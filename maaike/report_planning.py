"""Rapportplanning: editable monthly schedule concept (Europe/Amsterdam).

Auto-execute stays off until explicitly enabled. Runs are idempotent via run_key.
Paid AI execute is never started from this module.
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import threading
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from maaike.ai_status import public_ai_status
from maaike.repository import list_clients

logger = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
DEFAULT_START_TIME = "09:00"
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_RETRY_MAX = 2
DEFAULT_RETRY_WAIT_SECONDS = 120
DEFAULT_COST_LIMIT_USD = 25.0
ORIGIN_PLAN = "report_plan"

_scheduler = None
_started = False
_start_lock = threading.Lock()
_job_lock = threading.Lock()
_last_tick: dict[str, Any] = {
    "at": None,
    "action": "never",
    "detail": "Report planning scheduler not started yet.",
}


def amsterdam_now() -> datetime:
    return datetime.now(tz=AMSTERDAM)


def ensure_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS report_plans (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL DEFAULT 'Maandelijkse klantrapporten',
            auto_execute INTEGER NOT NULL DEFAULT 0,
            timezone TEXT NOT NULL DEFAULT 'Europe/Amsterdam',
            schedule_kind TEXT NOT NULL DEFAULT 'recurring',
            once_date TEXT,
            recurring_rule TEXT NOT NULL DEFAULT 'last_sunday_of_month',
            start_time TEXT NOT NULL DEFAULT '09:00',
            interval_minutes INTEGER NOT NULL DEFAULT 60,
            period_mode TEXT NOT NULL DEFAULT 'previous_calendar_month',
            period_year INTEGER,
            period_month INTEGER,
            client_ids_json TEXT NOT NULL DEFAULT '[]',
            client_slots_json TEXT NOT NULL DEFAULT '[]',
            include_trend_report INTEGER NOT NULL DEFAULT 0,
            shared_trend_report_id INTEGER,
            retry_max INTEGER NOT NULL DEFAULT 2,
            retry_wait_seconds INTEGER NOT NULL DEFAULT 120,
            cost_limit_usd REAL NOT NULL DEFAULT 25.0,
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS report_plan_runs (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER NOT NULL DEFAULT 1,
            run_key TEXT NOT NULL UNIQUE,
            planned_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            auto_execute INTEGER NOT NULL DEFAULT 0,
            period_year INTEGER,
            period_month INTEGER,
            shared_trend_report_id INTEGER,
            cost_spent_usd REAL NOT NULL DEFAULT 0,
            started_at TEXT,
            finished_at TEXT,
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(plan_id) REFERENCES report_plans(id)
        );

        CREATE TABLE IF NOT EXISTS report_plan_run_clients (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            client_name TEXT NOT NULL DEFAULT '',
            queue_position INTEGER NOT NULL DEFAULT 0,
            scheduled_at TEXT,
            fetch_status TEXT NOT NULL DEFAULT 'pending',
            fetch_detail TEXT NOT NULL DEFAULT '',
            report_id INTEGER,
            report_status TEXT NOT NULL DEFAULT '',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, client_id),
            FOREIGN KEY(run_id) REFERENCES report_plan_runs(id),
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );

        CREATE INDEX IF NOT EXISTS idx_report_plan_runs_key ON report_plan_runs(run_key);
        CREATE INDEX IF NOT EXISTS idx_report_plan_run_clients_run
            ON report_plan_run_clients(run_id, queue_position);
        """
    )
    plan_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(report_plans)").fetchall()}
    if "client_slots_json" not in plan_cols:
        conn.execute(
            "ALTER TABLE report_plans ADD COLUMN client_slots_json TEXT NOT NULL DEFAULT '[]'"
        )
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(client_reports)").fetchall()}
    if "origin" not in cols:
        conn.execute("ALTER TABLE client_reports ADD COLUMN origin TEXT NOT NULL DEFAULT ''")


def _parse_hhmm(value: str) -> time:
    raw = (value or DEFAULT_START_TIME).strip()
    try:
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except (TypeError, ValueError):
        return time(9, 0)


