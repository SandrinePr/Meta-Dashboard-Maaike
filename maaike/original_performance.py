"""Performance per month — Original analytics logic on one Maaike client."""

from __future__ import annotations

from datetime import date

from maaike.feed import feed_card
from maaike.presentation import format_sync_moment
from maaike.repository import get_client, list_posts

METRIC_KEYS = ("views", "likes", "comments", "saves", "shares")
METRIC_LABELS = {
    "views": "Views",
    "likes": "Likes",
    "comments": "Comments",
    "saves": "Saves",
    "shares": "Shares",
}
MONTH_NAMES = (
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


def format_month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


def performance_month_payload(
    conn,
    client_id: int,
    *,
    year: int | None = None,
    month: int | None = None,
    platforms: set[str] | None = None,
) -> dict:
    """Top 3 per metric for posts published in the selected month (lifetime totals)."""
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("This client is not in the list.")
    platforms = platforms or {"instagram", "facebook"}
    posts = [p for p in list_posts(conn, client_id) if p.platform in platforms]
    months = _available_months(posts)
    if not months:
        return {
            "client_id": client_id,
            "months": [],
            "selected": None,
            "sections": [],
            "post_count": 0,
            "platforms": sorted(platforms),
            "empty_message": "No posts available yet to show performance by month.",
            "caption": None,
            "latest_month_label": None,
            "refresh_available": bool(client.meta_status == "connected"),
        }

    counts = _month_counts(posts)
    if year is None or month is None:
        year, month = next((ym for ym in months if counts.get(ym, 0) > 0), months[0])
    selected = (int(year), int(month))
    if selected not in months:
        selected = months[0]

    month_posts = [p for p in posts if _ym(p.published_at) == selected]
    latest = next((ym for ym in months if counts.get(ym, 0) > 0), None)
    sections = []
    visible = [m for m in METRIC_KEYS if m != "saves" or "instagram" in platforms]
    for metric in visible:
        ranked = []
        for post in month_posts:
            if metric == "saves" and post.platform == "facebook":
                continue
            value = getattr(post, metric, None)
            if value is None:
                continue
            ranked.append((int(value), post))
        ranked.sort(key=lambda item: (-item[0], item[1].published_at or ""))
        sections.append(
            {
                "metric": metric,
                "label": METRIC_LABELS[metric],
                "header": f"{METRIC_LABELS[metric]} · top 3 · lifetime",
                "posts": [
                    {
                        **feed_card(post),
                        "rank": index,
                        "metric_value": value,
                        "metric_value_label": f"{value:,}".replace(",", "."),
                    }
                    for index, (value, post) in enumerate(ranked[:3], start=1)
                ],
            }
        )

    return {
        "client_id": client_id,
        "months": [
            {
                "year": y,
                "month": m,
                "label": format_month_label(y, m),
                "select_label": (
                    format_month_label(y, m)
                    if counts.get((y, m), 0)
                    else f"{format_month_label(y, m)} (no posts yet)"
                ),
                "count": counts.get((y, m), 0),
            }
            for y, m in months
        ],
        "selected": {
            "year": selected[0],
            "month": selected[1],
            "label": format_month_label(*selected),
        },
        "post_count": len(month_posts),
        "platforms": sorted(platforms),
        "sections": sections,
        "empty_message": None,
        "caption": (
            f"Top posts published in {format_month_label(*selected)}, "
            "ranked by lifetime totals from the database. "
            "Click Refresh figures for the latest Meta data."
        ),
        "latest_month_label": format_month_label(*latest) if latest else None,
        "refresh_available": connection_ok(client),
        "synced_at": format_sync_moment(client.last_fetch_at) if client.last_fetch_at else None,
    }


def connection_ok(client) -> bool:
    from maaike.repository import connection_label

    from maaike.repository import is_verified_link

    return is_verified_link(client)


def _ym(value: str | None) -> tuple[int, int] | None:
    if not value or len(value) < 7:
        return None
    try:
        return int(value[0:4]), int(value[5:7])
    except ValueError:
        return None


def _month_counts(posts) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}
    for post in posts:
        key = _ym(post.published_at)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _available_months(posts) -> list[tuple[int, int]]:
    today = date.today()
    current = (today.year, today.month)
    keys = [k for k in (_ym(p.published_at) for p in posts) if k]
    if not keys:
        return [current]
    earliest = min(keys)
    latest = max(max(keys), current)
    return _months_between(latest, earliest)


def _months_between(newest: tuple[int, int], oldest: tuple[int, int]) -> list[tuple[int, int]]:
    y, m = newest
    end_y, end_m = oldest
    months: list[tuple[int, int]] = []
    while (y, m) >= (end_y, end_m):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return months
