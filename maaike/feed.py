"""Client-scoped post feed, filters and monthly top lists for the React dashboard.

Uses only the Maaike SQLite database. Missing metrics stay unavailable; 0 stays 0.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from maaike.presentation import (
    NOT_AVAILABLE,
    RATING_PENDING,
    _kind_label,
    _platform_label,
    format_metric,
    format_sync_moment,
)
from maaike.repository import UNSET_LABEL, StoredPost, connection_label, get_client, is_verified_link, list_posts

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
FEED_PAGE_SIZE = 24
MIN_QUERY_LENGTH = 3

_METRIC_SORT = {
    "views": "views",
    "likes": "likes",
    "comments": "comments",
    "reach": "reach",
    "shares": "shares",
    "saves": "saves",
}

_PERF_METRICS = (
    ("views", "Views"),
    ("likes", "Likes"),
    ("comments", "Comments"),
    ("reach", "Reach"),
    ("shares", "Shares"),
    ("saves", "Saves"),
)


def parse_media_urls(raw: str | None) -> list[dict[str, str]]:
    """Split stored media lines into display items. Videos are marked as video."""
    if not raw:
        return []
    items: list[dict[str, str]] = []
    for line in raw.splitlines():
        url = line.strip()
        if not url.startswith("https://"):
            continue
        if not _looks_like_media(url):
            continue
        lower = url.lower().split("?", 1)[0]
        kind = "video" if lower.endswith((".mp4", ".mov", ".m4v", ".webm")) else "image"
        items.append({"url": url, "kind": kind})
    return items


def _looks_like_media(url: str) -> bool:
    """Skip permalink pages that were stored alongside CDN assets."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if host in {"facebook.com", "www.facebook.com", "fb.com", "www.fb.com", "instagram.com", "www.instagram.com", "instagr.am"}:
        return False
    if any(token in host for token in ("scontent", "cdninstagram", "fbcdn", "lookaside")):
        return True
    return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".m4v", ".webm"))


def feed_card(post: StoredPost, *, formula_rating: dict | None = None) -> dict:
    """JSON shape for one visual feed card."""
    media = parse_media_urls(post.media_urls)
    cover = next((item for item in media if item["kind"] == "image"), None)
    has_video = any(item["kind"] == "video" for item in media)
    formula = formula_rating or {}
    rating_label = formula.get("label") or post.rating_text or RATING_PENDING
    return {
        "id": post.post_id,
        "platform": post.platform,
        "platform_label": _platform_label(post.platform),
        "account": post.account_name or NOT_AVAILABLE,
        "published_at": post.published_at,
        "published_label": format_sync_moment(post.published_at),
        "content_kind": post.content_kind,
        "content_kind_label": _kind_label(post.content_kind),
        "permalink": post.permalink,
        "caption": post.caption or "",
        "external_id": post.external_id or "",
        "media": media,
        "cover_url": cover["url"] if cover else None,
        "has_video": has_video,
        "media_note": _media_note(media, has_video, cover),
        "format_id": post.format_id,
        "format_name": post.format_name or UNSET_LABEL,
        "pillar_id": post.pillar_id,
        "pillar_name": post.pillar_name or UNSET_LABEL,
        "hook": post.hook or "",
        "metrics": {
            "views": _metric(post, "views", post.views),
            "reach": _metric(post, "reach", post.reach),
            "likes": _metric(post, "likes", post.likes),
            "comments": _metric(post, "comments", post.comments),
            "shares": _metric(post, "shares", post.shares),
            "saves": _metric(post, "saves", post.saves),
            "clicks": _metric(post, "clicks", post.clicks),
        },
        "rating": rating_label,
        "formula_rating": formula or None,
        "excel_rating": post.rating_text,
        "excel_rating_source": post.rating_source_label,
    }