def last_sunday_of_month(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def next_planned_dates(*, from_day: date | None = None, count: int = 3) -> list[dict[str, Any]]:
    """Upcoming last-Sunday-of-month concepts (editable later)."""
    day = from_day or amsterdam_now().date()
    y, m = day.year, day.month
    out: list[dict[str, Any]] = []
    for _ in range(36):
        candidate = last_sunday_of_month(y, m)
        if candidate >= day:
            out.append(
                {
                    "date": candidate.isoformat(),
                    "label": candidate.strftime("%d-%m-%Y"),
                    "rule": "last_sunday_of_month",
                    "note": "Voorstel — definitieve datums later vastleggen.",
                }
            )
            if len(out) >= count:
                break
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def default_plan_payload() -> dict[str, Any]:
    now = amsterdam_now()
    return {
        "id": 1,
        "name": "Maandelijkse klantrapporten",
        "auto_execute": False,
        "timezone": "Europe/Amsterdam",
        "schedule_kind": "recurring",
        "once_date": None,
        "recurring_rule": "last_sunday_of_month",
        "start_time": DEFAULT_START_TIME,
        "interval_minutes": DEFAULT_INTERVAL_MINUTES,
        "period_mode": "previous_calendar_month",
        "period_year": None,
        "period_month": None,
        "client_ids": [],
        "client_slots": [],
        "include_trend_report": False,
        "shared_trend_report_id": None,
        "retry_max": DEFAULT_RETRY_MAX,
        "retry_wait_seconds": DEFAULT_RETRY_WAIT_SECONDS,
        "cost_limit_usd": DEFAULT_COST_LIMIT_USD,
        "updated_at": now.isoformat(),
        "created_at": now.isoformat(),
    }


def _normalize_slots(
    slots: list[Any] | None,
    *,
    client_ids: list[int] | None = None,
    start_time: str = DEFAULT_START_TIME,
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
) -> list[dict[str, Any]]:
    """One global slot per client: {client_id, time 'HH:MM'} in queue order."""
    cleaned: list[dict[str, Any]] = []
    seen: set[int] = set()
    if isinstance(slots, list):
        for raw in slots:
            if not isinstance(raw, dict):
                continue
            try:
                cid = int(raw.get("client_id"))
            except (TypeError, ValueError):
                continue
            if cid in seen:
                continue
            t = str(raw.get("time") or "").strip()
            try:
                parsed = _parse_hhmm(t)
                t = f"{parsed.hour:02d}:{parsed.minute:02d}"
            except Exception:
                t = start_time
            cleaned.append({"client_id": cid, "time": t})
            seen.add(cid)
    if cleaned:
        return cleaned
    # Fallback: build from client_ids + start + interval (1e klant start, daarna +pauze)
    ids = [int(x) for x in (client_ids or [])]
    base = datetime.combine(date.today(), _parse_hhmm(start_time))
    out = []
    for idx, cid in enumerate(ids):
        slot_dt = base + timedelta(minutes=int(interval_minutes) * idx)
        out.append({"client_id": cid, "time": slot_dt.strftime("%H:%M")})
    return out


def _row_to_plan(row: Any) -> dict[str, Any]:
    try:
        client_ids = json.loads(row["client_ids_json"] or "[]")
    except json.JSONDecodeError:
        client_ids = []
    client_ids = [int(x) for x in client_ids if str(x).isdigit() or isinstance(x, int)]
    try:
        keys = set(row.keys())
    except Exception:
        keys = set()
    raw_slots = []
    if "client_slots_json" in keys:
        try:
            raw_slots = json.loads(row["client_slots_json"] or "[]")
        except json.JSONDecodeError:
            raw_slots = []
    start_time = row["start_time"] or DEFAULT_START_TIME
    interval = int(row["interval_minutes"] or DEFAULT_INTERVAL_MINUTES)
    slots = _normalize_slots(
        raw_slots,
        client_ids=client_ids,
        start_time=start_time,
        interval_minutes=interval,
    )
    if slots and not client_ids:
        client_ids = [s["client_id"] for s in slots]
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "auto_execute": bool(row["auto_execute"]),
        "timezone": row["timezone"] or "Europe/Amsterdam",
        "schedule_kind": row["schedule_kind"],
        "once_date": row["once_date"],
        "recurring_rule": row["recurring_rule"],
        "start_time": start_time,
        "interval_minutes": interval,
        "period_mode": row["period_mode"],
        "period_year": row["period_year"],
        "period_month": row["period_month"],
        "client_ids": client_ids,
        "client_slots": slots,
        "include_trend_report": bool(row["include_trend_report"]),
        "shared_trend_report_id": row["shared_trend_report_id"],
        "retry_max": int(row["retry_max"] or DEFAULT_RETRY_MAX),
        "retry_wait_seconds": int(row["retry_wait_seconds"] or DEFAULT_RETRY_WAIT_SECONDS),
        "cost_limit_usd": float(row["cost_limit_usd"] or DEFAULT_COST_LIMIT_USD),
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
    }


