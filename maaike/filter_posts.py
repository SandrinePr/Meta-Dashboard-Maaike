"""Original-style Filter posts search over one Maaike client's posts and comments."""

from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from maaike.feed import FEED_PAGE_SIZE, MIN_QUERY_LENGTH, feed_card, parse_media_urls
from maaike.presentation import NOT_AVAILABLE, _kind_label, _platform_label, format_sync_moment
from maaike.repository import get_client, list_posts

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
_HASHTAG = re.compile(r"#([A-Za-z0-9_]+)", re.I)
_MENTION = re.compile(r"@([A-Za-z0-9._]+)", re.I)

MATCH_TYPES = ("comment", "tag", "hashtag", "caption")


def sync_totals(conn, client_id: int) -> dict:
    """Sidebar Synchronisatie counts for one client. Missing comments stay null, never invent 0."""
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("This client is not in the list.")
    posts = list_posts(conn, client_id)
    ig_posts = sum(1 for p in posts if p.platform == "instagram")
    fb_posts = sum(1 for p in posts if p.platform == "facebook")
    comments_ready = _comments_table_ready(conn)
    ig_comments = None
    fb_comments = None
    # Empty comments table after migration is not the same as “0 comments from Meta”.
    if comments_ready:
        total_comments = int(
            conn.execute(
                "SELECT COUNT(*) FROM comments WHERE client_id = ?",
                (client_id,),
            ).fetchone()[0]
        )
        if total_comments > 0:
            ig_comments = int(
                conn.execute(
                    "SELECT COUNT(*) FROM comments WHERE client_id = ? AND platform = 'instagram'",
                    (client_id,),
                ).fetchone()[0]
            )
            fb_comments = int(
                conn.execute(
                    "SELECT COUNT(*) FROM comments WHERE client_id = ? AND platform = 'facebook'",
                    (client_id,),
                ).fetchone()[0]
            )
    return {
        "client_id": client_id,
        "instagram_posts": ig_posts,
        "facebook_posts": fb_posts,
        "instagram_comments": ig_comments,
        "facebook_comments": fb_comments,
        "instagram_comments_label": (
            str(ig_comments) if ig_comments is not None else "not fetched yet"
        ),
        "facebook_comments_label": (
            str(fb_comments) if fb_comments is not None else "not fetched yet"
        ),
        "synced_at": format_sync_moment(client.last_fetch_at) if client.last_fetch_at else "not fetched yet",
        "comments_synced": ig_comments is not None or fb_comments is not None,
    }


