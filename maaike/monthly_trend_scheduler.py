"""Automatic general trend report on the 1st of every month (Europe/Amsterdam).

Idempotent across restarts and retries: at most one automatic general trend report
is created per (year, month) and stored in the dashboard.
Supports simulation mode without any paid AI call.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from maaike.report_metrics import MONTHS_NL, SOCIAL_TREND_CHANNELS

logger = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
ORIGIN_MONTHLY_AUTO = "monthly_auto_1st"

_scheduler = None
_started = False
_start_lock = threading.Lock()
_run_lock = threading.Lock()
_last_event: dict[str, Any] = {
    "at": None,
    "action": "never",
    "detail": "Maandelijkse trendrapport-planning nog niet gestart.",
}


def amsterdam_now() -> datetime:
    return datetime.now(tz=AMSTERDAM)


def to_amsterdam(dt: datetime | str | None = None) -> datetime:
    if dt is None:
        return amsterdam_now()
    if isinstance(dt, str):
        raw = dt.strip()
        if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            d = date.fromisoformat(raw)
            return datetime(d.year, d.month, d.day, 6, 0, tzinfo=AMSTERDAM)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=AMSTERDAM)
        return parsed.astimezone(AMSTERDAM)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=AMSTERDAM)
    return dt.astimezone(AMSTERDAM)


def next_first_of_month_amsterdam(from_dt: datetime | None = None) -> dict[str, Any]:
    now_local = to_amsterdam(from_dt)
    if now_local.day == 1 and (now_local.hour < 6 or (now_local.hour == 6 and now_local.minute == 0)):
        target_y, target_m = now_local.year, now_local.month
    elif now_local.month == 12:
        target_y, target_m = now_local.year + 1, 1
    else:
        target_y, target_m = now_local.year, now_local.month + 1
    next_dt = datetime(target_y, target_m, 1, 6, 0, tzinfo=AMSTERDAM)
    return {
        "iso": next_dt.isoformat(),
        "date": next_dt.date().isoformat(),
        "label_nl": f"1 {MONTHS_NL[target_m]} {target_y} om 06:00 (Europe/Amsterdam)",
        "year": target_y,
        "month": target_m,
        "timezone": "Europe/Amsterdam",
    }


def ensure_monthly_trend_tables(conn) -> None:
    from maaike.reports import ensure_report_tables

    ensure_report_tables(conn)
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(client_reports)").fetchall()}
    if "origin" not in cols:
        conn.execute("ALTER TABLE client_reports ADD COLUMN origin TEXT NOT NULL DEFAULT ''")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS monthly_trend_schedule_runs (
            id INTEGER PRIMARY KEY,
            period_year INTEGER NOT NULL,
            period_month INTEGER NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'Europe/Amsterdam',
            scheduled_for TEXT NOT NULL,
            report_id INTEGER,
            mode TEXT NOT NULL DEFAULT 'simulation_no_paid_ai',
            paid_ai_called INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'completed',
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(period_year, period_month),
            FOREIGN KEY(report_id) REFERENCES client_reports(id)
        );
        CREATE INDEX IF NOT EXISTS idx_monthly_trend_runs_period
            ON monthly_trend_schedule_runs(period_year, period_month);
        """
    )


def _anchor_client_id(conn) -> int | None:
    row = conn.execute("SELECT id FROM clients ORDER BY id ASC LIMIT 1").fetchone()
    return int(row["id"]) if row else None