def get_or_create_plan(conn) -> dict[str, Any]:
    ensure_tables(conn)
    row = conn.execute("SELECT * FROM report_plans WHERE id = 1").fetchone()
    if row is None:
        payload = default_plan_payload()
        conn.execute(
            """
            INSERT INTO report_plans (
                id, name, auto_execute, timezone, schedule_kind, once_date, recurring_rule,
                start_time, interval_minutes, period_mode, period_year, period_month,
                client_ids_json, include_trend_report, shared_trend_report_id,
                retry_max, retry_wait_seconds, cost_limit_usd, updated_at, created_at
            ) VALUES (1, ?, 0, ?, ?, NULL, ?, ?, ?, ?, NULL, NULL, '[]', 0, NULL, ?, ?, ?, ?, ?)
            """,
            (
                payload["name"],
                payload["timezone"],
                payload["schedule_kind"],
                payload["recurring_rule"],
                payload["start_time"],
                payload["interval_minutes"],
                payload["period_mode"],
                payload["retry_max"],
                payload["retry_wait_seconds"],
                payload["cost_limit_usd"],
                payload["updated_at"],
                payload["created_at"],
            ),
        )
        row = conn.execute("SELECT * FROM report_plans WHERE id = 1").fetchone()
    return _row_to_plan(row)


def update_plan(conn, body: dict[str, Any]) -> dict[str, Any]:
    plan = get_or_create_plan(conn)
    now = amsterdam_now().isoformat()

    def _bool(key: str, current: bool) -> bool:
        if key not in body:
            return current
        return bool(body[key])

    name = str(body.get("name") or plan["name"]).strip() or plan["name"]
    schedule_kind = str(body.get("schedule_kind") or plan["schedule_kind"]).strip()
    if schedule_kind not in {"once", "recurring"}:
        raise ValueError("schedule_kind must be once or recurring.")
    recurring_rule = str(body.get("recurring_rule") or plan["recurring_rule"]).strip()
    if recurring_rule not in {"last_sunday_of_month"}:
        raise ValueError("Alleen last_sunday_of_month is nu als concept beschikbaar.")
    start_time = str(body.get("start_time") or plan["start_time"]).strip()
    _parse_hhmm(start_time)  # validate
    interval = int(body.get("interval_minutes", plan["interval_minutes"]))
    if interval < 15 or interval > 240:
        raise ValueError("interval_minutes must be between 15 and 240.")
    period_mode = str(body.get("period_mode") or plan["period_mode"]).strip()
    if period_mode not in {"previous_calendar_month", "fixed_month"}:
        raise ValueError("period_mode must be previous_calendar_month or fixed_month.")
    raw_slots = body.get("client_slots")
    if raw_slots is None and "client_ids" in body:
        raw_slots = None  # rebuild from ids below
    cleaned_ids: list[int] = []
    if isinstance(raw_slots, list) and raw_slots:
        slots = _normalize_slots(
            raw_slots,
            start_time=start_time,
            interval_minutes=interval,
        )
        cleaned_ids = [s["client_id"] for s in slots]
    else:
        client_ids = body.get("client_ids", plan["client_ids"])
        if not isinstance(client_ids, list):
            raise ValueError("client_ids must be a list.")
        for raw in client_ids:
            try:
                cleaned_ids.append(int(raw))
            except (TypeError, ValueError) as exc:
                raise ValueError("client_ids must be integers.") from exc
        slots = _normalize_slots(
            body.get("client_slots") if isinstance(body.get("client_slots"), list) else plan.get("client_slots"),
            client_ids=cleaned_ids,
            start_time=start_time,
            interval_minutes=interval,
        )
        # If only ids changed, rebuild times from start+interval so "1 uur pauze" stays clear
        if "client_slots" not in body:
            slots = _normalize_slots(
                None,
                client_ids=cleaned_ids,
                start_time=start_time,
                interval_minutes=interval,
            )
        cleaned_ids = [s["client_id"] for s in slots]
    once_date = body.get("once_date", plan["once_date"])
    if once_date in ("", None):
        once_date = None
    elif once_date:
        date.fromisoformat(str(once_date))

    period_year = body.get("period_year", plan["period_year"])
    period_month = body.get("period_month", plan["period_month"])
    if period_mode == "fixed_month":
        if not period_year or not period_month:
            raise ValueError("fixed_month requires period_year and period_month.")
        period_year = int(period_year)
        period_month = int(period_month)
        if not (1 <= period_month <= 12):
            raise ValueError("Invalid period_month.")

    # Safety: never silently turn auto_execute on via partial payloads in QA.
    auto_execute = False
    if "auto_execute" in body and bool(body["auto_execute"]):
        raise ValueError(
            "Automatisch uitvoeren staat voorlopig uit. Zet auto_execute niet aan tot live planning is goedgekeurd."
        )

    retry_max = int(body.get("retry_max", plan["retry_max"]))
    retry_wait = int(body.get("retry_wait_seconds", plan["retry_wait_seconds"]))
    cost_limit = float(body.get("cost_limit_usd", plan["cost_limit_usd"]))
    if retry_max < 0 or retry_max > 5:
        raise ValueError("retry_max must be 0–5.")
    if retry_wait < 30 or retry_wait > 3600:
        raise ValueError("retry_wait_seconds must be 30–3600.")
    if cost_limit < 0 or cost_limit > 500:
        raise ValueError("cost_limit_usd must be 0–500.")

    include_trend = _bool("include_trend_report", plan["include_trend_report"])
    shared_trend = body.get("shared_trend_report_id", plan["shared_trend_report_id"])
    if shared_trend in ("", None):
        shared_trend = None
    elif shared_trend is not None:
        shared_trend = int(shared_trend)

    # Keep start_time aligned with first slot when slots are explicit
    if slots:
        start_time = slots[0]["time"]
    conn.execute(
        """
        UPDATE report_plans SET
            name = ?, auto_execute = ?, schedule_kind = ?, once_date = ?, recurring_rule = ?,
            start_time = ?, interval_minutes = ?, period_mode = ?, period_year = ?, period_month = ?,
            client_ids_json = ?, client_slots_json = ?, include_trend_report = ?, shared_trend_report_id = ?,
            retry_max = ?, retry_wait_seconds = ?, cost_limit_usd = ?, updated_at = ?
        WHERE id = 1
        """,
        (
            name,
            1 if auto_execute else 0,
            schedule_kind,
            once_date,
            recurring_rule,
            start_time,
            interval,
            period_mode,
            period_year,
            period_month,
            json.dumps(cleaned_ids),
            json.dumps(slots),
            1 if include_trend else 0,
            shared_trend,
            retry_max,
            retry_wait,
            cost_limit,
            now,
        ),
    )
    return get_or_create_plan(conn)


