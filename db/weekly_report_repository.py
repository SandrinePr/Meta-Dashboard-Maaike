"""Store weekly report snapshots and AI prompt texts. No network calls."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai.prompts import DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_PROMPT


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class WeeklyReportRecord:
    report_id: int
    created_at: str
    period_start: str
    period_end: str
    own_account_id: int | None
    account_label: str | None
    snapshot: dict[str, Any]
    ai_status: str
    ai_summary: str | None
    ai_advice: list[str]
    ai_model: str | None
    ai_generated_at: str | None


def _advice_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _row_to_record(row: sqlite3.Row) -> WeeklyReportRecord:
    snapshot = json.loads(row["snapshot_json"])
    if not isinstance(snapshot, dict):
        snapshot = {}
    return WeeklyReportRecord(
        report_id=int(row["id"]),
        created_at=str(row["created_at"]),
        period_start=str(row["period_start"]),
        period_end=str(row["period_end"]),
        own_account_id=int(row["own_account_id"]) if row["own_account_id"] is not None else None,
        account_label=row["account_label"],
        snapshot=snapshot,
        ai_status=str(row["ai_status"]),
        ai_summary=row["ai_summary"],
        ai_advice=_advice_list(row["ai_advice_json"]),
        ai_model=row["ai_model"],
        ai_generated_at=row["ai_generated_at"],
    )


def save_weekly_report(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    own_account_id: int | None,
    account_label: str | None,
    snapshot: dict[str, Any],
) -> int:
    """Store a frozen numeric snapshot. Does not call AI."""
    cursor = conn.execute(
        """
        INSERT INTO weekly_reports (
            created_at, period_start, period_end, own_account_id, account_label,
            snapshot_json, ai_status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'not_configured')
        """,
        (
            _now(),
            period_start,
            period_end,
            own_account_id,
            account_label,
            json.dumps(snapshot, ensure_ascii=False),
        ),
    )
    return int(cursor.lastrowid)


def list_weekly_reports(conn: sqlite3.Connection, *, limit: int = 40) -> list[WeeklyReportRecord]:
    rows = conn.execute(
        """
        SELECT id, created_at, period_start, period_end, own_account_id, account_label,
               snapshot_json, ai_status, ai_summary, ai_advice_json, ai_model, ai_generated_at
        FROM weekly_reports
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def get_weekly_report(conn: sqlite3.Connection, report_id: int) -> WeeklyReportRecord | None:
    row = conn.execute(
        """
        SELECT id, created_at, period_start, period_end, own_account_id, account_label,
               snapshot_json, ai_status, ai_summary, ai_advice_json, ai_model, ai_generated_at
        FROM weekly_reports
        WHERE id = ?
        """,
        (report_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def save_analysis(
    conn: sqlite3.Connection,
    report_id: int,
    *,
    status: str,
    summary: str | None,
    advice: list[str] | None,
    model: str | None,
) -> None:
    conn.execute(
        """
        UPDATE weekly_reports
        SET ai_status = ?,
            ai_summary = ?,
            ai_advice_json = ?,
            ai_model = ?,
            ai_generated_at = ?
        WHERE id = ?
        """,
        (
            status,
            summary,
            json.dumps(advice, ensure_ascii=False) if advice else None,
            model,
            _now(),
            report_id,
        ),
    )


def get_prompts(conn: sqlite3.Connection) -> tuple[str, str]:
    row = conn.execute(
        "SELECT system_prompt, user_prompt FROM ai_prompt_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_PROMPT
    return str(row["system_prompt"]), str(row["user_prompt"])


def save_prompts(conn: sqlite3.Connection, system_prompt: str, user_prompt: str) -> None:
    existing = conn.execute("SELECT id FROM ai_prompt_settings WHERE id = 1").fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO ai_prompt_settings (id, system_prompt, user_prompt, updated_at)
            VALUES (1, ?, ?, ?)
            """,
            (system_prompt, user_prompt, _now()),
        )
        return
    conn.execute(
        """
        UPDATE ai_prompt_settings
        SET system_prompt = ?, user_prompt = ?, updated_at = ?
        WHERE id = 1
        """,
        (system_prompt, user_prompt, _now()),
    )