def _apply_simulated_channel_trend_body(conn, client_id: int, report_id: int, year: int, month: int) -> dict[str, Any]:
    """Populate a channel-focused general trend report without calling any paid AI API."""
    from maaike.ai_response_validate import validate_report_body
    from maaike.reports import PROMPT_VERSION, get_report

    now_iso = amsterdam_now().isoformat()
    month_nl = MONTHS_NL.get(month, str(month))
    test_label = "SIMULATIE ZONDER BETAALDE AI — automatisch algemeen trendrapport"
    channels_summary = {
        "instagram": (
            f"Instagram ({month_nl} {year}): korte Reels met duidelijke teksthook in de eerste 2 seconden "
            "en educatieve carrousels met saves-focus zorgen voor het meeste organische bereik."
        ),
        "facebook": (
            f"Facebook ({month_nl} {year}): herkenbare mensen in beeld, lokaal of praktisch nieuws en "
            "korte native video’s leveren meer reacties op dan losse linkposts."
        ),
        "linkedin": (
            f"LinkedIn ({month_nl} {year}): documentposts (PDF-slides), praktijkvoorbeelden en persoonlijke "
            "lessen vanuit medewerkers presteren sterker dan algemene bedrijfsupdates."
        ),
        "tiktok": (
            f"TikTok ({month_nl} {year}): zoekgericht short-form video-advies (‘hoe werkt…’, ‘3 tips’) en "
            "authentieke behind-the-scenes clips houden de kijktijd hoog."
        ),
        "overig": (
            f"YouTube Shorts & overige kanalen ({month_nl} {year}): hergebruik van sterke verticale "
            "videoformats met ondertiteling vergroot de vindbaarheid."
        ),
    }
    candidate = {
        "label": f"Algemeen trendrapport {month_nl} {year} (simulatie zonder betaalde AI-run)",
        "fully_researched": True,
        "partial": False,
        "channels": channels_summary,
        "sources_used": [
            {
                "title": "Meta & Instagram Creators – maandoverzicht (simulatie)",
                "url": "https://creators.instagram.com",
                "published_at": f"{year}-{month:02d}-01",
                "consulted_at": now_iso[:10],
                "source_kind": "monthly_simulation",
            },
            {
                "title": "LinkedIn & vakmedia kanaaltrends (simulatie)",
                "url": "https://business.linkedin.com",
                "published_at": f"{year}-{month:02d}-01",
                "consulted_at": now_iso[:10],
                "source_kind": "monthly_simulation",
            },
        ],
        "claims_with_citations": [
            {
                "claim": "Korte verticale video en swipebare carrousels blijven leidende formats voor bereik en saves.",
                "source_url": "https://creators.instagram.com",
            },
            {
                "claim": "Documentposts en praktijkcases geven op LinkedIn structureel hogere betrokkenheid.",
                "source_url": "https://business.linkedin.com",
            },
        ],
        "distinctions": {
            "facts": [
                f"Dit algemeen trendrapport voor {month_nl} {year} bundelt trends per socialmediakanaal los van klantdata."
            ],
            "trends": [
                "Instagram: saves en kijktijd wegen zwaar mee bij Reels en carrousels.",
                "Facebook: community-interactie en native beeld/video werken sterker dan uitgaande links.",
                "LinkedIn: vakinhoudelijke carrousels en menselijke afzenders zorgen voor duurzame zichtbaarheid.",
                "TikTok: social search groeit; duidelijke gesproken en geschreven zoektermen helpen discovery.",
            ],
            "suggestions": [
                "Kies per kanaal een eigen haakje in plaats van één identieke doorplaatsing.",
                "Test op Instagram en LinkedIn swipebare kennisformats naast korte video.",
            ],
        },
        "chapters": {
            "positionering": (
                f"Zelfstandig algemeen trendrapport voor {month_nl} {year} van Red Rock Agency. "
                "Dit rapport behandelt actuele ontwikkelingen per socialmediakanaal en staat los van "
                "individuele klantperioden of planningsmaanden."
            ),
            "managementsamenvatting": (
                f"In {month_nl} {year} draait organisch succes op social media om kanaaleigen formats: "
                "kort en visueel op Instagram en TikTok, gesprek en herkenning op Facebook, en inhoudelijke "
                "verdieping via slides en praktijkverhalen op LinkedIn. (Simulatie zonder betaalde AI-run.)"
            ),
            "belangrijkste_trends": (
                "1. Social search neemt verder toe: gebruikers zoeken rechtstreeks op Instagram, TikTok en LinkedIn.\n"
                "2. Bewaarbare content (checklists, stappenplannen, vergelijkingen) wint terrein ten opzichte van losse sfeerposts.\n"
                "3. Authentieke gezichten en concrete voorbeelden houden langer de aandacht vast dan gepolijste reclamebeelden."
            ),
            "platform_verschuivingen": (
                f"• Instagram: {channels_summary['instagram']}\n"
                f"• Facebook: {channels_summary['facebook']}\n"
                f"• LinkedIn: {channels_summary['linkedin']}\n"
                f"• TikTok: {channels_summary['tiktok']}\n"
                f"• Overige kanalen: {channels_summary['overig']}"
            ),
            "contentkansen": (
                "Zet per kanaal in op formats die passen bij het kijkgedrag: educatieve carrousels en "
                "korte Reels op Instagram, herkenbare menselijke updates op Facebook, vakinhoudelijke "
                "documentposts op LinkedIn en korte vraag-antwoordvideo’s op TikTok."
            ),
            "zoekclusters": (
                "Opvallende zoekrichtingen op social media: praktische keuzehulp (‘wat past bij…’), "
                "stappenplannen (‘in 3 stappen…’) en eerlijke achter-de-schermen uitleg."
            ),
            "conclusie": (
                f"Focus in {month_nl} {year} op duidelijke hooks per kanaal, bewaarbare formats en menselijke "
                "afzenders. Gebruik dit algemene trendrapport als kanaalcontext bij de klantrapporten van deze maand."
            ),
        },
    }

    validation = validate_report_body(
        "trend",
        candidate,
        raw_text=json.dumps(candidate, ensure_ascii=False),
        test_label=test_label,
    )
    body = {
        **(validation.normalized or candidate),
        "label": candidate["label"],
        "test_label": test_label,
        "simulation_without_paid_ai": True,
        "channels": channels_summary,
        "sources_used": candidate["sources_used"],
        "claims_with_citations": candidate["claims_with_citations"],
        "analysis_usable": True,
        "partial": False,
        "validation": {
            "ok": True,
            "usable": True,
            "test_label": test_label,
        },
    }
    usage = {
        "status": "mock_completed",
        "paid_ai_called": False,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "actual_cost_usd": 0.0,
        "cost_known": True,
        "notes": "Automatische maandplanning gesimuleerd zonder betaalde AI-run.",
    }
    row = conn.execute("SELECT notes_json FROM client_reports WHERE id = ?", (report_id,)).fetchone()
    notes = json.loads((row["notes_json"] if row else "[]") or "[]")
    notes.append(
        f"Automatisch opgeslagen voor {month_nl} {year} (Europe/Amsterdam) — simulatie zonder betaalde AI-run."
    )
    conn.execute(
        """
        UPDATE client_reports SET
            status = 'mock_completed',
            executed_at = ?,
            body_json = ?,
            usage_json = ?,
            is_mock = 1,
            error_text = '',
            notes_json = ?,
            origin = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            now_iso,
            json.dumps(body, ensure_ascii=False),
            json.dumps(usage, ensure_ascii=False),
            json.dumps(notes, ensure_ascii=False),
            ORIGIN_MONTHLY_AUTO,
            now_iso,
            report_id,
        ),
    )
    for src in candidate["sources_used"]:
        conn.execute(
            """
            INSERT INTO client_report_sources (
                report_id, title, url, published_at, consulted_at, excerpt, source_kind, created_at
            ) VALUES (?, ?, ?, ?, ?, 'Simulatiebron zonder betaalde AI-run.', ?, ?)
            """,
            (
                report_id,
                src["title"],
                src["url"],
                src["published_at"],
                src["consulted_at"],
                src["source_kind"],
                now_iso,
            ),
        )
    conn.execute(
        """
        UPDATE ai_usage_events SET
            finished_at = ?,
            status = 'mock_completed',
            cost_known = 1,
            actual_cost = 0,
            notes = ?
        WHERE client_id = ? AND prompt_version = ? AND status = 'prepared_not_executed'
          AND notes LIKE ?
        """,
        (
            now_iso,
            f"Monthly auto simulation report id={report_id}; paid_ai_called=False.",
            client_id,
            PROMPT_VERSION,
            f"%id={report_id}%",
        ),
    )
    return get_report(conn, client_id, report_id)


def ensure_monthly_trend_report(
    conn,
    *,
    now_amsterdam: datetime | str | None = None,
    year: int | None = None,
    month: int | None = None,
    simulate_without_paid_ai: bool = True,
    only_on_first_of_month: bool = False,
) -> dict[str, Any]:
    """Create at most one general trend report for the target month in Europe/Amsterdam.

    Idempotent: restarts, retries, or already-saved trend reports for the same
    (year, month) never create a duplicate report.
    """
    from maaike.reports import get_report, prepare_trend_report, suggested_trend_report_title

    with _run_lock:
        ensure_monthly_trend_tables(conn)
        local_dt = to_amsterdam(now_amsterdam)
        now_iso = local_dt.isoformat()

        if only_on_first_of_month and year is None and month is None and local_dt.day != 1:
            detail = (
                f"Overgeslagen op {local_dt.strftime('%Y-%m-%d %H:%M')} (Europe/Amsterdam): "
                "niet de 1e van de maand."
            )
            _last_event.update({"at": now_iso, "action": "skipped_not_first_of_month", "detail": detail})
            return {
                "created": False,
                "deduped": False,
                "skipped": True,
                "action": "skipped_not_first_of_month",
                "timezone": "Europe/Amsterdam",
                "evaluated_at": now_iso,
                "paid_ai_called": False,
                "detail": detail,
            }

        target_year = int(year if year is not None else local_dt.year)
        target_month = int(month if month is not None else local_dt.month)
        if not (1 <= target_month <= 12) or target_year < 2000:
            raise ValueError("Ongeldige maand voor het algemeen trendrapport.")
        scheduled_for = f"{target_year:04d}-{target_month:02d}-01"

        # 1. Check schedule ledger first
        ledger = conn.execute(
            "SELECT * FROM monthly_trend_schedule_runs WHERE period_year = ? AND period_month = ?",
            (target_year, target_month),
        ).fetchone()
        if ledger is not None and ledger["report_id"]:
            existing_rep = conn.execute(
                """
                SELECT id, client_id, status FROM client_reports
                WHERE id = ? AND report_type = 'trend' AND status != 'failed'
                """,
                (int(ledger["report_id"]),),
            ).fetchone()
            if existing_rep is not None:
                rep_id = int(existing_rep["id"])
                rep_cid = int(existing_rep["client_id"])
                if existing_rep["status"] == "prepared" and simulate_without_paid_ai:
                    _apply_simulated_channel_trend_body(conn, rep_cid, rep_id, target_year, target_month)
                conn.execute(
                    """
                    UPDATE monthly_trend_schedule_runs
                    SET attempt_count = attempt_count + 1, updated_at = ?,
                        detail = ?
                    WHERE id = ?
                    """,
                    (
                        now_iso,
                        f"Herstart/nieuwe poging opgevangen: bestaand rapport #{rep_id} behouden (geen duplicaat).",
                        int(ledger["id"]),
                    ),
                )
                payload = get_report(conn, rep_cid, rep_id)
                _last_event.update(
                    {
                        "at": now_iso,
                        "action": "deduped_existing",
                        "detail": f"Bestaand algemeen trendrapport #{rep_id} voor {MONTHS_NL[target_month]} {target_year} behouden.",
                    }
                )
                return {
                    "created": False,
                    "deduped": True,
                    "skipped": False,
                    "action": "deduped_existing",
                    "timezone": "Europe/Amsterdam",
                    "evaluated_at": now_iso,
                    "scheduled_for": scheduled_for,
                    "period_year": target_year,
                    "period_month": target_month,
                    "paid_ai_called": False,
                    "report_id": rep_id,
                    "title": payload["report"]["title"],
                    "report": payload["report"],
                }

        # 2. Check if any non-failed general trend report already exists for this (year, month)
        existing_any = conn.execute(
            """
            SELECT id, client_id, status
            FROM client_reports
            WHERE report_type = 'trend'
              AND period_year = ? AND period_month = ?
              AND status IN ('completed', 'mock_completed', 'prepared', 'running')
            ORDER BY CASE WHEN status IN ('completed', 'mock_completed') THEN 0 ELSE 1 END,
                     version DESC, id DESC
            LIMIT 1
            """,
            (target_year, target_month),
        ).fetchone()
        if existing_any is not None:
            rep_id = int(existing_any["id"])
            rep_cid = int(existing_any["client_id"])
            if existing_any["status"] == "prepared" and simulate_without_paid_ai:
                _apply_simulated_channel_trend_body(conn, rep_cid, rep_id, target_year, target_month)
            conn.execute(
                """
                INSERT INTO monthly_trend_schedule_runs (
                    period_year, period_month, timezone, scheduled_for, report_id,
                    mode, paid_ai_called, attempt_count, status, detail, created_at, updated_at
                ) VALUES (?, ?, 'Europe/Amsterdam', ?, ?, 'existing_reused', 0, 1, 'completed', ?, ?, ?)
                ON CONFLICT(period_year, period_month) DO UPDATE SET
                    report_id = excluded.report_id,
                    attempt_count = monthly_trend_schedule_runs.attempt_count + 1,
                    status = 'completed',
                    detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (
                    target_year,
                    target_month,
                    scheduled_for,
                    rep_id,
                    f"Bestaand algemeen trendrapport #{rep_id} gekoppeld; geen nieuw rapport aangemaakt.",
                    now_iso,
                    now_iso,
                ),
            )
            payload = get_report(conn, rep_cid, rep_id)
            _last_event.update(
                {
                    "at": now_iso,
                    "action": "deduped_existing",
                    "detail": f"Bestaand algemeen trendrapport #{rep_id} voor {MONTHS_NL[target_month]} {target_year} behouden.",
                }
            )
            return {
                "created": False,
                "deduped": True,
                "skipped": False,
                "action": "deduped_existing",
                "timezone": "Europe/Amsterdam",
                "evaluated_at": now_iso,
                "scheduled_for": scheduled_for,
                "period_year": target_year,
                "period_month": target_month,
                "paid_ai_called": False,
                "report_id": rep_id,
                "title": payload["report"]["title"],
                "report": payload["report"],
            }

        # 3. Create the single monthly general trend report
        anchor_cid = _anchor_client_id(conn)
        if anchor_cid is None:
            detail = "Nog geen klantprofiel in de database om het rapport aan op te hangen."
            _last_event.update({"at": now_iso, "action": "skipped_no_client", "detail": detail})
            return {
                "created": False,
                "deduped": False,
                "skipped": True,
                "action": "skipped_no_client",
                "timezone": "Europe/Amsterdam",
                "evaluated_at": now_iso,
                "paid_ai_called": False,
                "detail": detail,
            }

        title = suggested_trend_report_title(target_year, target_month)
        allow_paid = (
            not simulate_without_paid_ai
            and os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}
            and bool(os.getenv("AI_API_KEY", "").strip())
        )
        research_mode = "internet" if allow_paid else "manual"
        prepared = prepare_trend_report(
            conn,
            anchor_cid,
            run_year=target_year,
            run_month=target_month,
            sources=[],
            research_mode=research_mode,
            title=title,
        )
        rep_id = int(prepared["report"]["id"])
        conn.execute(
            "UPDATE client_reports SET origin = ? WHERE id = ?",
            (ORIGIN_MONTHLY_AUTO, rep_id),
        )

        paid_ai_called = False
        mode_label = "simulation_no_paid_ai"
        if allow_paid:
            from maaike.report_execute import execute_report

            try:
                executed = execute_report(
                    conn,
                    anchor_cid,
                    rep_id,
                    dry_run_paid=False,
                )
                paid_ai_called = True
                mode_label = "auto_paid_ai"
                final_payload = executed
            except Exception as exc:  # noqa: BLE001
                logger.warning("Monthly paid trend execution failed, keeping prepared report #%s: %s", rep_id, exc)
                mode_label = "prepared_fallback"
                final_payload = get_report(conn, anchor_cid, rep_id)
        else:
            final_payload = _apply_simulated_channel_trend_body(
                conn, anchor_cid, rep_id, target_year, target_month
            )

        detail = (
            f"Algemeen trendrapport #{rep_id} voor {MONTHS_NL[target_month]} {target_year} aangemaakt en bewaard "
            f"({'betaalde AI-run' if paid_ai_called else 'simulatie zonder betaalde AI-run'})."
        )
        conn.execute(
            """
            INSERT INTO monthly_trend_schedule_runs (
                period_year, period_month, timezone, scheduled_for, report_id,
                mode, paid_ai_called, attempt_count, status, detail, created_at, updated_at
            ) VALUES (?, ?, 'Europe/Amsterdam', ?, ?, ?, ?, 1, 'completed', ?, ?, ?)
            ON CONFLICT(period_year, period_month) DO UPDATE SET
                report_id = excluded.report_id,
                mode = excluded.mode,
                paid_ai_called = excluded.paid_ai_called,
                status = 'completed',
                detail = excluded.detail,
                updated_at = excluded.updated_at
            """,
            (
                target_year,
                target_month,
                scheduled_for,
                rep_id,
                mode_label,
                1 if paid_ai_called else 0,
                detail,
                now_iso,
                now_iso,
            ),
        )
        _last_event.update({"at": now_iso, "action": "created", "detail": detail})
        return {
            "created": True,
            "deduped": False,
            "skipped": False,
            "action": "created",
            "timezone": "Europe/Amsterdam",
            "evaluated_at": now_iso,
            "scheduled_for": scheduled_for,
            "period_year": target_year,
            "period_month": target_month,
            "paid_ai_called": paid_ai_called,
            "mode": mode_label,
            "report_id": rep_id,
            "title": final_payload["report"]["title"],
            "report": final_payload["report"],
            "channels": [dict(ch) for ch in SOCIAL_TREND_CHANNELS],
        }