def resolve_report_period(plan: dict[str, Any], *, planned_day: date | None = None) -> tuple[int, int]:
    if plan["period_mode"] == "fixed_month" and plan.get("period_year") and plan.get("period_month"):
        return int(plan["period_year"]), int(plan["period_month"])
    day = planned_day or amsterdam_now().date()
    if day.month == 1:
        return day.year - 1, 12
    return day.year, day.month - 1


def planning_month_x2(analysis_year: int, analysis_month: int) -> tuple[int, int]:
    plan_m = int(analysis_month) + 2
    plan_y = int(analysis_year)
    while plan_m > 12:
        plan_m -= 12
        plan_y += 1
    return plan_y, plan_m


def resolve_shared_trend_report(
    conn,
    *,
    analysis_year: int,
    analysis_month: int,
    preferred_id: int | None = None,
) -> dict[str, Any]:
    """Pick one general trend report for the month (shared across clients).

    Preference order:
    1. preferred_id when it is a usable trend
    2. completed/mock trend whose planning_year/month matches analysis X+2
    3. completed/mock trend whose period_year/month matches the analysis month
    """
    plan_y, plan_m = planning_month_x2(analysis_year, analysis_month)

    def _row(report_id: int):
        return conn.execute(
            """
            SELECT id, client_id, title, status, period_year, period_month,
                   planning_year, planning_month
            FROM client_reports
            WHERE id = ? AND report_type = 'trend'
            """,
            (report_id,),
        ).fetchone()

    def _usable(row) -> bool:
        return row is not None and str(row["status"] or "") in {"completed", "mock_completed"}

    def _pack(row, *, reason: str) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "client_id": int(row["client_id"]),
            "title": row["title"],
            "status": row["status"],
            "period_year": row["period_year"],
            "period_month": row["period_month"],
            "planning_year": row["planning_year"],
            "planning_month": row["planning_month"],
            "match_reason": reason,
            "expected_planning": {"year": plan_y, "month": plan_m},
            "analysis_period": {"year": analysis_year, "month": analysis_month},
        }

    if preferred_id is not None:
        pref = _row(int(preferred_id))
        if _usable(pref):
            reason = "preferred_shared_trend_report_id"
            if pref["planning_year"] == plan_y and pref["planning_month"] == plan_m:
                reason = "preferred_matches_planning_x2"
            return _pack(pref, reason=reason)

    by_plan = conn.execute(
        """
        SELECT id, client_id, title, status, period_year, period_month,
               planning_year, planning_month
        FROM client_reports
        WHERE report_type = 'trend'
          AND status IN ('completed', 'mock_completed')
          AND planning_year = ? AND planning_month = ?
        ORDER BY CASE WHEN status = 'completed' THEN 0 ELSE 1 END, version DESC, id DESC
        LIMIT 1
        """,
        (plan_y, plan_m),
    ).fetchone()
    if by_plan:
        return _pack(by_plan, reason="matched_planning_x2")

    by_analysis = conn.execute(
        """
        SELECT id, client_id, title, status, period_year, period_month,
               planning_year, planning_month
        FROM client_reports
        WHERE report_type = 'trend'
          AND status IN ('completed', 'mock_completed')
          AND period_year = ? AND period_month = ?
        ORDER BY CASE WHEN status = 'completed' THEN 0 ELSE 1 END, version DESC, id DESC
        LIMIT 1
        """,
        (analysis_year, analysis_month),
    ).fetchone()
    if by_analysis:
        return _pack(by_analysis, reason="matched_analysis_period_fallback")

    return {
        "id": None,
        "match_reason": "none",
        "expected_planning": {"year": plan_y, "month": plan_m},
        "analysis_period": {"year": analysis_year, "month": analysis_month},
    }


