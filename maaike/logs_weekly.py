"""Weekly Logs control schedule & completion — separate from Competitors weekly plan.

Auto-execute stays off: this stores when Jet, Mo or Maaike reviews client posts,
who is responsible (if configured), which posts in the two-month window still need
classification, and when the latest weekly check was completed.
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from maaike.presentation import _platform_label, format_sync_moment
from maaike.repository import list_posts

WEEKDAY_LABELS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")

CHECKLIST_ITEMS = [
    "Kies het juiste contentformat uit de legenda.",
    "Kies de juiste contentpijler uit de legenda.",
    "Vul de hook in (de openingszin of het haakje van het bericht).",
    "Controleer of cijfers en een eventuele Figma-link kloppen en klik op Indeling opslaan.",
]


def ensure_logs_weekly_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS client_logs_weekly_preferences (
            client_id INTEGER PRIMARY KEY,
            weekly_enabled INTEGER NOT NULL DEFAULT 0,
            weekly_weekday INTEGER NOT NULL DEFAULT 0,
            weekly_time TEXT NOT NULL DEFAULT '09:00',
            weekly_note TEXT NOT NULL DEFAULT '',
            responsible_name TEXT NOT NULL DEFAULT '',
            last_completed_at TEXT,
            last_completed_by TEXT NOT NULL DEFAULT '',
            last_completed_window_from TEXT NOT NULL DEFAULT '',
            last_completed_window_to TEXT NOT NULL DEFAULT '',
            last_completed_count INTEGER,
            updated_at TEXT NOT NULL
        )
        """
    )
    cols = {
        str(r[1])
        for r in conn.execute("PRAGMA table_info(client_logs_weekly_preferences)").fetchall()
    }
    for name, declaration in (
        ("responsible_name", "TEXT NOT NULL DEFAULT ''"),
        ("last_completed_at", "TEXT"),
        ("last_completed_by", "TEXT NOT NULL DEFAULT ''"),
        ("last_completed_window_from", "TEXT NOT NULL DEFAULT ''"),
        ("last_completed_window_to", "TEXT NOT NULL DEFAULT ''"),
        ("last_completed_count", "INTEGER"),
    ):
        if name not in cols:
            conn.execute(
                f"ALTER TABLE client_logs_weekly_preferences ADD COLUMN {name} {declaration}"
            )


def two_month_logs_window(today: date | None = None) -> dict[str, str]:
    """Same rule as frontend SocialPostsPage.twoMonthLogsWindow."""
    today = today or date.today()
    start = date(today.year if today.month > 1 else today.year - 1, today.month - 1 or 12, 1)
    end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return {"from": start.isoformat(), "to": end.isoformat()}


def next_weekly_check_date(
    *,
    weekday: int,
    from_day: date | None = None,
) -> date:
    """Next occurrence of weekday (0=Monday) on or after from_day."""
    day = from_day or date.today()
    wd = max(0, min(6, int(weekday)))
    delta = (wd - day.weekday()) % 7
    return day + timedelta(days=delta)


def _iso_day(value: str | None) -> str:
    raw = str(value or "").strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    return ""


