"""Original-style Filter posts search over one Maaike client's posts and comments."""

from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from maaike.feed import FEED_PAGE_SIZE, MIN_QUERY_LENGTH, feed_card, parse_media_urls
from maaike.presentation import NOT_AVAILABLE, _kind_label, _platform_label, format_sync_moment
from maaike.repository import get_client, is_verified_link, latest_sync_at, list_posts

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
_HASHTAG = re.compile(r"#([A-Za-z0-9_]+)", re.I)
_MENTION = re.compile(r"@([A-Za-z0-9._]+)", re.I)

MATCH_TYPES = ("comment", "tag", "hashtag", "caption")


def build_channel_status(conn, client, posts=None) -> dict:
    """Truthful per-client connection + fetch status for Socialmediaberichten."""
    own_posts = list(posts) if posts is not None else list_posts(conn, client.client_id)
    own_count = len(own_posts)
    ig_count = sum(1 for p in own_posts if p.platform == "instagram")
    fb_count = sum(1 for p in own_posts if p.platform == "facebook")
    other_count = max(0, own_count - ig_count - fb_count)

    raw_row = conn.execute(
        "SELECT meta_page_id, meta_ig_user_id FROM clients WHERE id = ?",
        (client.client_id,),
    ).fetchone()
    has_page_id = bool(raw_row and str(raw_row["meta_page_id"] or "").strip())
    has_ig_id = bool(raw_row and str(raw_row["meta_ig_user_id"] or "").strip())

    verified = is_verified_link(client)
    fb_connected = bool(verified and (has_page_id or bool((client.meta_page_name or "").strip())))
    ig_connected = bool(verified and (has_ig_id or bool((client.meta_ig_username or "").strip())))

    fb_label = (
        f"Gekoppeld ({client.meta_page_name})"
        if fb_connected and client.meta_page_name
        else ("Gekoppeld" if fb_connected else "Niet gekoppeld")
    )
    ig_label = (
        f"Gekoppeld (@{client.meta_ig_username.lstrip('@')})"
        if ig_connected and client.meta_ig_username
        else ("Gekoppeld" if ig_connected else "Niet gekoppeld")
    )

    last_raw = client.last_fetch_at or latest_sync_at(conn, client.client_id)
    formatted_sync = format_sync_moment(last_raw) if last_raw else None
    has_fetched = bool(formatted_sync and formatted_sync not in {"not available", "niet beschikbaar", "—"})
    last_fetched_label = formatted_sync if has_fetched else "Nog nooit opgehaald"

    meta_state = str(client.meta_status or "not_connected")
    if not verified:
        state_code = "connect_required"
        headline = "Koppel eerst je accounts"
        if meta_state in {"expired", "revoked"}:
            next_action = (
                f"De koppeling met Facebook/Instagram voor {client.name} is verlopen. "
                "Koppel de accounts opnieuw om berichten op te halen."
            )
        elif own_count > 0:
            next_action = (
                f"Facebook en Instagram zijn nog niet gekoppeld voor {client.name}. "
                f"Er staan al wel {own_count} ingelezen bericht(en) klaar om te bekijken."
            )
        else:
            next_action = (
                f"Koppel Facebook en Instagram voor {client.name} om berichten automatisch op te halen."
            )
        action_key = "connect_accounts"
        action_label = "Accounts koppelen"
    elif own_count == 0:
        state_code = "fetch_first_posts"
        headline = "Haal je eerste berichten op"
        if has_fetched:
            next_action = (
                f"De accounts van {client.name} zijn gekoppeld, maar er zijn nog geen berichten gevonden. "
                "Haal je berichten opnieuw op of voeg handmatig een bericht toe."
            )
        else:
            next_action = (
                f"Facebook en Instagram zijn gekoppeld voor {client.name}. "
                "Klik op de knop om de eerste berichten op te halen."
            )
        action_key = "fetch_first"
        action_label = "Eerste berichten ophalen"
    else:
        state_code = "ready_to_view"
        headline = "Je berichten zijn klaar om te bekijken"
        missing_channels = []
        if not fb_connected:
            missing_channels.append("Facebook")
        if not ig_connected:
            missing_channels.append("Instagram")
        extra = (
            f" Let op: {', '.join(missing_channels)} is nog niet gekoppeld."
            if missing_channels
            else ""
        )
        next_action = (
            f"Er staan {own_count} berichten van {client.name} klaar. "
            f"Haal nieuwe berichten op wanneer je cijfers wilt bijwerken.{extra}"
        )
        action_key = "fetch_updates"
        action_label = "Nieuwe berichten ophalen"

    admin_detail = None
    if not verified and client.meta_status_detail:
        admin_detail = str(client.meta_status_detail).strip() or None
    elif client.last_fetch_status in {"error", "failed"} and client.last_fetch_detail:
        admin_detail = str(client.last_fetch_detail).strip() or None

    return {
        "state": state_code,
        "headline": headline,
        "next_action": next_action,
        "action_key": action_key,
        "action_label": action_label,
        "connected": verified,
        "meta_status": meta_state,
        "facebook": {
            "connected": fb_connected,
            "account_name": client.meta_page_name or None,
            "label": fb_label,
            "post_count": fb_count,
        },
        "instagram": {
            "connected": ig_connected,
            "account_name": f"@{client.meta_ig_username.lstrip('@')}" if client.meta_ig_username else None,
            "label": ig_label,
            "post_count": ig_count,
        },
        "other_post_count": other_count,
        "own_post_count": own_count,
        "has_fetched": has_fetched,
        "last_fetched_at": last_raw,
        "last_fetched_label": last_fetched_label,
        "last_fetch_status": client.last_fetch_status,
        "admin_error_detail": admin_detail,
    }