def task_ai_providers() -> dict[str, Any]:
    """Which provider each report/analysis task uses (existing wiring)."""
    status = public_ai_status()
    gemini = status.get("gemini") or {}
    claude = status.get("claude") or {}
    return {
        "post_analysis": {
            "label": "Postfeedback",
            "primary": {
                "provider": "Anthropic Claude",
                "model": claude.get("model") or "",
                "configured": bool(claude.get("configured")),
            },
            "notes": (
                "Prepare/Execute in Logs / Media & insight gebruikt Claude "
                "(CLAUDE_API_KEY) met Maaikes bewerkbare post_analysis-prompt. "
                "Mock test de invoer zonder betaalde call."
            ),
            "optional": {
                "provider": "Google Gemini Developer API",
                "configured": bool(gemini.get("configured")),
                "model": gemini.get("model") or "",
                "used_for": "Rapporten / AI Trial — niet voor standaard postfeedback",
            },
        },
        "client_report": {
            "label": "Klantrapport",
            "primary": {
                "provider": "Google Gemini Developer API",
                "model": gemini.get("model") or "",
                "configured": bool(gemini.get("configured")),
            },
            "notes": "Native Gemini generateContent via bestaande report_execute-koppeling.",
        },
        "trend_report": {
            "label": "Trendrapport",
            "primary": {
                "provider": "Google Gemini Developer API",
                "model": gemini.get("model") or "",
                "configured": bool(gemini.get("configured")),
            },
            "notes": "Zelfde Gemini-koppeling; optioneel één gedeeld trendrapport voor klanten.",
        },
        "ai_status": status,
    }


def server_runtime_requirements() -> dict[str, Any]:
    """What is needed so planning can run when the laptop is off."""
    return {
        "summary": (
            "Planning draait alleen terwijl het Maaike-proces actief is "
            "(Render web service of altijd-aan host). Laptop uit = geen runs."
        ),
        "needed": [
            "Maaike web service 24/7 (bijv. Render) met ENABLE_REPORT_PLANNING_SCHEDULER=1",
            "MAAIKE_DATABASE_PATH op persistente disk (niet ephemere filesystem zonder disk)",
            "AI_API_KEY / AI_MODEL (en optioneel CLAUDE_API_KEY) als env vars op de server",
            "Meta tokens geldig voor post-/cijfer-sync vóór rapportvoorbereiding",
            "auto_execute pas aanzetten na akkoord — nu hard uit in code/API",
        ],
        "not_enough": [
            "Alleen lokaal `uvicorn` op een laptop die ’s nachts uit staat",
            "Scheduler zonder persistente SQLite (runs/idempotency weg bij wipe)",
        ],
        "env_flags": {
            "ENABLE_REPORT_PLANNING_SCHEDULER": os.getenv("ENABLE_REPORT_PLANNING_SCHEDULER", "0"),
            "auto_execute_forced_off": True,
        },
    }


def _client_name_map(conn) -> dict[int, str]:
    return {int(c.client_id): c.name for c in list_clients(conn)}


def _assess_fetch_status(conn, client_id: int, period_year: int, period_month: int) -> tuple[str, str]:
    """Classify local data readiness without calling Meta/AI."""
    from maaike.report_metrics import build_period_metrics

    try:
        bundle = build_period_metrics(
            conn,
            client_id,
            period_year=period_year,
            period_month=period_month,
            attach_enrichment=False,
        )
    except Exception as exc:  # noqa: BLE001 — surface as failed fetch for UI
        return "failed", f"Cijfers ophalen mislukt: {exc}"
    posts = bundle.get("posts") or []
    metrics = bundle.get("metrics") or {}
    count = int(metrics.get("post_count") or len(posts) or 0)
    client = conn.execute(
        "SELECT meta_status, last_fetch_status, last_fetch_at FROM clients WHERE id = ?",
        (client_id,),
    ).fetchone()
    meta_ok = (client["meta_status"] if client else "") == "connected"
    last_fetch = (client["last_fetch_status"] if client else "") or ""
    if count == 0:
        if not meta_ok:
            return "failed", "Geen posts in periode en Meta niet verbonden."
        return "partial", "Geen posts in analyseperiode (Meta wel verbonden)."
    if last_fetch and last_fetch not in {"ok", "completed", "success"}:
        return "partial", f"{count} posts lokaal; laatste Meta-sync: {last_fetch}."
    return "updated", f"{count} posts/cijfers beschikbaar voor {period_year}-{period_month:02d}."