def _fallback_responsible_from_strategy(conn, client_id: int) -> str:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'client_strategy'"
    ).fetchone()
    if has_table is None:
        return ""
    row = conn.execute(
        "SELECT strategy_fields_json FROM client_strategy WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if row is None or not row["strategy_fields_json"]:
        return ""
    try:
        fields = json.loads(row["strategy_fields_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    for key in ("wekelijkse_controle_verantwoordelijke", "verantwoordelijke", "contactpersonen"):
        val = str(fields.get(key) or "").strip()
        if val and len(val) <= 80:
            return val
    return ""


def _window_review_summary(
    conn,
    client_id: int,
    *,
    window_from: str,
    window_to: str,
) -> dict[str, Any]:
    posts = list_posts(conn, client_id)
    in_window = []
    for post in posts:
        day = _iso_day(post.published_at)
        if day and window_from <= day <= window_to:
            in_window.append(post)

    unchecked: list[dict[str, Any]] = []
    for post in in_window:
        missing_labels: list[str] = []
        if post.format_id is None:
            missing_labels.append("Contentformat")
        if post.pillar_id is None:
            missing_labels.append("Contentpijler")
        if not str(post.hook or "").strip():
            missing_labels.append("Hook")
        if not missing_labels:
            continue
        caption_clean = " ".join(str(post.caption or "").split())
        preview = (
            f"{caption_clean[:72]}…"
            if len(caption_clean) > 72
            else (caption_clean or post.permalink or f"Bericht #{post.post_id}")
        )
        unchecked.append(
            {
                "id": post.post_id,
                "platform": post.platform,
                "platform_label": post.platform_label or _platform_label(post.platform),
                "published_at": post.published_at,
                "published_label": format_sync_moment(post.published_at),
                "caption_preview": preview,
                "missing_labels": missing_labels,
            }
        )

    total = len(in_window)
    unchecked_count = len(unchecked)
    checked_count = max(0, total - unchecked_count)
    return {
        "posts_in_window_count": total,
        "checked_in_window_count": checked_count,
        "unchecked_in_window_count": unchecked_count,
        "unchecked_posts": unchecked[:25],
        "all_posts_count": len(posts),
    }


def _payload(
    conn,
    client_id: int,
    *,
    enabled: bool,
    weekday: int,
    time_s: str,
    note: str,
    responsible_name: str = "",
    last_completed_at: str | None = None,
    last_completed_by: str = "",
    last_completed_window_from: str = "",
    last_completed_window_to: str = "",
    last_completed_count: int | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    wd = max(0, min(6, int(weekday)))
    # Preserve exact next_check_date behavior when not completed today; if completed today on the
    # scheduled weekday, advance the next planned check by a week.
    completed_day = _iso_day(last_completed_at)
    start_day = (
        today + timedelta(days=1)
        if completed_day and completed_day == today.isoformat() and today.weekday() == wd
        else today
    )
    next_day = next_weekly_check_date(weekday=wd, from_day=start_day)
    window = two_month_logs_window(today)
    # Keep window_from/window_to anchored on next_day when enabled (compatible with existing tests).
    plan_window = two_month_logs_window(next_day)
    review = _window_review_summary(
        conn,
        client_id,
        window_from=plan_window["from"],
        window_to=plan_window["to"],
    )
    explicit_resp = str(responsible_name or "").strip()
    resolved_resp = explicit_resp or _fallback_responsible_from_strategy(conn, client_id)
    last_completed_label = (
        format_sync_moment(last_completed_at)
        if last_completed_at
        else None
    )
    if last_completed_label in {"not available", "niet beschikbaar", "—"}:
        last_completed_label = last_completed_at

    return {
        "enabled": enabled,
        "weekday": wd,
        "weekday_label": WEEKDAY_LABELS[wd],
        "time": time_s or "09:00",
        "note": note or "",
        "responsible_name": resolved_resp,
        "has_responsible": bool(resolved_resp),
        "auto_execute": False,
        "status": (
            "gepland (handmatig; aparte Logs-controle, niet Competitors; auto-uitvoering uit)"
            if enabled
            else "uit"
        ),
        "next_check_date": next_day.isoformat(),
        "window_from": plan_window["from"],
        "window_to": plan_window["to"],
        "current_window_from": window["from"],
        "current_window_to": window["to"],
        "weekday_options": [{"value": i, "label": label} for i, label in enumerate(WEEKDAY_LABELS)],
        "separate_from_competitors": True,
        "checklist_items": list(CHECKLIST_ITEMS),
        "last_completed_at": last_completed_at,
        "last_completed_label": last_completed_label,
        "last_completed_by": str(last_completed_by or "").strip(),
        "last_completed_window_from": last_completed_window_from or "",
        "last_completed_window_to": last_completed_window_to or "",
        "last_completed_count": last_completed_count,
        **review,
    }


def get_logs_weekly_plan(conn, client_id: int, *, today: date | None = None) -> dict[str, Any]:
    ensure_logs_weekly_table(conn)
    row = conn.execute(
        """
        SELECT weekly_enabled, weekly_weekday, weekly_time, weekly_note,
               responsible_name, last_completed_at, last_completed_by,
               last_completed_window_from, last_completed_window_to, last_completed_count
        FROM client_logs_weekly_preferences WHERE client_id = ?
        """,
        (client_id,),
    ).fetchone()
    if row is None:
        return _payload(
            conn,
            client_id,
            enabled=False,
            weekday=0,
            time_s="09:00",
            note="",
            today=today,
        )
    return _payload(
        conn,
        client_id,
        enabled=bool(row["weekly_enabled"]),
        weekday=int(row["weekly_weekday"] or 0),
        time_s=str(row["weekly_time"] or "09:00"),
        note=str(row["weekly_note"] or ""),
        responsible_name=str(row["responsible_name"] or ""),
        last_completed_at=row["last_completed_at"],
        last_completed_by=str(row["last_completed_by"] or ""),
        last_completed_window_from=str(row["last_completed_window_from"] or ""),
        last_completed_window_to=str(row["last_completed_window_to"] or ""),
        last_completed_count=(
            int(row["last_completed_count"]) if row["last_completed_count"] is not None else None
        ),
        today=today,
    )


def save_logs_weekly_plan(
    conn,
    client_id: int,
    *,
    enabled: bool = False,
    weekday: int = 0,
    time: str = "09:00",
    note: str = "",
    responsible_name: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    ensure_logs_weekly_table(conn)
    now = datetime.now(tz=timezone.utc).isoformat()
    wd = max(0, min(6, int(weekday)))
    time_s = str(time or "09:00").strip() or "09:00"
    existing = conn.execute(
        "SELECT responsible_name FROM client_logs_weekly_preferences WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    resp = (
        str(responsible_name).strip()[:80]
        if responsible_name is not None
        else str(existing["responsible_name"] or "").strip() if existing else ""
    )
    conn.execute(
        """
        INSERT INTO client_logs_weekly_preferences (
            client_id, weekly_enabled, weekly_weekday, weekly_time, weekly_note,
            responsible_name, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            weekly_enabled = excluded.weekly_enabled,
            weekly_weekday = excluded.weekly_weekday,
            weekly_time = excluded.weekly_time,
            weekly_note = excluded.weekly_note,
            responsible_name = excluded.responsible_name,
            updated_at = excluded.updated_at
        """,
        (client_id, 1 if enabled else 0, wd, time_s, str(note or "").strip(), resp, now),
    )
    return get_logs_weekly_plan(conn, client_id, today=today)


def complete_logs_weekly_check(
    conn,
    client_id: int,
    *,
    completed_by: str = "",
    note: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Record completion of the weekly post check for ``client_id``."""
    ensure_logs_weekly_table(conn)
    current = get_logs_weekly_plan(conn, client_id, today=today)
    now = datetime.now(tz=timezone.utc).isoformat()
    who = str(completed_by or current.get("responsible_name") or "").strip()[:80]
    next_note = str(note).strip() if note is not None else str(current.get("note") or "")
    resp = str(completed_by).strip()[:80] if str(completed_by or "").strip() else str(current.get("responsible_name") or "")
    checked_count = int(current.get("checked_in_window_count") or 0)

    conn.execute(
        """
        INSERT INTO client_logs_weekly_preferences (
            client_id, weekly_enabled, weekly_weekday, weekly_time, weekly_note,
            responsible_name, last_completed_at, last_completed_by,
            last_completed_window_from, last_completed_window_to, last_completed_count,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            weekly_note = excluded.weekly_note,
            responsible_name = CASE
                WHEN excluded.responsible_name != '' THEN excluded.responsible_name
                ELSE client_logs_weekly_preferences.responsible_name
            END,
            last_completed_at = excluded.last_completed_at,
            last_completed_by = excluded.last_completed_by,
            last_completed_window_from = excluded.last_completed_window_from,
            last_completed_window_to = excluded.last_completed_window_to,
            last_completed_count = excluded.last_completed_count,
            updated_at = excluded.updated_at
        """,
        (
            client_id,
            1 if current.get("enabled") else 0,
            int(current.get("weekday") or 0),
            str(current.get("time") or "09:00"),
            next_note,
            resp,
            now,
            who,
            str(current.get("window_from") or ""),
            str(current.get("window_to") or ""),
            checked_count,
            now,
        ),
    )
    return get_logs_weekly_plan(conn, client_id, today=today)