def sync_totals(conn, client_id: int) -> dict:
    """Sidebar Synchronisatie counts for one client. Missing comments stay null, never invent 0."""
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("This client is not in the list.")
    posts = list_posts(conn, client_id)
    own_post_ids = {int(p.post_id) for p in posts}
    ig_posts = sum(1 for p in posts if p.platform == "instagram")
    fb_posts = sum(1 for p in posts if p.platform == "facebook")
    comments_ready = _comments_table_ready(conn)
    ig_comments = None
    fb_comments = None
    # Empty comments table after migration is not the same as “0 comments from Meta”.
    if comments_ready and own_post_ids:
        placeholders = ",".join("?" for _ in own_post_ids)
        params_all = (client_id, *sorted(own_post_ids))
        total_comments = int(
            conn.execute(
                f"SELECT COUNT(*) FROM comments WHERE client_id = ? AND post_id IN ({placeholders})",
                params_all,
            ).fetchone()[0]
        )
        if total_comments > 0:
            ig_comments = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM comments WHERE client_id = ? AND platform = 'instagram' AND post_id IN ({placeholders})",
                    params_all,
                ).fetchone()[0]
            )
            fb_comments = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM comments WHERE client_id = ? AND platform = 'facebook' AND post_id IN ({placeholders})",
                    params_all,
                ).fetchone()[0]
            )
    channel_status = build_channel_status(conn, client, posts=posts)
    return {
        "client_id": client_id,
        "instagram_posts": ig_posts,
        "facebook_posts": fb_posts,
        "instagram_comments": ig_comments,
        "facebook_comments": fb_comments,
        "instagram_comments_label": (
            str(ig_comments) if ig_comments is not None else "Nog niet opgehaald"
        ),
        "facebook_comments_label": (
            str(fb_comments) if fb_comments is not None else "Nog niet opgehaald"
        ),
        "synced_at": channel_status["last_fetched_label"],
        "comments_synced": ig_comments is not None or fb_comments is not None,
        "channel_status": channel_status,
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
                _post_result(
                    post,
                    query="",
                    formula_rating=rate_post(post, rating_settings),
                    client_id=client_id,
                )
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
                    client_id=client_id,
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
    own_post_ids = {int(p.post_id) for p in list_posts(conn, client_id)}
    if not own_post_ids:
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
        if int(row["post_id"]) not in own_post_ids:
            continue
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


def _post_result(
    post,
    *,
    query: str,
    membership: set[str] | None = None,
    formula_rating: dict | None = None,
    client_id: int | None = None,
) -> dict:
    card = feed_card(post, formula_rating=formula_rating, client_id=client_id)
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
