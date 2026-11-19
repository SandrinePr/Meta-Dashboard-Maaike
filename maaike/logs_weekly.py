"""Weekly Logs control schedule — separate from Competitors weekly plan.

Auto-execute stays off: this only stores when Maaike reviews Logs and which
two-month window that review uses.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any

WEEKDAY_LABELS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


def ensure_logs_weekly_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS client_logs_weekly_preferences (
            client_id INTEGER PRIMARY KEY,
            weekly_enabled INTEGER NOT NULL DEFAULT 0,
            weekly_weekday INTEGER NOT NULL DEFAULT 0,
            weekly_time TEXT NOT NULL DEFAULT '09:00',
            weekly_note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
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


def _payload(
    *,
    enabled: bool,
    weekday: int,
    time_s: str,
    note: str,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    wd = max(0, min(6, int(weekday)))
    next_day = next_weekly_check_date(weekday=wd, from_day=today)
    window = two_month_logs_window(next_day)
    return {
        "enabled": enabled,
        "weekday": wd,
        "weekday_label": WEEKDAY_LABELS[wd],
        "time": time_s or "09:00",
        "note": note or "",
        "auto_execute": False,
        "status": (
            "gepland (handmatig; aparte Logs-controle, niet Competitors; auto-uitvoering uit)"
            if enabled
            else "uit"
        ),
        "next_check_date": next_day.isoformat(),
        "window_from": window["from"],
        "window_to": window["to"],
        "weekday_options": [{"value": i, "label": label} for i, label in enumerate(WEEKDAY_LABELS)],
        "separate_from_competitors": True,
    }


def get_logs_weekly_plan(conn, client_id: int, *, today: date | None = None) -> dict[str, Any]:
    ensure_logs_weekly_table(conn)
    row = conn.execute(
        """
        SELECT weekly_enabled, weekly_weekday, weekly_time, weekly_note
        FROM client_logs_weekly_preferences WHERE client_id = ?
        """,
        (client_id,),
    ).fetchone()
    if row is None:
        return _payload(enabled=False, weekday=0, time_s="09:00", note="", today=today)
    return _payload(
        enabled=bool(row["weekly_enabled"]),
        weekday=int(row["weekly_weekday"] or 0),
        time_s=str(row["weekly_time"] or "09:00"),
        note=str(row["weekly_note"] or ""),
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
    today: date | None = None,
) -> dict[str, Any]:
    ensure_logs_weekly_table(conn)
    now = datetime.now(tz=timezone.utc).isoformat()
    wd = max(0, min(6, int(weekday)))
    time_s = str(time or "09:00").strip() or "09:00"
    conn.execute(
        """
        INSERT INTO client_logs_weekly_preferences (
            client_id, weekly_enabled, weekly_weekday, weekly_time, weekly_note, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            weekly_enabled = excluded.weekly_enabled,
            weekly_weekday = excluded.weekly_weekday,
            weekly_time = excluded.weekly_time,
            weekly_note = excluded.weekly_note,
            updated_at = excluded.updated_at
        """,
        (client_id, 1 if enabled else 0, wd, time_s, str(note or "").strip(), now),
    )
    return get_logs_weekly_plan(conn, client_id, today=today)