def planning_overview(conn) -> dict[str, Any]:
    plan = get_or_create_plan(conn)
    names = _client_name_map(conn)
    selected_ids = {s["client_id"] for s in plan.get("client_slots") or []} or set(plan["client_ids"])
    clients = [
        {
            "id": cid,
            "name": names.get(cid, f"#{cid}"),
            "selected": cid in selected_ids,
        }
        for cid in sorted(names, key=lambda i: names.get(i, "").lower())
    ]
    schedule = []
    for slot in plan.get("client_slots") or []:
        cid = int(slot["client_id"])
        schedule.append(
            {
                "client_id": cid,
                "name": names.get(cid, f"#{cid}"),
                "time": slot["time"],
            }
        )
    from maaike.monthly_trend_scheduler import monthly_trend_schedule_status

    last_run = conn.execute(
        "SELECT * FROM report_plan_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    last_run_payload = None
    if last_run:
        last_run_payload = get_run(conn, int(last_run["id"]))
    return {
        "plan": plan,
        "clients": clients,
        "schedule": schedule,
        "scope": "global",
        "scope_note": (
            "Eén planning voor alle klanten. Wissel je links van klant, dan blijft dit schema hetzelfde."
        ),
        "suggested_dates": next_planned_dates(count=3),
        "task_ai_providers": task_ai_providers(),
        "server_runtime": server_runtime_requirements(),
        "last_run": last_run_payload,
        "scheduler": schedule_status(),
        "monthly_trend_schedule": monthly_trend_schedule_status(conn),
        "notes": [
            "Algemeen trendrapport: wordt op de 1e van iedere maand automatisch aangemaakt en bewaard (Europe/Amsterdam).",
            "Voorbeeld klantrapporten: Red Rock 12:00, Test1 13:00 = pauze van 1 uur tussen die twee.",
            "Automatisch betaalde AI uitvoeren voor klantrapporten staat uit totdat dit expliciet wordt vrijgegeven.",
        ],
    }


def get_run(conn, run_id: int) -> dict[str, Any]:
    ensure_tables(conn)
    row = conn.execute("SELECT * FROM report_plan_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("Planning-run niet gevonden.")
    clients = [
        dict(r)
        for r in conn.execute(
            """
            SELECT * FROM report_plan_run_clients
            WHERE run_id = ?
            ORDER BY queue_position, id
            """,
            (run_id,),
        ).fetchall()
    ]
    return {
        "id": int(row["id"]),
        "plan_id": int(row["plan_id"]),
        "run_key": row["run_key"],
        "planned_date": row["planned_date"],
        "status": row["status"],
        "auto_execute": bool(row["auto_execute"]),
        "period_year": row["period_year"],
        "period_month": row["period_month"],
        "shared_trend_report_id": row["shared_trend_report_id"],
        "cost_spent_usd": row["cost_spent_usd"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "detail": row["detail"],
        "clients": clients,
    }


def list_ready_concepts(conn, *, client_id: int | None = None, limit: int = 40) -> list[dict[str, Any]]:
    """Prepared / not-yet-approved concepts for Reports ‘Klaar om te bekijken’."""
    ensure_tables(conn)
    from maaike.reports import ensure_report_tables

    ensure_report_tables(conn)
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(client_reports)").fetchall()}
    origin_select = "COALESCE(r.origin, '') AS origin" if "origin" in cols else "'' AS origin"
    q = f"""
        SELECT r.id, r.client_id, c.name AS client_name, r.report_type, r.period_year, r.period_month,
               r.planning_year, r.planning_month, r.title, r.status, r.prepared_at, r.executed_at,
               r.updated_at, {origin_select}
        FROM client_reports r
        JOIN clients c ON c.id = r.client_id
        WHERE r.report_type = 'client'
          AND (
            r.status = 'prepared'
            OR (r.status IN ('completed', 'mock_completed') AND r.executed_at IS NOT NULL)
          )
    """
    params: list[Any] = []
    if client_id is not None:
        q += " AND r.client_id = ?"
        params.append(client_id)
    q += " ORDER BY COALESCE(r.updated_at, r.prepared_at, r.created_at) DESC, r.id DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    # Drop approved completed reports from “ready to review”
    from maaike.report_review import review_summary_for_list

    ready = []
    for row in rows:
        summary = review_summary_for_list(conn, int(row["client_id"]), row)
        if row["status"] in {"completed", "mock_completed"} and summary.get("is_approved"):
            continue
        row["from_plan"] = (row.get("origin") or "") == ORIGIN_PLAN
        row["is_approved"] = bool(summary.get("is_approved"))
        ready.append(row)
    # Prefer plan concepts first, then newest
    ready.sort(key=lambda r: (0 if r.get("from_plan") else 1, r.get("updated_at") or "", -int(r["id"])))
    return ready


def start_or_resume_run(
    conn,
    *,
    planned_date: str | None = None,
    prepare_concepts: bool = True,
    allow_meta_refresh: bool = False,
) -> dict[str, Any]:
    """Create/idempotent resume a plan run: assess data, optionally prepare concepts (no paid AI)."""
    plan = get_or_create_plan(conn)
    if plan["auto_execute"]:
        raise ValueError("auto_execute is on — blocked until live planning is approved.")

    day = date.fromisoformat(planned_date) if planned_date else amsterdam_now().date()
    period_year, period_month = resolve_report_period(plan, planned_day=day)
    run_key = f"plan-1:{day.isoformat()}:{period_year}-{period_month:02d}"

    preferred_trend = plan.get("shared_trend_report_id") if plan.get("include_trend_report") else None
    trend_match = (
        resolve_shared_trend_report(
            conn,
            analysis_year=period_year,
            analysis_month=period_month,
            preferred_id=int(preferred_trend) if preferred_trend else None,
        )
        if plan.get("include_trend_report")
        else {"id": None, "match_reason": "trend_disabled"}
    )
    resolved_trend_id = trend_match.get("id")

    existing = conn.execute(
        "SELECT id, status FROM report_plan_runs WHERE run_key = ?", (run_key,)
    ).fetchone()
    now = amsterdam_now().isoformat()
    if existing and existing["status"] in {"done", "running", "queuing", "fetching"}:
        # Idempotent: return existing run instead of duplicating reports
        return {
            "run": get_run(conn, int(existing["id"])),
            "deduped": True,
            "message": "Bestaande run hergebruikt — geen dubbele rapporten.",
            "trend_selection": trend_match,
        }

    if existing:
        run_id = int(existing["id"])
        conn.execute(
            """
            UPDATE report_plan_runs
            SET status = 'fetching', started_at = COALESCE(started_at, ?), updated_at = ?,
                detail = ?, shared_trend_report_id = ?
            WHERE id = ?
            """,
            (
                now,
                now,
                "Opnieuw gestart (eerdere run was niet af).",
                resolved_trend_id,
                run_id,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO report_plan_runs (
                plan_id, run_key, planned_date, status, auto_execute,
                period_year, period_month, shared_trend_report_id,
                cost_spent_usd, started_at, finished_at, detail, created_at, updated_at
            ) VALUES (1, ?, ?, 'fetching', 0, ?, ?, ?, 0, ?, NULL, ?, ?, ?)
            """,
            (
                run_key,
                day.isoformat(),
                period_year,
                period_month,
                resolved_trend_id,
                now,
                (
                    f"Data beoordelen (lokaal; Meta-refresh alleen indien later aangezet). "
                    f"Trendkeuze: {trend_match.get('match_reason')} "
                    f"→ #{resolved_trend_id or 'geen'}."
                ),
                now,
                now,
            ),
        )
        run_id = int(cur.lastrowid)

    names = _client_name_map(conn)
    slots = plan.get("client_slots") or _normalize_slots(
        None,
        client_ids=plan.get("client_ids") or list(names.keys()),
        start_time=plan["start_time"],
        interval_minutes=int(plan["interval_minutes"]),
    )

    # Optional Meta refresh stays off in QA unless explicitly allowed (still no AI).
    if allow_meta_refresh:
        logger.info("allow_meta_refresh requested but skipped in planning dry path")

    for idx, slot in enumerate(slots):
        client_id = int(slot["client_id"])
        if client_id not in names:
            continue
        slot_t = _parse_hhmm(slot.get("time") or plan["start_time"])
        scheduled_at = datetime.combine(day, slot_t, tzinfo=AMSTERDAM).isoformat()
        fetch_status, fetch_detail = _assess_fetch_status(conn, client_id, period_year, period_month)
        row = conn.execute(
            "SELECT id, report_id FROM report_plan_run_clients WHERE run_id = ? AND client_id = ?",
            (run_id, client_id),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO report_plan_run_clients (
                    run_id, client_id, client_name, queue_position, scheduled_at,
                    fetch_status, fetch_detail, report_id, report_status,
                    attempt_count, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, '', 0, '', ?)
                """,
                (
                    run_id,
                    client_id,
                    names[client_id],
                    idx,
                    scheduled_at,
                    fetch_status,
                    fetch_detail,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE report_plan_run_clients
                SET client_name = ?, queue_position = ?, scheduled_at = ?,
                    fetch_status = ?, fetch_detail = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    names[client_id],
                    idx,
                    scheduled_at,
                    fetch_status,
                    fetch_detail,
                    now,
                    int(row["id"]),
                ),
            )

    conn.execute(
        "UPDATE report_plan_runs SET status = 'queuing', updated_at = ?, detail = ? WHERE id = ?",
        (now, "Klantrapporten één voor één in de wachtrij (prepare only).", run_id),
    )

    if prepare_concepts:
        _prepare_concepts_for_run(conn, run_id, plan)

    conn.execute(
        """
        UPDATE report_plan_runs
        SET status = 'done', finished_at = ?, updated_at = ?, detail = ?
        WHERE id = ?
        """,
        (
            amsterdam_now().isoformat(),
            amsterdam_now().isoformat(),
            "Klaar: data-status + concepten (geen betaalde AI).",
            run_id,
        ),
    )
    return {
        "run": get_run(conn, run_id),
        "deduped": False,
        "message": "Run afgerond zonder betaalde AI.",
        "trend_selection": trend_match,
    }


def _prepare_concepts_for_run(conn, run_id: int, plan: dict[str, Any]) -> None:
    from maaike.reports import prepare_client_report

    run = conn.execute("SELECT * FROM report_plan_runs WHERE id = ?", (run_id,)).fetchone()
    period_year = int(run["period_year"])
    period_month = int(run["period_month"])
    trend_id = run["shared_trend_report_id"] if plan.get("include_trend_report") else None
    rows = conn.execute(
        """
        SELECT * FROM report_plan_run_clients
        WHERE run_id = ?
        ORDER BY queue_position, id
        """,
        (run_id,),
    ).fetchall()
    for row in rows:
        now = amsterdam_now().isoformat()
        if row["report_id"]:
            # Idempotent: keep existing concept
            continue
        attempts = 0
        last_error = ""
        while attempts <= int(plan["retry_max"]):
            attempts += 1
            try:
                # Still prepare a concept when fetch is partial/failed so Maaike can open it;
                # fetch_status on the run row remains the source of truth for data quality.
                result = prepare_client_report(
                    conn,
                    int(row["client_id"]),
                    period_year=period_year,
                    period_month=period_month,
                    linked_trend_report_id=int(trend_id) if trend_id else None,
                    allow_partial_without_trend=True,
                    title=f"{row['client_name']} – analyse {period_month:02d}-{period_year} (planning)",
                )
                report = result.get("report") if isinstance(result, dict) else None
                report_id = int((report or result)["id"])
                conn.execute(
                    "UPDATE client_reports SET origin = ? WHERE id = ?",
                    (ORIGIN_PLAN, report_id),
                )
                conn.execute(
                    """
                    UPDATE report_plan_run_clients
                    SET report_id = ?, report_status = 'prepared', attempt_count = ?,
                        last_error = '', updated_at = ?
                    WHERE id = ?
                    """,
                    (report_id, attempts, now, int(row["id"])),
                )
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                # Temporary failures: record and retry within limit (no sleep in request path)
                conn.execute(
                    """
                    UPDATE report_plan_run_clients
                    SET report_status = 'retry', attempt_count = ?, last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (attempts, last_error, now, int(row["id"])),
                )
        if last_error:
            conn.execute(
                """
                UPDATE report_plan_run_clients
                SET report_status = 'failed', last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (last_error, amsterdam_now().isoformat(), int(row["id"])),
            )


def schedule_status() -> dict[str, Any]:
    enabled_env = os.getenv("ENABLE_REPORT_PLANNING_SCHEDULER", "0").strip() in {"1", "true", "yes"}
    return {
        "process_started": _started,
        "env_enabled": enabled_env,
        "auto_execute_forced_off": True,
        "timezone": "Europe/Amsterdam",
        "tick": "hourly check for last_sunday_of_month + start_time (no-op while auto_execute off)",
        "last_tick": dict(_last_tick),
        "live_planning_active": False,
    }


def start_report_planning_scheduler() -> None:
    """Register hourly tick; does nothing useful while auto_execute is forced off."""
    global _scheduler, _started
    if os.getenv("ENABLE_REPORT_PLANNING_SCHEDULER", "0").strip() not in {"1", "true", "yes"}:
        _last_tick.update(
            {
                "at": amsterdam_now().isoformat(),
                "action": "disabled",
                "detail": "ENABLE_REPORT_PLANNING_SCHEDULER not set — scheduler not started.",
            }
        )
        return
    with _start_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning("APScheduler missing — report planning scheduler not started")
            return
        _scheduler = BackgroundScheduler(timezone=AMSTERDAM)
        _scheduler.add_job(
            _scheduler_tick,
            CronTrigger(minute=5, timezone=AMSTERDAM),
            id="report_planning_tick",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        _started = True
        _last_tick.update(
            {
                "at": amsterdam_now().isoformat(),
                "action": "started",
                "detail": "Scheduler started; auto_execute remains off so ticks are no-ops.",
            }
        )


def _scheduler_tick() -> None:
    if not _job_lock.acquire(blocking=False):
        return
    try:
        _last_tick.update(
            {
                "at": amsterdam_now().isoformat(),
                "action": "skip_auto_off",
                "detail": "Live planning not activated — tick ignored.",
            }
        )
    finally:
        _job_lock.release()