def filter_search_payload(
    conn,
    client_id: int,
    *,
    query: str = "",
    platforms: set[str] | None = None,
    match_types: set[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = 0,
    limit: int = FEED_PAGE_SIZE,
) -> dict:
    """Search posts and comments like Original Filter posts."""
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("This client is not in the list.")
    platforms = platforms or {"instagram", "facebook"}
    match_types = match_types or set(MATCH_TYPES)
    trimmed = (query or "").strip()
    if trimmed and len(trimmed) < MIN_QUERY_LENGTH:
        return {
            "client_id": client_id,
            "query": trimmed,
            "query_too_short": True,
            "min_query_length": MIN_QUERY_LENGTH,
            "results": [],
            "total": 0,
            "has_more": False,
            "empty_message": None,
            "totals": None,
        }

    from maaike.rating import get_rating_settings, rate_post

    rating_settings = get_rating_settings(conn, client_id)
    posts = [
        p
        for p in list_posts(conn, client_id)
        if p.platform in platforms and _in_date(p.published_at, date_from, date_to)
    ]
    comments = _list_comments(conn, client_id, platforms, date_from, date_to)

    results: list[dict] = []
    if not trimmed:
        # Original shows recent posts when query empty.
        for post in posts[: max(limit + offset, 20)]:
            results.append(
                _post_result(post, query="", formula_rating=rate_post(post, rating_settings))
            )
    else:
        for post in posts:
            membership = _post_membership(post.caption or "", trimmed)
            if membership & match_types:
                item = _post_result(
                    post,
                    query=trimmed,
                    membership=membership,
                    formula_rating=rate_post(post, rating_settings),
                )
                results.append(item)
        if "comment" in match_types:
            for comment in comments:
                membership = _comment_membership(comment["text"], trimmed)
                if membership & match_types or "comment" in match_types and _text_match(
                    comment["text"], trimmed
                ):
                    if not _text_match(comment["text"], trimmed):
                        continue
                    results.append(_comment_result(comment, query=trimmed, membership=membership))

    results.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    total = len(results)
    page = results[offset : offset + limit]
    return {
        "client_id": client_id,
        "query": trimmed,
        "query_too_short": False,
        "min_query_length": MIN_QUERY_LENGTH,
        "results": page,
        "total": total,
        "has_more": offset + len(page) < total,
        "empty_message": (
            None
            if page
            else (
                "No results found in the local database."
                if trimmed
                else f"No posts yet for {client.name}."
            )
        ),
        "totals": _engagement_totals([r for r in page if r["entity_type"] == "post"]),
        "comments_available": _comments_table_ready(conn),
        "comments_note": (
            None
            if _comments_table_ready(conn)
            else "Comment texts have not been fetched for this client yet. Sync Meta to load comments."
        ),
    }


def _comments_table_ready(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='comments'"
    ).fetchone()
    return row is not None


def _list_comments(conn, client_id, platforms, date_from, date_to) -> list[dict]:
    if not _comments_table_ready(conn):
        return []
    rows = conn.execute(
        """
        SELECT id, post_id, platform, external_id, text, permalink, published_at, author_name
        FROM comments
        WHERE client_id = ?
        ORDER BY published_at DESC
        """,
        (client_id,),
    ).fetchall()
    out = []
    for row in rows:
        if row["platform"] not in platforms:
            continue
        if not _in_date(row["published_at"], date_from, date_to):
            continue
        out.append(dict(row))
    return out


def _in_date(value: str | None, date_from: date | None, date_to: date | None) -> bool:
    if not date_from and not date_to:
        return True
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        day = dt.astimezone(AMSTERDAM).date()
    except ValueError:
        return False
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


def _text_match(haystack: str, query: str) -> bool:
    return query.casefold() in (haystack or "").casefold()


def _post_membership(caption: str, query: str) -> set[str]:
    text = caption or ""
    q = query.strip()
    membership: set[str] = set()
    tags = _HASHTAG.findall(text)
    mentions = _MENTION.findall(text)
    if any(q.casefold() in tag.casefold() or tag.casefold() in q.casefold().lstrip("#") for tag in tags):
        membership.add("hashtag")
    if any(q.casefold() in m.casefold() or m.casefold() in q.casefold().lstrip("@") for m in mentions):
        membership.add("tag")
    stripped = _MENTION.sub(" ", _HASHTAG.sub(" ", text))
    if _text_match(stripped, q) or _text_match(text, q):
        membership.add("caption")
    return membership


def _comment_membership(text: str, query: str) -> set[str]:
    membership = {"comment"}
    tags = _HASHTAG.findall(text or "")
    mentions = _MENTION.findall(text or "")
    q = query.strip()
    if any(q.casefold() in tag.casefold() for tag in tags):
        membership.add("hashtag")
    if any(q.casefold() in m.casefold() for m in mentions):
        membership.add("tag")
    return membership


def _post_result(post, *, query: str, membership: set[str] | None = None, formula_rating: dict | None = None) -> dict:
    card = feed_card(post, formula_rating=formula_rating)
    membership = membership or set()
    return {
        **card,
        "entity_type": "post",
        "entity_id": post.post_id,
        "text": post.caption or "",
        "match_badges": sorted(membership & {"caption", "hashtag", "tag"}),
        "content_type_label": "Post",
    }


def _comment_result(comment: dict, *, query: str, membership: set[str]) -> dict:
    return {
        "id": f"comment-{comment['id']}",
        "entity_type": "comment",
        "entity_id": comment["id"],
        "post_id": comment["post_id"],
        "platform": comment["platform"],
        "platform_label": _platform_label(comment["platform"]),
        "published_at": comment["published_at"],
        "published_label": format_sync_moment(comment["published_at"]),
        "text": comment["text"] or "",
        "caption": comment["text"] or "",
        "permalink": comment["permalink"],
        "author_name": comment["author_name"] or NOT_AVAILABLE,
        "content_kind_label": "Comment",
        "content_type_label": "Comment",
        "match_badges": sorted(membership & {"comment", "hashtag", "tag"}),
        "cover_url": None,
        "media": [],
        "metrics": {},
        "account": comment["author_name"] or NOT_AVAILABLE,
    }


def _engagement_totals(post_results: list[dict]) -> dict | None:
    keys = ("views", "likes", "comments", "saves", "shares")
    totals: dict[str, int] = {}
    for post in post_results:
        metrics = post.get("metrics") or {}
        for key in keys:
            metric = metrics.get(key) or {}
            value = metric.get("value")
            if value is None:
                continue
            totals[key] = totals.get(key, 0) + int(value)
    return totals or None
