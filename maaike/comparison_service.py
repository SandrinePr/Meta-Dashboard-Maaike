"""Client-scoped Social vergelijking (Original UI), without TAOL social_search.db data."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from maaike.repository import get_client, list_posts

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
EMPTY_DATA_MESSAGE = "No data fetched yet"
NOT_FETCHED_MESSAGE = "Not fetched yet"
NOT_MEASURED = "Not measured"
INSUFFICIENT_GROWTH = "Not enough measurement history yet"
MAX_COMPETITORS = 10
MAX_COMPETITOR_LENGTH = 80
ERROR_EMPTY = "Enter an account name or username."
ERROR_DUPLICATE = "This competitor is already on the list."
ERROR_LIMIT = "You can add at most 10 competitors."
ERROR_TOO_LONG = "Use at most 80 characters."
PERIOD_PRESETS = (
    ("7d", "Last 7 days"),
    ("30d", "Last 30 days"),
    ("3m", "Last 3 months"),
    ("custom", "Custom period"),
)


def ensure_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            external_id TEXT NOT NULL,
            text TEXT,
            permalink TEXT,
            published_at TEXT,
            author_name TEXT,
            UNIQUE(client_id, platform, external_id),
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_comments_client_platform
            ON comments(client_id, platform);
        CREATE TABLE IF NOT EXISTS client_comparison_preferences (
            client_id INTEGER PRIMARY KEY,
            competitors_json TEXT NOT NULL DEFAULT '[]',
            period_key TEXT NOT NULL DEFAULT '3m',
            custom_start TEXT,
            custom_end TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );
        """
    )