def filter_posts(
    posts: list[StoredPost],
    *,
    query: str = "",
    platforms: set[str] | None = None,
    kinds: set[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[StoredPost]:
    trimmed = query.strip()
    platforms = platforms or set()
    kinds = kinds or set()
    out: list[StoredPost] = []
    for post in posts:
        if platforms and post.platform not in platforms:
            continue
        kind = (post.content_kind or "").strip().lower()
        if kinds and kind not in kinds and not _kind_alias_match(kind, kinds):
            continue
        published = _local_date(post.published_at)
        if date_from and (published is None or published < date_from):
            continue
        if date_to and (published is None or published > date_to):
            continue
        if trimmed and not _matches_query(post, trimmed):
            continue
        out.append(post)
    return out


def sort_posts(posts: list[StoredPost], sort: str) -> list[StoredPost]:
    key = (sort or "published_desc").strip().lower()
    if key == "published_asc":
        return sorted(posts, key=lambda post: (post.published_at or "", post.post_id))
    if key.endswith("_desc") and key[:-5] in _METRIC_SORT:
        metric = _METRIC_SORT[key[:-5]]
        return sorted(
            posts,
            key=lambda post: (_metric_value(post, metric) is not None, _metric_value(post, metric) or -1, post.published_at or ""),
            reverse=True,
        )
    return sorted(posts, key=lambda post: (post.published_at or "", post.post_id), reverse=True)


def feed_payload(
    conn,
    client_id: int,
    *,
    query: str = "",
    platforms: list[str] | None = None,
    kinds: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "published_desc",
    offset: int = 0,
    limit: int = FEED_PAGE_SIZE,
) -> dict:
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("This client is not in the list.")
    from maaike.rating import get_rating_settings, rate_post

    all_posts = list_posts(conn, client_id)
    rating_settings = get_rating_settings(conn, client_id)
    platform_set = {item.strip().lower() for item in platforms or [] if item.strip()}
    kind_set = {item.strip().lower() for item in kinds or [] if item.strip()}
    filtered = filter_posts(
        all_posts,
        query=query,
        platforms=platform_set,
        kinds=kind_set,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )
    ordered = sort_posts(filtered, sort)
    start = max(0, int(offset))
    size = max(1, min(int(limit), 100))
    page = ordered[start : start + size]
    available_kinds = sorted(
        {
            (post.content_kind or "").strip().lower()
            for post in all_posts
            if (post.content_kind or "").strip()
        }
    )
    return {
        "client_id": client_id,
        "client_name": client.name,
        "total": len(ordered),
        "offset": start,
        "limit": size,
        "has_more": start + size < len(ordered),
        "query_too_short": bool(query.strip()) and len(query.strip()) < MIN_QUERY_LENGTH,
        "min_query_length": MIN_QUERY_LENGTH,
        "available_kinds": available_kinds,
        "kind_labels": {kind: _kind_label(kind) for kind in available_kinds},
        "posts": [feed_card(post, formula_rating=rate_post(post, rating_settings)) for post in page],
        "empty_message": (
            f"No posts yet for {client.name}."
            if not all_posts
            else "No posts match these filters."
        ),
    }


def post_detail(conn, client_id: int, post_id: int) -> dict | None:
    from maaike.rating import get_rating_settings, rate_post

    settings = get_rating_settings(conn, client_id)
    for post in list_posts(conn, client_id):
        if post.post_id == post_id:
            return feed_card(post, formula_rating=rate_post(post, settings))
    return None


def overview_payload(conn, client_id: int) -> dict:
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("This client is not in the list.")
    posts = list_posts(conn, client_id)
    ig = sum(1 for post in posts if post.platform == "instagram")
    fb = sum(1 for post in posts if post.platform == "facebook")
    published = [post.published_at for post in posts if post.published_at]
    return {
        "client_id": client_id,
        "client_name": client.name,
        "status_label": connection_label(client),
        "connected": is_verified_link(client),
        "page_name": client.meta_page_name,
        "ig_username": client.meta_ig_username,
        "instagram_count": ig,
        "facebook_count": fb,
        "post_count": len(posts),
        "period_from": format_sync_moment(min(published)) if published else NOT_AVAILABLE,
        "period_until": format_sync_moment(max(published)) if published else NOT_AVAILABLE,
        "synced_at": format_sync_moment(
            max((post.last_synced_at for post in posts if post.last_synced_at), default=None)
        ),
        "fetch_status": client.last_fetch_status,
        "fetch_message": client.last_fetch_detail
        or (
            "No posts fetched for this client yet."
            if is_verified_link(client)
            else "Connect Meta first via client settings."
        ),
        "fetch_available": is_verified_link(client),
    }


def performance_payload(conn, client_id: int, *, year: int | None = None, month: int | None = None) -> dict:
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("This client is not in the list.")
    posts = list_posts(conn, client_id)
    months = _available_months(posts)
    if not months:
        return {
            "client_id": client_id,
            "months": [],
            "selected": None,
            "sections": [],
            "empty_message": f"No posts yet for {client.name} to show performance by month.",
        }
    if year is None or month is None:
        year, month = months[0]
    selected = (int(year), int(month))
    if selected not in months:
        selected = months[0]
    month_posts = [
        post
        for post in posts
        if _year_month(post.published_at) == selected
    ]
    sections = []
    for metric, label in _PERF_METRICS:
        ranked = sorted(
            (post for post in month_posts if _metric_value(post, metric) is not None),
            key=lambda post: _metric_value(post, metric) or 0,
            reverse=True,
        )[:3]
        sections.append(
            {
                "metric": metric,
                "label": label,
                "posts": [
                    {
                        **feed_card(post),
                        "rank": index,
                        "metric_value": _metric_value(post, metric),
                    }
                    for index, post in enumerate(ranked, start=1)
                ],
            }
        )
    return {
        "client_id": client_id,
        "months": [
            {
                "year": year_value,
                "month": month_value,
                "label": _month_label(year_value, month_value),
                "count": sum(1 for post in posts if _year_month(post.published_at) == (year_value, month_value)),
            }
            for year_value, month_value in months
        ],
        "selected": {"year": selected[0], "month": selected[1], "label": _month_label(*selected)},
        "post_count": len(month_posts),
        "sections": sections,
        "empty_message": None,
    }


def _metric(post: StoredPost, name: str, value: int | None) -> dict:
    return {
        "value": value,
        "label": format_metric(value, previous=name in post.previous_metrics),
        "previous": name in post.previous_metrics,
    }


def _metric_value(post: StoredPost, name: str) -> int | None:
    return getattr(post, name, None)


def _media_note(media: list[dict[str, str]], has_video: bool, cover: dict | None) -> str | None:
    if not media:
        return "No media available for this post."
    if has_video and cover is None:
        return "Only a video file is stored. Play it where the browser allows; this is not a full video analysis."
    if has_video and cover is not None:
        return "There is a video and a cover. The cover is not a full video analysis."
    if len(media) > 1:
        return f"Carousel with {len(media)} media items."
    return None


def _matches_query(post: StoredPost, query: str) -> bool:
    if len(query) < MIN_QUERY_LENGTH:
        return True
    needle = query.casefold()
    haystacks = [
        post.caption or "",
        post.hook or "",
        post.external_id or "",
        post.account_name or "",
        post.permalink or "",
        post.format_name or "",
        post.pillar_name or "",
    ]
    return any(needle in text.casefold() for text in haystacks)


def _kind_alias_match(kind: str, kinds: set[str]) -> bool:
    aliases = {
        "carousel": {"carousel", "carousel_album", "album"},
        "carousel_album": {"carousel", "carousel_album", "album"},
        "reel": {"reel", "reels"},
        "reels": {"reel", "reels"},
        "photo": {"photo", "image"},
        "image": {"photo", "image"},
        "video": {"video", "video_inline"},
    }
    for selected in kinds:
        if kind == selected:
            return True
        if kind in aliases.get(selected, set()):
            return True
    return False


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _local_date(value: str | None) -> date | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return parsed.astimezone(AMSTERDAM).date()


def _year_month(value: str | None) -> tuple[int, int] | None:
    local = _local_date(value)
    if local is None:
        return None
    return local.year, local.month


def _available_months(posts: list[StoredPost]) -> list[tuple[int, int]]:
    found = {
        pair
        for post in posts
        if (pair := _year_month(post.published_at)) is not None
    }
    return sorted(found, reverse=True)


def _month_label(year: int, month: int) -> str:
    names = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    return f"{names[month - 1]} {year}"


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
