"""Client-scoped Social vergelijking (Original UI), without TAOL social_search.db data."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from maaike.presentation import format_sync_moment
from maaike.repository import get_client, is_verified_link, list_posts, load_page_secret

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
EMPTY_DATA_MESSAGE = "Nog geen berichten opgehaald"
NOT_FETCHED_MESSAGE = "Nog geen berichten opgehaald"
NOT_MEASURED = "Nog niet gemeten"
INSUFFICIENT_GROWTH = "Nog onvoldoende meetmomenten om volgersgroei te berekenen"
META_CONNECT_REQUIRED_MESSAGE = (
    "Koppel eerst het Facebook- en Instagram-account van deze klant om berichten van concurrenten op te halen."
)
MAX_COMPETITORS = 10
MAX_COMPETITOR_LENGTH = 80
ERROR_EMPTY = "Vul een Instagram-gebruikersnaam in, bijvoorbeeld @gebruikersnaam."
ERROR_DUPLICATE = "Deze concurrent staat al op de lijst."
ERROR_LIMIT = "Je kunt maximaal 10 concurrenten toevoegen."
ERROR_TOO_LONG = "Gebruik maximaal 80 tekens."
PERIOD_PRESETS = (
    ("7d", "Laatste 7 dagen"),
    ("30d", "Laatste 30 dagen"),
    ("3m", "Laatste 3 maanden"),
    ("custom", "Eigen periode"),
)

DUTCH_MONTHS = (
    "",
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
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
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(client_comparison_preferences)").fetchall()}
    for name, declaration in (
        ("weekly_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("weekly_weekday", "INTEGER NOT NULL DEFAULT 0"),  # 0=ma … 6=zo
        ("weekly_time", "TEXT NOT NULL DEFAULT '09:00'"),
        ("weekly_note", "TEXT NOT NULL DEFAULT ''"),
        ("weekly_responsible", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE client_comparison_preferences ADD COLUMN {name} {declaration}")


def _meta_discovery_status(conn, client) -> dict:
    """Truthful check whether Facebook + Instagram Business Discovery are connected for this client."""
    fb_connected = bool(is_verified_link(client))
    secret = load_page_secret(conn, client.client_id)
    has_ig_secret = bool(secret is not None and secret[1] and secret[2])
    has_ig_handle_or_id = bool(client.meta_ig_username or (secret is not None and secret[1]))
    ig_connected = bool(fb_connected and has_ig_handle_or_id and has_ig_secret)
    ready = bool(fb_connected and ig_connected)
    return {
        "connected": ready,
        "facebook_connected": fb_connected,
        "facebook_page_name": client.meta_page_name if fb_connected else None,
        "instagram_connected": ig_connected,
        "instagram_username": client.meta_ig_username if ig_connected else None,
        "missing_message": None if ready else META_CONNECT_REQUIRED_MESSAGE,
    }


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
    meta_status = _meta_discovery_status(conn, client)
    own_row = _own_performance_row(conn, client, bounds) if bounds else None
    from maaike.account_crawl import ensure_crawl_tables

    ensure_crawl_tables(conn)
    crawl_by_user = {
        str(r["username"]).lower(): dict(r)
        for r in conn.execute(
            """
            SELECT username, last_crawled_at, last_success_at, last_crawl_status, last_crawl_detail, followers_count
            FROM client_crawl_accounts WHERE client_id = ?
            """,
            (client_id,),
        ).fetchall()
    }
    competitor_rows = []
    for name in competitors:
        crawl = crawl_by_user.get(name.lower()) or {}
        comp_post_rows = conn.execute(
            """
            SELECT published_at, likes, comments FROM posts
            WHERE client_id = ? AND lower(COALESCE(source_origin, '')) = ?
            """,
            (client_id, f"business_discovery:{name.lower()}"),
        ).fetchall()
        posts_count = len(comp_post_rows)
        in_period_rows = [
            r for r in comp_post_rows if bounds is not None and _in_bounds(r["published_at"], bounds)
        ]
        likes_vals = [int(r["likes"]) for r in in_period_rows if r["likes"] is not None]
        comment_vals = [int(r["comments"]) for r in in_period_rows if r["comments"] is not None]
        likes_total = sum(likes_vals) if likes_vals else None
        comments_total = sum(comment_vals) if comment_vals else None
        likes_avg = (likes_total / len(likes_vals)) if likes_vals else None
        comments_avg = (comments_total / len(comment_vals)) if comment_vals else None
        inter_vals = [
            (int(r["likes"] or 0) + int(r["comments"] or 0))
            for r in in_period_rows
            if r["likes"] is not None or r["comments"] is not None
        ]
        interaction_avg = (sum(inter_vals) / len(inter_vals)) if inter_vals else None

        crawl_status = str(crawl.get("last_crawl_status") or "").strip().lower()
        succeeded_crawl = crawl_status in {"completed", "completed_with_warnings"}
        fetched = posts_count > 0 or succeeded_crawl
        last_success_raw = crawl.get("last_success_at") or (
            crawl.get("last_crawled_at") if (succeeded_crawl or posts_count > 0) else None
        )
        last_succeeded_label = (
            format_sync_moment(last_success_raw) if last_success_raw else "Nog niet gelukt"
        )
        if posts_count > 0:
            posts_fetched_label = (
                f"Ja ({posts_count} {'bericht' if posts_count == 1 else 'berichten'} opgehaald)"
            )
        elif succeeded_crawl:
            posts_fetched_label = "Gecontroleerd (nog geen openbare berichten gevonden)"
        else:
            posts_fetched_label = "Nog geen berichten opgehaald"

        if not meta_status["connected"]:
            action_needed = True
            action_label = "Koppel eerst het Facebook- en Instagram-account van deze klant."
        elif crawl_status == "failed":
            action_needed = True
            action_label = (
                f"Laatste ophaalpoging mislukt — klik op ‘Opnieuw ophalen’ of controleer of @{name} een zakelijk Instagram-account is."
            )
        elif not fetched:
            action_needed = True
            action_label = "Klik op ‘Berichten van concurrenten ophalen’ of ‘Opnieuw ophalen’."
        else:
            action_needed = False
            action_label = "Geen actie nodig — berichten staan klaar."

        if fetched and crawl_status != "failed":
            status_label = f"Laatst gelukt: {last_succeeded_label}"
        elif crawl_status == "failed":
            status_label = "Ophalen mislukt"
        elif crawl:
            status_label = "Nog geen berichten opgehaald"
        else:
            status_label = NOT_FETCHED_MESSAGE

        competitor_rows.append(
            {
                "username": name,
                "display_name": f"@{name}",
                "role": "competitor",
                "has_fetched_data": fetched,
                "fetched_posts_total": posts_count,
                "posts_fetched_label": posts_fetched_label,
                "last_succeeded_at": last_success_raw,
                "last_succeeded_label": last_succeeded_label,
                "action_needed": action_needed,
                "action_label": action_label,
                "admin_error_detail": (
                    str(crawl.get("last_crawl_detail") or "").strip()
                    if crawl_status == "failed"
                    else None
                ),
                "status_label": status_label,
                "followers": crawl.get("followers_count"),
                "followers_label": (
                    str(crawl["followers_count"])
                    if crawl.get("followers_count") is not None
                    else (status_label if not fetched else NOT_FETCHED_MESSAGE)
                ),
                "posts_in_period": len(in_period_rows) if (fetched and bounds is not None) else None,
                "likes_total": likes_total,
                "comments_total": comments_total,
                "likes_avg": likes_avg,
                "comments_avg": comments_avg,
                "interaction_avg": interaction_avg,
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
        "client_name": client.name,
        "page_title": "Concurrenten",
        "meta_connection": meta_status,
        "own_account": {
            "username": own_username if meta_status["connected"] else None,
            "label": (
                f"@{own_username}"
                if (meta_status["connected"] and own_username)
                else (client.meta_page_name if meta_status["connected"] else None)
            ),
            "connected": meta_status["connected"],
            "hint": meta_status["missing_message"],
        },
        "competitors": competitors,
        "period_presets": [{"key": k, "label": label} for k, label in PERIOD_PRESETS],
        "period_key": key,
        "period_start": bounds[0].isoformat() if bounds else None,
        "period_end": bounds[1].isoformat() if bounds else None,
        "period_label": (
            f"{bounds[0]:%d-%m-%Y} t/m {bounds[1]:%d-%m-%Y}" if bounds else None
        ),
        "account_rows": account_rows,
        "content_rows": content_rows,
        "growth_rows": [
            {
                "username": own_username or "eigen-account",
                "display_name": f"@{own_username}" if own_username else f"{client.name} (eigen account)",
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
                    "missing_note": (
                        INSUFFICIENT_GROWTH
                        if any(r["username"] == name and r.get("has_fetched_data") for r in competitor_rows)
                        else NOT_FETCHED_MESSAGE
                    ),
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
            "note": "Dagelijkse cijfers van concurrenten worden gevuld zodra hun berichten zijn opgehaald.",
            "rows": [],
        },
        "refresh": {
            "available": meta_status["connected"],
            "button_label": "Berichten van concurrenten ophalen",
            "explanation": (
                "Haalt de nieuwste openbare Instagram-berichten, likes en reacties van je ingestelde concurrenten op."
            ),
            "message": (
                "Automatisch op de achtergrond: buiten werktijd (ma–vr na 18:00 en in het weekend) wordt elk uur één concurrent bijgewerkt. "
                "Handmatig: met ‘Berichten van concurrenten ophalen’ haal je de berichten direct op."
            ),
            "limitation": meta_status["missing_message"],
        },
        "schedule": _schedule_payload(),
        "weekly_plan": _weekly_plan(conn, client_id),
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


WEEKDAY_LABELS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


def _fallback_responsible_for_client(conn, client_id: int) -> str:
    """Reuse an already-configured responsible person for this client if set on logs or strategy."""
    has_logs = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'client_logs_weekly_preferences'"
    ).fetchone()
    if has_logs:
        logs_row = conn.execute(
            "SELECT responsible_name FROM client_logs_weekly_preferences WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        if logs_row and str(logs_row["responsible_name"] or "").strip():
            return str(logs_row["responsible_name"]).strip()
    try:
        from maaike.logs_weekly import _fallback_responsible_from_strategy

        return _fallback_responsible_from_strategy(conn, client_id)
    except Exception:
        return ""


def _format_dutch_date(day: date) -> str:
    month_name = DUTCH_MONTHS[day.month] if 1 <= day.month <= 12 else str(day.month)
    return f"{day.day} {month_name} {day.year}"


def _next_weekday(weekday: int, *, today: date | None = None) -> date:
    base = today or datetime.now(tz=AMSTERDAM).date()
    wd = max(0, min(6, int(weekday)))
    delta = (wd - base.weekday()) % 7
    return base + timedelta(days=delta)


def _weekly_plan(conn, client_id: int, *, today: date | None = None) -> dict:
    ensure_tables(conn)
    row = conn.execute(
        """
        SELECT weekly_enabled, weekly_weekday, weekly_time, weekly_note, weekly_responsible
        FROM client_comparison_preferences WHERE client_id = ?
        """,
        (client_id,),
    ).fetchone()
    enabled = bool(row["weekly_enabled"]) if row else False
    weekday = int(row["weekly_weekday"]) if row else 0
    weekday_label = WEEKDAY_LABELS[weekday] if 0 <= weekday <= 6 else WEEKDAY_LABELS[0]
    time_s = str(row["weekly_time"] if row else "09:00") or "09:00"
    note = str(row["weekly_note"] if row else "") or ""
    explicit_responsible = str(row["weekly_responsible"] if row else "").strip()
    responsible_name = explicit_responsible or _fallback_responsible_for_client(conn, client_id)
    next_day = _next_weekday(weekday, today=today)
    next_day_label = f"{weekday_label} {_format_dutch_date(next_day)} om {time_s}"
    if enabled:
        schedule_summary = f"Elke {weekday_label} om {time_s} (eerstvolgende moment: {next_day_label})."
        status_text = f"Gepland op elke {weekday_label} om {time_s} (handmatige controle)"
    else:
        schedule_summary = (
            "Nog geen vast controlemoment ingepland. Stel via ‘Planning & verantwoordelijke’ een vaste dag en tijd in."
        )
        status_text = "Nog niet ingepland (handmatige controle)"
    return {
        "enabled": enabled,
        "weekday": weekday,
        "weekday_label": weekday_label,
        "time": time_s,
        "note": note,
        "responsible_name": responsible_name,
        "has_responsible": bool(responsible_name),
        "next_check_date": next_day.isoformat(),
        "next_check_label": next_day_label,
        "schedule_summary": schedule_summary,
        "auto_execute": False,
        "execution_mode_label": "Handmatige controle door het team; berichten ophalen gebeurt op de achtergrond automatisch",
        "background_fetch_summary": (
            "Als Facebook en Instagram gekoppeld zijn, werkt HAMSTER buiten werktijd (ma–vr na 18:00 en in het weekend) elk uur automatisch één concurrent bij."
        ),
        "manual_check_summary": (
            "Het bekijken en vergelijken van de concurrenten gebeurt handmatig op het geplande moment."
        ),
        "user_steps": [
            "Controleer in de concurrentenlijst of bij elk account recente berichten klaarstaan en er geen ‘Actie nodig’ staat.",
            "Klik zo nodig op ‘Berichten van concurrenten ophalen’ (of bij één account op ‘Opnieuw ophalen’).",
            "Bekijk bij Prestaties en Contentmix welke berichten en formats bij concurrenten opvallen.",
        ],
        "status": status_text,
        "weekday_options": [{"value": i, "label": label} for i, label in enumerate(WEEKDAY_LABELS)],
    }


def save_weekly_plan(
    conn,
    client_id: int,
    *,
    enabled: bool = False,
    weekday: int = 0,
    time: str = "09:00",
    note: str = "",
    responsible_name: str | None = None,
) -> dict:
    ensure_tables(conn)
    wd = max(0, min(6, int(weekday)))
    time_s = str(time or "09:00").strip() or "09:00"
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc).isoformat()
    row = conn.execute(
        """
        SELECT competitors_json, period_key, custom_start, custom_end, weekly_responsible
        FROM client_comparison_preferences WHERE client_id = ?
        """,
        (client_id,),
    ).fetchone()
    competitors = row["competitors_json"] if row else "[]"
    period_key = (row["period_key"] if row else None) or "3m"
    custom_start = row["custom_start"] if row else None
    custom_end = row["custom_end"] if row else None
    existing_resp = str(row["weekly_responsible"] if row else "") or ""
    resp_s = existing_resp if responsible_name is None else str(responsible_name or "").strip()
    conn.execute(
        """
        INSERT INTO client_comparison_preferences (
            client_id, competitors_json, period_key, custom_start, custom_end, updated_at,
            weekly_enabled, weekly_weekday, weekly_time, weekly_note, weekly_responsible
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            weekly_enabled = excluded.weekly_enabled,
            weekly_weekday = excluded.weekly_weekday,
            weekly_time = excluded.weekly_time,
            weekly_note = excluded.weekly_note,
            weekly_responsible = excluded.weekly_responsible,
            updated_at = excluded.updated_at
        """,
        (
            client_id,
            competitors,
            period_key,
            custom_start,
            custom_end,
            now,
            1 if enabled else 0,
            wd,
            time_s,
            str(note or "").strip(),
            resp_s,
        ),
    )
    return _weekly_plan(conn, client_id)


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
        raise ValueError("Kies een geldige periode.")
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