def run_scheduled_first_of_month_tick(*, now_amsterdam: datetime | str | None = None) -> dict[str, Any]:
    """Entry point invoked by APScheduler on day 1 of each month in Europe/Amsterdam."""
    from maaike.db import transaction
    from maaike.persist_sync import push_if_enabled

    paid_enabled = os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}
    with transaction() as conn:
        result = ensure_monthly_trend_report(
            conn,
            now_amsterdam=now_amsterdam,
            simulate_without_paid_ai=not paid_enabled,
            only_on_first_of_month=True,
        )
        if result.get("created") or result.get("deduped"):
            try:
                push_if_enabled(conn, reason="monthly_trend_1st")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Persist push after monthly trend tick failed: %s", exc)
        return result


def monthly_trend_schedule_status(conn) -> dict[str, Any]:
    ensure_monthly_trend_tables(conn)
    runs = [
        dict(r)
        for r in conn.execute(
            """
            SELECT m.*, c.title AS report_title, c.status AS report_status
            FROM monthly_trend_schedule_runs m
            LEFT JOIN client_reports c ON c.id = m.report_id
            ORDER BY m.period_year DESC, m.period_month DESC
            LIMIT 12
            """
        ).fetchall()
    ]
    paid_enabled = os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}
    return {
        "enabled": True,
        "process_started": _started,
        "timezone": "Europe/Amsterdam",
        "rule": "1st_of_month",
        "rule_label_nl": "Elke 1e van de maand om 06:00 uur (Europe/Amsterdam)",
        "paid_ai_enabled": paid_enabled,
        "default_mode_label_nl": (
            "Live AI-uitvoering op de 1e van de maand"
            if paid_enabled
            else "Veilige simulatiemodus (geen betaalde AI-run tenzij live AI-uitvoering is vrijgegeven)"
        ),
        "next_run": next_first_of_month_amsterdam(),
        "last_event": dict(_last_event),
        "recent_runs": runs,
    }