def normalize_username(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned.startswith("@"):
        cleaned = cleaned[1:].strip()
    return cleaned


def comparison_state(
    conn,
    client_id: int,
    *,
    period_key: str | None = None,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> dict:
    ensure_tables(conn)
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("Deze klant staat niet in de lijst.")
    prefs = _prefs(conn, client_id)
    key = period_key or prefs["period_key"]
    start = custom_start
    end = custom_end
    if key == "custom":
        start = start or _parse_day(prefs.get("custom_start"))
        end = end or _parse_day(prefs.get("custom_end"))
    bounds = resolve_period(key, today=datetime.now(tz=AMSTERDAM).date(), custom_start=start, custom_end=end)
    competitors = prefs["competitors"]
    own_username = client.meta_ig_username
    own_row = _own_performance_row(conn, client, bounds) if bounds else None
    from maaike.account_crawl import ensure_crawl_tables

    ensure_crawl_tables(conn)
    crawl_by_user = {
        str(r["username"]).lower(): dict(r)
        for r in conn.execute(
            """
            SELECT username, last_crawled_at, last_crawl_status, last_crawl_detail, followers_count
            FROM client_crawl_accounts WHERE client_id = ?
            """,
            (client_id,),
        ).fetchall()
    }
    competitor_rows = []
    for name in competitors:
        crawl = crawl_by_user.get(name.lower()) or {}
        posts_count = conn.execute(
            """
            SELECT COUNT(*) AS n FROM posts
            WHERE client_id = ? AND lower(COALESCE(source_origin, '')) = ?
            """,
            (client_id, f"business_discovery:{name.lower()}"),
        ).fetchone()["n"]
        fetched = int(posts_count or 0) > 0 or crawl.get("last_crawl_status") == "completed"
        if fetched:
            status_label = (
                f"Laatst opgehaald {crawl.get('last_crawled_at') or '—'} · "
                f"{crawl.get('last_crawl_status') or 'ok'}"
            )
        elif crawl.get("last_crawl_status") == "failed":
            status_label = f"Crawl mislukt · {crawl.get('last_crawl_detail') or ''}"
        elif crawl:
            status_label = "Gekoppeld — wacht op automatische ophaal buiten werktijd"
        else:
            status_label = NOT_FETCHED_MESSAGE
        competitor_rows.append(
            {
                "username": name,
                "display_name": f"@{name}",
                "role": "competitor",
                "has_fetched_data": fetched,
                "status_label": status_label,
                "followers": crawl.get("followers_count"),
                "followers_label": (
                    str(crawl["followers_count"])
                    if crawl.get("followers_count") is not None
                    else (status_label if not fetched else NOT_FETCHED_MESSAGE)
                ),
                "posts_in_period": int(posts_count or 0) if fetched else None,
                "likes_total": None,
                "comments_total": None,
                "likes_avg": None,
                "comments_avg": None,
                "interaction_avg": None,
                "last_crawled_at": crawl.get("last_crawled_at"),
                "last_crawl_status": crawl.get("last_crawl_status"),
            }
        )
    account_rows = ([own_row] if own_row else []) + competitor_rows
    content_rows = []
    if own_row and own_row.get("has_fetched_data") and bounds:
        content_rows.append(_own_content_mix(conn, client_id, bounds))
    for name in competitors:
        crawl = crawl_by_user.get(name.lower()) or {}
        fetched = any(r["username"] == name and r.get("has_fetched_data") for r in competitor_rows)
        if fetched and bounds:
            content_rows.append(_competitor_content_mix(conn, client_id, name, bounds))
        else:
            content_rows.append(
                {
                    "username": name,
                    "display_name": f"@{name}",
                    "has_fetched_data": False,
                    "status_label": NOT_FETCHED_MESSAGE,
                    "reels": None,
                    "images": None,
                    "carousels": None,
                    "other_videos": None,
                    "unknown": None,
                    "last_crawled_at": crawl.get("last_crawled_at"),
                }
            )

    return {
        "client_id": client_id,
        "page_title": "Social comparison",
        "own_account": {
            "username": own_username,
            "label": f"@{own_username}" if own_username else None,
            "connected": bool(own_username),
            "hint": (
                None
                if own_username
                else "No own Instagram account linked yet — connect Meta via client settings."
            ),
        },
        "competitors": competitors,
        "period_presets": [{"key": k, "label": label} for k, label in PERIOD_PRESETS],
        "period_key": key,
        "period_start": bounds[0].isoformat() if bounds else None,
        "period_end": bounds[1].isoformat() if bounds else None,
        "period_label": (
            f"{bounds[0]:%d-%m-%Y} to {bounds[1]:%d-%m-%Y}" if bounds else None
        ),
        "account_rows": account_rows,
        "content_rows": content_rows,
        "growth_rows": [
            {
                "username": own_username or "own account",
                "display_name": f"@{own_username}" if own_username else "Own account",
                "insufficient": True,
                "missing_note": INSUFFICIENT_GROWTH,
                "followers_start": None,
                "followers_end": None,
                "followers_delta": None,
                "followers_pct": None,
            },
            *[
                {
                    "username": name,
                    "display_name": f"@{name}",
                    "insufficient": True,
                    "missing_note": NOT_FETCHED_MESSAGE,
                    "followers_start": None,
                    "followers_end": None,
                    "followers_delta": None,
                    "followers_pct": None,
                }
                for name in competitors
            ],
        ],
        "top_posts": [],
        "top_posts_empty": EMPTY_DATA_MESSAGE,
        "daily": {
            "message": NOT_MEASURED,
            "note": "Daily metrics for competitors are filled only after Refresh data (Business Discovery).",
            "rows": [],
        },
        "refresh": {
            "available": bool(own_username),
            "message": (
                "Automatisch: buiten werktijd (ma–vr na 18:00 / weekend) elk uur één concurrent. "
                "Handmatig: knop ‘Haal concurrenten nu op’ werkt altijd, ook overdag. "
                "Zonder crawl tonen concurrenten ‘Nog niet opgehaald’, nooit 0."
            ),
            "limitation": None,
        },
        "schedule": _schedule_payload(),
        "empty_data_message": EMPTY_DATA_MESSAGE,
        "not_fetched_message": NOT_FETCHED_MESSAGE,
    }


def _schedule_payload() -> dict:
    try:
        from maaike.competitor_scheduler import schedule_status

        return schedule_status()
    except Exception:
        return {
            "enabled": False,
            "detail": "Scheduler niet beschikbaar in dit proces.",
        }


def save_competitors(conn, client_id: int, competitors: list[str]) -> dict:
    ensure_tables(conn)
    cleaned = []
    for name in competitors:
        item = normalize_username(name)
        if not item:
            continue
        if len(item) > MAX_COMPETITOR_LENGTH:
            raise ValueError(ERROR_TOO_LONG)
        if item.casefold() in {c.casefold() for c in cleaned}:
            continue
        cleaned.append(item)
    if len(cleaned) > MAX_COMPETITORS:
        raise ValueError(ERROR_LIMIT)
    _write_prefs(conn, client_id, competitors=cleaned)
    return comparison_state(conn, client_id)


def add_competitor(conn, client_id: int, name: str) -> dict:
    from maaike.account_crawl import link_crawl_account

    prefs = _prefs(conn, client_id)
    current = list(prefs["competitors"])
    cleaned = normalize_username(name)
    if not cleaned:
        raise ValueError(ERROR_EMPTY)
    if len(cleaned) > MAX_COMPETITOR_LENGTH:
        raise ValueError(ERROR_TOO_LONG)
    if len(current) >= MAX_COMPETITORS:
        raise ValueError(ERROR_LIMIT)
    if cleaned.casefold() in {c.casefold() for c in current}:
        raise ValueError(ERROR_DUPLICATE)
    current.append(cleaned)
    state = save_competitors(conn, client_id, current)
    # Auto-link for Business Discovery; hourly off-hours job will fetch.
    link_crawl_account(conn, client_id, cleaned)
    return state


def remove_competitor(conn, client_id: int, name: str) -> dict:
    prefs = _prefs(conn, client_id)
    target = normalize_username(name)
    updated = [c for c in prefs["competitors"] if c.casefold() != target.casefold()]
    return save_competitors(conn, client_id, updated)


def save_period(
    conn,
    client_id: int,
    period_key: str,
    *,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> dict:
    if period_key not in {k for k, _ in PERIOD_PRESETS}:
        raise ValueError("Unknown period.")
    _write_prefs(
        conn,
        client_id,
        period_key=period_key,
        custom_start=custom_start.isoformat() if custom_start else None,
        custom_end=custom_end.isoformat() if custom_end else None,
    )
    return comparison_state(
        conn,
        client_id,
        period_key=period_key,
        custom_start=custom_start,
        custom_end=custom_end,
    )


def resolve_period(
    period_key: str,
    *,
    today: date,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> tuple[date, date] | None:
    if period_key == "7d":
        return today - timedelta(days=6), today
    if period_key == "30d":
        return today - timedelta(days=29), today
    if period_key == "3m":
        return _subtract_months(today, 3), today
    if period_key == "custom":
        if custom_start is None or custom_end is None or custom_start > custom_end:
            return None
        return custom_start, custom_end
    return None


def _subtract_months(value: date, months: int) -> date:
    import calendar

    month_index = value.month - 1 - months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))


def _own_performance_row(conn, client, bounds: tuple[date, date] | None) -> dict:
    username = client.meta_ig_username or "eigen-account"
    if bounds is None:
        return {
            "username": username,
            "display_name": f"@{username}" if client.meta_ig_username else "Eigen account",
            "role": "own",
            "has_fetched_data": False,
            "status_label": EMPTY_DATA_MESSAGE,
        }
    posts = [
        p
        for p in list_posts(conn, client.client_id)
        if p.platform == "instagram" and _in_bounds(p.published_at, bounds)
    ]
    if not posts and not client.meta_ig_username:
        return {
            "username": username,
            "display_name": "Eigen account",
            "role": "own",
            "has_fetched_data": False,
            "status_label": EMPTY_DATA_MESSAGE,
        }
    likes_vals = [p.likes for p in posts if p.likes is not None]
    comment_vals = [p.comments for p in posts if p.comments is not None]
    likes_total = sum(likes_vals) if likes_vals else None
    comments_total = sum(comment_vals) if comment_vals else None
    n_like = len(likes_vals)
    n_comment = len(comment_vals)
    interaction_vals = []
    for p in posts:
        if p.likes is None and p.comments is None:
            continue
        interaction_vals.append((p.likes or 0) + (p.comments or 0))
    return {
        "username": username,
        "display_name": f"@{username}" if client.meta_ig_username else "Eigen account",
        "role": "own",
        "has_fetched_data": True,
        "status_label": "local (posts for this client)",
        "followers": None,
        "followers_label": NOT_MEASURED,
        "posts_in_period": len(posts),
        "likes_total": likes_total,
        "comments_total": comments_total,
        "likes_avg": (likes_total / n_like) if n_like else None,
        "comments_avg": (comments_total / n_comment) if n_comment else None,
        "interaction_avg": (sum(interaction_vals) / len(interaction_vals)) if interaction_vals else None,
        "posts_with_interaction": len(interaction_vals),
        "metrics_incomplete": len(interaction_vals) < len(posts),
    }


def _count_content_kinds(kinds: list[str]) -> dict:
    reels = images = carousels = other_videos = unknown = 0
    for raw in kinds:
        kind = (raw or "").lower()
        if kind in {"reel", "reels"}:
            reels += 1
        elif kind in {"image", "photo", "foto"}:
            images += 1
        elif "carousel" in kind or kind == "album":
            carousels += 1
        elif "video" in kind:
            other_videos += 1
        else:
            unknown += 1
    return {
        "reels": reels,
        "images": images,
        "carousels": carousels,
        "other_videos": other_videos,
        "unknown": unknown,
    }


def _own_content_mix(conn, client_id: int, bounds: tuple[date, date]) -> dict:
    posts = [
        p
        for p in list_posts(conn, client_id)
        if p.platform == "instagram" and _in_bounds(p.published_at, bounds)
        and not str(getattr(p, "source_origin", "") or "").lower().startswith("business_discovery:")
    ]
    client = get_client(conn, client_id)
    counts = _count_content_kinds([p.content_kind for p in posts])
    return {
        "username": client.meta_ig_username if client else "",
        "display_name": f"@{client.meta_ig_username}" if client and client.meta_ig_username else "Eigen account",
        "has_fetched_data": True,
        **counts,
    }


def _competitor_content_mix(
    conn, client_id: int, username: str, bounds: tuple[date, date]
) -> dict:
    origin = f"business_discovery:{username.lower()}"
    rows = conn.execute(
        """
        SELECT content_kind, published_at
        FROM posts
        WHERE client_id = ? AND lower(COALESCE(source_origin, '')) = ?
        """,
        (client_id, origin),
    ).fetchall()
    kinds = [r["content_kind"] for r in rows if _in_bounds(r["published_at"], bounds)]
    counts = _count_content_kinds(kinds)
    return {
        "username": username,
        "display_name": f"@{username}",
        "has_fetched_data": True,
        **counts,
    }


def _in_bounds(published_at: str | None, bounds: tuple[date, date]) -> bool:
    if not published_at:
        return False
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        day = dt.astimezone(AMSTERDAM).date()
    except ValueError:
        return False
    return bounds[0] <= day <= bounds[1]


def _prefs(conn, client_id: int) -> dict:
    ensure_tables(conn)
    row = conn.execute(
        "SELECT competitors_json, period_key, custom_start, custom_end FROM client_comparison_preferences WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if row is None:
        return {"competitors": [], "period_key": "3m", "custom_start": None, "custom_end": None}
    try:
        competitors = json.loads(row["competitors_json"] or "[]")
    except json.JSONDecodeError:
        competitors = []
    return {
        "competitors": [str(x) for x in competitors if str(x).strip()],
        "period_key": row["period_key"] or "3m",
        "custom_start": row["custom_start"],
        "custom_end": row["custom_end"],
    }


def _write_prefs(conn, client_id: int, **fields) -> None:
    ensure_tables(conn)
    current = _prefs(conn, client_id)
    competitors = fields.get("competitors", current["competitors"])
    period_key = fields.get("period_key", current["period_key"])
    custom_start = fields.get("custom_start", current["custom_start"])
    custom_end = fields.get("custom_end", current["custom_end"])
    now = datetime.now(tz=AMSTERDAM).isoformat()
    conn.execute(
        """
        INSERT INTO client_comparison_preferences (
            client_id, competitors_json, period_key, custom_start, custom_end, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            competitors_json = excluded.competitors_json,
            period_key = excluded.period_key,
            custom_start = excluded.custom_start,
            custom_end = excluded.custom_end,
            updated_at = excluded.updated_at
        """,
        (client_id, json.dumps(competitors), period_key, custom_start, custom_end, now),
    )


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