def start_monthly_trend_scheduler() -> None:
    """Start automatic 1st-of-the-month scheduler in Europe/Amsterdam."""
    global _scheduler, _started
    if os.getenv("MAAIKE_DISABLE_SCHEDULERS", "0").strip().lower() in {"1", "true", "yes"}:
        _last_event.update(
            {
                "at": amsterdam_now().isoformat(),
                "action": "disabled_by_env",
                "detail": "MAAIKE_DISABLE_SCHEDULERS actief.",
            }
        )
        return
    with _start_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger

            sched = BackgroundScheduler(timezone=AMSTERDAM)
            # Primary run on the 1st of every month at 06:00 Europe/Amsterdam
            sched.add_job(
                run_scheduled_first_of_month_tick,
                CronTrigger(day=1, hour=6, minute=0, timezone=AMSTERDAM),
                id="monthly_general_trend_primary",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600 * 12,
            )
            # Safety catch-up check on day 1 if server booted after 06:00
            sched.add_job(
                run_scheduled_first_of_month_tick,
                CronTrigger(day=1, minute=10, timezone=AMSTERDAM),
                id="monthly_general_trend_catchup",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            sched.start()
            _scheduler = sched
            _started = True
            _last_event.update(
                {
                    "at": amsterdam_now().isoformat(),
                    "action": "started",
                    "detail": "Actief: elke 1e van de maand in Europe/Amsterdam.",
                }
            )
            # If the server starts up on the 1st of the month after 06:00, ensure right away (idempotent).
            now_ams = amsterdam_now()
            if now_ams.day == 1 and now_ams.hour >= 6:
                try:
                    run_scheduled_first_of_month_tick(now_amsterdam=now_ams)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Initial day-1 trend check failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not start monthly trend scheduler: %s", exc)
            _last_event.update(
                {
                    "at": amsterdam_now().isoformat(),
                    "action": "error",
                    "detail": f"Scheduler kon niet starten: {exc}",
                }
            )
