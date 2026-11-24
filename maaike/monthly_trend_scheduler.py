"""Automatic general trend report on the 1st of every month around 06:00 (Europe/Amsterdam).

Features:
- Scheduled for the 1st of every month at 06:00 Europe/Amsterdam (CET/CEST DST-aware).
- External wake-up trigger (e.g. GitHub Actions -> secured Render endpoint) wakes a
  sleeping Render Free instance and triggers evaluation.
- Catch-up ("inhaalrun") after the 1st: if the run on the 1st was missed (service asleep,
  network error, etc.), any trigger or startup check on day 2..31 catches it up once.
- Production active_from guard (default 2026-12-01, the next 1st of the month) prevents
  retroactive paid AI runs for earlier historical months on deployment.
- Atomic reservation + active lease prevents duplicate reports and duplicate AI calls
  across retries, restarts, and simultaneous triggers.
- Simulation mode never calls paid AI, and simulated trend reports are marked so they
  cannot be used as a source for real client reports.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from maaike.report_metrics import MONTHS_NL, SOCIAL_TREND_CHANNELS

logger = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
ORIGIN_MONTHLY_AUTO = "monthly_auto_1st"
SCHEDULED_HOUR_AMSTERDAM = 6
SCHEDULED_MINUTE_AMSTERDAM = 0
DEFAULT_PRODUCTION_ACTIVE_FROM = "2026-12-01"
LEASE_SECONDS = 900

_scheduler = None
_started = False
_start_lock = threading.Lock()
_claim_lock = threading.Lock()
_last_event: dict[str, Any] = {
    "at": None,
    "action": "never",
    "detail": "Maandelijkse trendrapport-planning nog niet gestart.",
}


def amsterdam_now() -> datetime:
    return datetime.now(tz=AMSTERDAM)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def to_amsterdam(dt: datetime | str | None = None) -> datetime:
    if dt is None:
        return amsterdam_now()
    if isinstance(dt, str):
        raw = dt.strip()
        if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            d = date.fromisoformat(raw)
            return datetime(
                d.year,
                d.month,
                d.day,
                SCHEDULED_HOUR_AMSTERDAM,
                SCHEDULED_MINUTE_AMSTERDAM,
                tzinfo=AMSTERDAM,
            )
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=AMSTERDAM)
        return parsed.astimezone(AMSTERDAM)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=AMSTERDAM)
    return dt.astimezone(AMSTERDAM)


def due_datetime_amsterdam(year: int, month: int) -> datetime:
    return datetime(
        int(year),
        int(month),
        1,
        SCHEDULED_HOUR_AMSTERDAM,
        SCHEDULED_MINUTE_AMSTERDAM,
        tzinfo=AMSTERDAM,
    )


def _parse_active_from_ym(raw: str | None) -> tuple[int, int]:
    val = (raw or DEFAULT_PRODUCTION_ACTIVE_FROM).strip()
    try:
        parts = val[:10].split("-")
        y = int(parts[0])
        m = int(parts[1])
        if 2000 <= y <= 2100 and 1 <= m <= 12:
            return (y, m)
    except Exception:  # noqa: BLE001
        pass
    return (2026, 12)


def next_first_of_month_amsterdam(
    from_dt: datetime | None = None,
    *,
    active_from: str | None = None,
) -> dict[str, Any]:
    now_local = to_amsterdam(from_dt)
    due_this_month = due_datetime_amsterdam(now_local.year, now_local.month)
    if now_local < due_this_month:
        target_y, target_m = now_local.year, now_local.month
    elif now_local.month == 12:
        target_y, target_m = now_local.year + 1, 1
    else:
        target_y, target_m = now_local.year, now_local.month + 1

    if active_from:
        af_y, af_m = _parse_active_from_ym(active_from)
        if (target_y, target_m) < (af_y, af_m):
            target_y, target_m = af_y, af_m

    next_dt = due_datetime_amsterdam(target_y, target_m)
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

    # Migrate legacy monthly_trend_schedule_runs if UNIQUE(period_year, period_month) lacked run_scope
    tbl_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'monthly_trend_schedule_runs'"
    ).fetchone()
    if tbl_row is not None:
        create_sql = str(tbl_row[0] or "")
        existing_cols = {
            str(r[1]) for r in conn.execute("PRAGMA table_info(monthly_trend_schedule_runs)").fetchall()
        }
        if "run_scope" not in existing_cols or "UNIQUE(period_year, period_month, run_scope)" not in create_sql:
            conn.executescript(
                """
                ALTER TABLE monthly_trend_schedule_runs RENAME TO _monthly_trend_schedule_runs_legacy;

                CREATE TABLE monthly_trend_schedule_runs (
                    id INTEGER PRIMARY KEY,
                    period_year INTEGER NOT NULL,
                    period_month INTEGER NOT NULL,
                    run_scope TEXT NOT NULL DEFAULT 'simulation',
                    timezone TEXT NOT NULL DEFAULT 'Europe/Amsterdam',
                    scheduled_for TEXT NOT NULL,
                    report_id INTEGER,
                    mode TEXT NOT NULL DEFAULT 'simulation_no_paid_ai',
                    paid_ai_called INTEGER NOT NULL DEFAULT 0,
                    caught_up INTEGER NOT NULL DEFAULT 0,
                    trigger_source TEXT NOT NULL DEFAULT '',
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'completed',
                    claim_token TEXT NOT NULL DEFAULT '',
                    claim_expires_at TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(period_year, period_month, run_scope),
                    FOREIGN KEY(report_id) REFERENCES client_reports(id)
                );
                """
            )
            legacy_cols = {
                str(r[1])
                for r in conn.execute("PRAGMA table_info(_monthly_trend_schedule_runs_legacy)").fetchall()
            }
            scope_expr = (
                "run_scope"
                if "run_scope" in legacy_cols
                else "CASE WHEN paid_ai_called = 1 THEN 'production' ELSE 'simulation' END"
            )
            caught_expr = "caught_up" if "caught_up" in legacy_cols else "0"
            src_expr = "trigger_source" if "trigger_source" in legacy_cols else "''"
            conn.execute(
                f"""
                INSERT OR IGNORE INTO monthly_trend_schedule_runs (
                    period_year, period_month, run_scope, timezone, scheduled_for, report_id,
                    mode, paid_ai_called, caught_up, trigger_source, attempt_count,
                    status, claim_token, claim_expires_at, detail, created_at, updated_at
                )
                SELECT
                    period_year, period_month, {scope_expr}, timezone, scheduled_for, report_id,
                    mode, paid_ai_called, {caught_expr}, {src_expr}, attempt_count,
                    status, '', '', detail, created_at, updated_at
                FROM _monthly_trend_schedule_runs_legacy
                """
            )
            conn.execute("DROP TABLE _monthly_trend_schedule_runs_legacy")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS monthly_trend_schedule_runs (
            id INTEGER PRIMARY KEY,
            period_year INTEGER NOT NULL,
            period_month INTEGER NOT NULL,
            run_scope TEXT NOT NULL DEFAULT 'simulation',
            timezone TEXT NOT NULL DEFAULT 'Europe/Amsterdam',
            scheduled_for TEXT NOT NULL,
            report_id INTEGER,
            mode TEXT NOT NULL DEFAULT 'simulation_no_paid_ai',
            paid_ai_called INTEGER NOT NULL DEFAULT 0,
            caught_up INTEGER NOT NULL DEFAULT 0,
            trigger_source TEXT NOT NULL DEFAULT '',
            attempt_count INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'completed',
            claim_token TEXT NOT NULL DEFAULT '',
            claim_expires_at TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(period_year, period_month, run_scope),
            FOREIGN KEY(report_id) REFERENCES client_reports(id)
        );
        CREATE INDEX IF NOT EXISTS idx_monthly_trend_runs_period
            ON monthly_trend_schedule_runs(period_year, period_month, run_scope);

        CREATE TABLE IF NOT EXISTS monthly_trend_planner_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            production_enabled INTEGER NOT NULL DEFAULT 1,
            catchup_enabled INTEGER NOT NULL DEFAULT 1,
            active_from TEXT NOT NULL DEFAULT '2026-12-01',
            last_external_trigger_at TEXT,
            last_external_trigger_mode TEXT,
            last_external_trigger_source TEXT,
            last_external_trigger_result TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )
    row = conn.execute("SELECT id FROM monthly_trend_planner_settings WHERE id = 1").fetchone()
    if row is None:
        env_af = (os.getenv("MAAIKE_MONTHLY_TREND_ACTIVE_FROM") or DEFAULT_PRODUCTION_ACTIVE_FROM).strip()
        conn.execute(
            """
            INSERT INTO monthly_trend_planner_settings (
                id, production_enabled, catchup_enabled, active_from, updated_at
            ) VALUES (1, 1, 1, ?, ?)
            """,
            (env_af, amsterdam_now().isoformat()),
        )


def get_monthly_trend_planner_settings(conn) -> dict[str, Any]:
    ensure_monthly_trend_tables(conn)
    row = conn.execute("SELECT * FROM monthly_trend_planner_settings WHERE id = 1").fetchone()
    env_af = (os.getenv("MAAIKE_MONTHLY_TREND_ACTIVE_FROM") or "").strip()
    active_from = env_af or (str(row["active_from"] or DEFAULT_PRODUCTION_ACTIVE_FROM) if row else DEFAULT_PRODUCTION_ACTIVE_FROM)
    return {
        "production_enabled": bool(row["production_enabled"]) if row else True,
        "catchup_enabled": bool(row["catchup_enabled"]) if row else True,
        "active_from": active_from,
        "last_external_trigger_at": row["last_external_trigger_at"] if row else None,
        "last_external_trigger_mode": row["last_external_trigger_mode"] if row else None,
        "last_external_trigger_source": row["last_external_trigger_source"] if row else None,
        "last_external_trigger_result": row["last_external_trigger_result"] if row else None,
        "updated_at": row["updated_at"] if row else None,
    }


def record_external_trigger_audit(
    conn,
    *,
    mode: str,
    trigger_source: str,
    action: str,
    at_iso: str | None = None,
) -> None:
    ensure_monthly_trend_tables(conn)
    ts = at_iso or amsterdam_now().isoformat()
    conn.execute(
        """
        UPDATE monthly_trend_planner_settings
        SET last_external_trigger_at = ?,
            last_external_trigger_mode = ?,
            last_external_trigger_source = ?,
            last_external_trigger_result = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (ts, mode, trigger_source, action, ts),
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
    test_label = "SIMULATIE ZONDER BETAALDE AI — automatisch algemeen trendrapport (niet voor klantrapporten)"
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
        "fully_researched": False,
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
                f"Dit gesimuleerde trendrapport voor {month_nl} {year} dient uitsluitend voor verificatie van de maandplanner (geen betaalde AI-run)."
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
                f"Gesimuleerd algemeen trendrapport voor {month_nl} {year} (verificatie zonder betaalde AI-run). "
                "Let op: gesimuleerde trendrapporten kunnen niet als bron voor echte klantrapporten dienen."
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
                f"Simulatieverificatie voor {month_nl} {year} geslaagd zonder betaalde AI-run."
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
        "usable_for_client_report": False,
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
    conn.execute("DELETE FROM client_report_sources WHERE report_id = ?", (report_id,))
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


def _find_matching_completed_trend(conn, *, year: int, month: int, run_scope: str):
    """Find an already-completed trend report that satisfies run_scope.

    - For 'production': ONLY a real, non-simulated completed trend report counts!
      A simulated report NEVER blocks or satisfies a production run.
    - For 'simulation': any completed or mock_completed trend report for (year, month) counts.
    """
    from maaike.reports import is_simulated_report_row

    rows = conn.execute(
        """
        SELECT *
        FROM client_reports
        WHERE report_type = 'trend'
          AND period_year = ? AND period_month = ?
          AND status IN ('completed', 'mock_completed')
        ORDER BY CASE WHEN status = 'completed' AND COALESCE(is_mock, 0) = 0 THEN 0 ELSE 1 END,
                 version DESC, id DESC
        """,
        (int(year), int(month)),
    ).fetchall()
    for r in rows:
        sim = is_simulated_report_row(r)
        if run_scope == "production":
            if r["status"] == "completed" and not sim:
                return r
        else:
            return r
    return None


def _evaluate_schedule_window(
    conn,
    *,
    local_dt: datetime,
    year: int | None,
    month: int | None,
    run_scope: str,
    only_on_first_of_month: bool,
    allow_catchup_after_first: bool,
    enforce_due_time: bool,
    enforce_active_from: bool,
) -> dict[str, Any]:
    settings = get_monthly_trend_planner_settings(conn)
    explicit_period = year is not None or month is not None
    target_year = int(year if year is not None else local_dt.year)
    target_month = int(month if month is not None else local_dt.month)
    if not (1 <= target_month <= 12) or target_year < 2000:
        raise ValueError("Ongeldige maand voor het algemeen trendrapport.")

    due_dt = due_datetime_amsterdam(target_year, target_month)
    now_iso = local_dt.isoformat()

    if not explicit_period:
        if run_scope == "production" and not settings["production_enabled"]:
            detail = "Productieplanning staat gepauzeerd in de planner-instellingen."
            return {
                "proceed": False,
                "response": {
                    "created": False,
                    "deduped": False,
                    "skipped": True,
                    "caught_up": False,
                    "action": "skipped_production_disabled",
                    "timezone": "Europe/Amsterdam",
                    "evaluated_at": now_iso,
                    "paid_ai_called": False,
                    "detail": detail,
                },
            }

        if enforce_active_from:
            af_y, af_m = _parse_active_from_ym(settings["active_from"])
            if (target_year, target_month) < (af_y, af_m):
                nxt = next_first_of_month_amsterdam(local_dt, active_from=settings["active_from"])
                detail = (
                    f"Overgeslagen op {local_dt.strftime('%Y-%m-%d %H:%M')} (Europe/Amsterdam): "
                    f"productieplanning staat actief vanaf {nxt['label_nl']} (geen terugwerkende betaalde AI-run)."
                )
                return {
                    "proceed": False,
                    "response": {
                        "created": False,
                        "deduped": False,
                        "skipped": True,
                        "caught_up": False,
                        "action": "skipped_before_active_from",
                        "timezone": "Europe/Amsterdam",
                        "evaluated_at": now_iso,
                        "active_from": settings["active_from"],
                        "next_run": nxt,
                        "paid_ai_called": False,
                        "detail": detail,
                    },
                }

        if only_on_first_of_month and local_dt.day != 1:
            detail = (
                f"Overgeslagen op {local_dt.strftime('%Y-%m-%d %H:%M')} (Europe/Amsterdam): "
                "niet de 1e van de maand."
            )
            return {
                "proceed": False,
                "response": {
                    "created": False,
                    "deduped": False,
                    "skipped": True,
                    "caught_up": False,
                    "action": "skipped_not_first_of_month",
                    "timezone": "Europe/Amsterdam",
                    "evaluated_at": now_iso,
                    "paid_ai_called": False,
                    "detail": detail,
                },
            }

        if local_dt.day > 1 and not allow_catchup_after_first:
            detail = (
                f"Overgeslagen op {local_dt.strftime('%Y-%m-%d %H:%M')} (Europe/Amsterdam): "
                "inhalen na de 1e staat uit."
            )
            return {
                "proceed": False,
                "response": {
                    "created": False,
                    "deduped": False,
                    "skipped": True,
                    "caught_up": False,
                    "action": "skipped_catchup_disabled",
                    "timezone": "Europe/Amsterdam",
                    "evaluated_at": now_iso,
                    "paid_ai_called": False,
                    "detail": detail,
                },
            }

        if enforce_due_time and local_dt < due_dt:
            detail = (
                f"Nog niet aan de beurt op {local_dt.strftime('%Y-%m-%d %H:%M')} (Europe/Amsterdam): "
                f"gepland vanaf {due_dt.strftime('%Y-%m-%d %H:%M')} Nederlandse tijd."
            )
            return {
                "proceed": False,
                "response": {
                    "created": False,
                    "deduped": False,
                    "skipped": True,
                    "caught_up": False,
                    "action": "skipped_before_0600_amsterdam",
                    "timezone": "Europe/Amsterdam",
                    "evaluated_at": now_iso,
                    "scheduled_due_at": due_dt.isoformat(),
                    "paid_ai_called": False,
                    "detail": detail,
                },
            }

    caught_up = (not explicit_period) and (local_dt.day > 1)
    return {
        "proceed": True,
        "target_year": target_year,
        "target_month": target_month,
        "scheduled_for": f"{target_year:04d}-{target_month:02d}-01",
        "due_dt": due_dt,
        "caught_up": caught_up,
    }


def _claim_or_dedupe_in_conn(
    conn,
    *,
    target_year: int,
    target_month: int,
    scheduled_for: str,
    run_scope: str,
    caught_up: bool,
    trigger_source: str,
    now_iso: str,
    allow_paid: bool,
) -> dict[str, Any]:
    """Inspect ledger & existing reports, returning either an immediate deduped result or an active claim."""
    from maaike.reports import get_report, is_simulated_report_row, prepare_trend_report, suggested_trend_report_title

    now_utc = _utc_now()
    ledger = conn.execute(
        """
        SELECT * FROM monthly_trend_schedule_runs
        WHERE period_year = ? AND period_month = ? AND run_scope = ?
        """,
        (target_year, target_month, run_scope),
    ).fetchone()

    # 1. Active in-progress lease -> block concurrent trigger immediately (0 duplicate report, 0 duplicate AI call)
    if ledger is not None and ledger["status"] == "in_progress" and ledger["claim_expires_at"]:
        try:
            exp = datetime.fromisoformat(str(ledger["claim_expires_at"]).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            exp = now_utc - timedelta(seconds=1)
        if exp > now_utc:
            conn.execute(
                """
                UPDATE monthly_trend_schedule_runs
                SET attempt_count = attempt_count + 1,
                    updated_at = ?,
                    detail = ?
                WHERE id = ?
                """,
                (
                    now_iso,
                    f"Gelijktijdige trigger opgevangen terwijl run al bezig is (rapport #{ledger['report_id']}); geen dubbele AI-aanroep.",
                    int(ledger["id"]),
                ),
            )
            detail = (
                f"Run voor {MONTHS_NL[target_month]} {target_year} ({run_scope}) is al bezig "
                f"(rapport #{ledger['report_id']}); gelijktijdige aanvraag genegeerd."
            )
            _last_event.update({"at": now_iso, "action": "already_in_progress", "detail": detail})
            return {
                "kind": "immediate",
                "result": {
                    "created": False,
                    "deduped": True,
                    "in_progress": True,
                    "skipped": False,
                    "caught_up": False,
                    "action": "already_in_progress",
                    "run_scope": run_scope,
                    "timezone": "Europe/Amsterdam",
                    "evaluated_at": now_iso,
                    "scheduled_for": scheduled_for,
                    "period_year": target_year,
                    "period_month": target_month,
                    "paid_ai_called": False,
                    "report_id": int(ledger["report_id"]) if ledger["report_id"] else None,
                    "detail": detail,
                },
            }

    # 2. Check ledger's existing completed report
    if ledger is not None and ledger["report_id"]:
        existing_rep = conn.execute(
            "SELECT * FROM client_reports WHERE id = ? AND report_type = 'trend' AND status != 'failed'",
            (int(ledger["report_id"]),),
        ).fetchone()
        if existing_rep is not None:
            rep_id = int(existing_rep["id"])
            rep_cid = int(existing_rep["client_id"])
            sim = is_simulated_report_row(existing_rep)
            usable_done = (
                (existing_rep["status"] == "completed" and not sim)
                if run_scope == "production"
                else (existing_rep["status"] in {"completed", "mock_completed"})
            )
            if usable_done:
                conn.execute(
                    """
                    UPDATE monthly_trend_schedule_runs
                    SET attempt_count = attempt_count + 1,
                        status = 'completed',
                        claim_token = '',
                        claim_expires_at = '',
                        updated_at = ?,
                        detail = ?
                    WHERE id = ?
                    """,
                    (
                        now_iso,
                        f"Herstart/retry opgevangen: bestaand rapport #{rep_id} behouden (geen duplicaat).",
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
                    "kind": "immediate",
                    "result": {
                        "created": False,
                        "deduped": True,
                        "in_progress": False,
                        "skipped": False,
                        "caught_up": False,
                        "action": "deduped_existing",
                        "run_scope": run_scope,
                        "timezone": "Europe/Amsterdam",
                        "evaluated_at": now_iso,
                        "scheduled_for": scheduled_for,
                        "period_year": target_year,
                        "period_month": target_month,
                        "paid_ai_called": False,
                        "report_id": rep_id,
                        "title": payload["report"]["title"],
                        "report": payload["report"],
                    },
                }

    # 3. Check if a matching completed trend report already exists in client_reports (e.g. manually created)
    existing_completed = _find_matching_completed_trend(
        conn, year=target_year, month=target_month, run_scope=run_scope
    )
    if existing_completed is not None:
        rep_id = int(existing_completed["id"])
        rep_cid = int(existing_completed["client_id"])
        conn.execute(
            """
            INSERT INTO monthly_trend_schedule_runs (
                period_year, period_month, run_scope, timezone, scheduled_for, report_id,
                mode, paid_ai_called, caught_up, trigger_source, attempt_count,
                status, claim_token, claim_expires_at, detail, created_at, updated_at
            ) VALUES (?, ?, ?, 'Europe/Amsterdam', ?, ?, 'existing_reused', 0, 0, ?, 1, 'completed', '', '', ?, ?, ?)
            ON CONFLICT(period_year, period_month, run_scope) DO UPDATE SET
                report_id = excluded.report_id,
                attempt_count = monthly_trend_schedule_runs.attempt_count + 1,
                status = 'completed',
                claim_token = '',
                claim_expires_at = '',
                detail = excluded.detail,
                updated_at = excluded.updated_at
            """,
            (
                target_year,
                target_month,
                run_scope,
                scheduled_for,
                rep_id,
                trigger_source,
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
            "kind": "immediate",
            "result": {
                "created": False,
                "deduped": True,
                "in_progress": False,
                "skipped": False,
                "caught_up": False,
                "action": "deduped_existing",
                "run_scope": run_scope,
                "timezone": "Europe/Amsterdam",
                "evaluated_at": now_iso,
                "scheduled_for": scheduled_for,
                "period_year": target_year,
                "period_month": target_month,
                "paid_ai_called": False,
                "report_id": rep_id,
                "title": payload["report"]["title"],
                "report": payload["report"],
            },
        }

    # 4. Anchor client check
    anchor_cid = _anchor_client_id(conn)
    if anchor_cid is None:
        detail = "Nog geen klantprofiel in de database om het rapport aan op te hangen."
        _last_event.update({"at": now_iso, "action": "skipped_no_client", "detail": detail})
        return {
            "kind": "immediate",
            "result": {
                "created": False,
                "deduped": False,
                "skipped": True,
                "caught_up": False,
                "action": "skipped_no_client",
                "run_scope": run_scope,
                "timezone": "Europe/Amsterdam",
                "evaluated_at": now_iso,
                "paid_ai_called": False,
                "detail": detail,
            },
        }

    # 5. Reuse an interrupted/prepared report row if present so retries/restarts NEVER create a 2nd report row
    reused_rep_id: int | None = None
    reused_cid = anchor_cid
    if ledger is not None and ledger["report_id"]:
        prep_row = conn.execute(
            """
            SELECT id, client_id, status FROM client_reports
            WHERE id = ? AND report_type = 'trend' AND status = 'prepared'
            """,
            (int(ledger["report_id"]),),
        ).fetchone()
        if prep_row is not None:
            reused_rep_id = int(prep_row["id"])
            reused_cid = int(prep_row["client_id"])

    if reused_rep_id is None:
        # Also check if a prepared monthly_auto_1st row already exists for this period
        orphan_prep = conn.execute(
            """
            SELECT id, client_id FROM client_reports
            WHERE report_type = 'trend'
              AND period_year = ? AND period_month = ?
              AND status = 'prepared'
              AND origin = ?
            ORDER BY id DESC LIMIT 1
            """,
            (target_year, target_month, ORIGIN_MONTHLY_AUTO),
        ).fetchone()
        if orphan_prep is not None:
            reused_rep_id = int(orphan_prep["id"])
            reused_cid = int(orphan_prep["client_id"])

    if reused_rep_id is not None:
        rep_id = reused_rep_id
        anchor_cid = reused_cid
    else:
        title = suggested_trend_report_title(target_year, target_month)
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

    claim_token = uuid.uuid4().hex
    claim_expires_at = (now_utc + timedelta(seconds=LEASE_SECONDS)).isoformat()
    conn.execute(
        """
        INSERT INTO monthly_trend_schedule_runs (
            period_year, period_month, run_scope, timezone, scheduled_for, report_id,
            mode, paid_ai_called, caught_up, trigger_source, attempt_count,
            status, claim_token, claim_expires_at, detail, created_at, updated_at
        ) VALUES (?, ?, ?, 'Europe/Amsterdam', ?, ?, 'claiming', 0, ?, ?, 1, 'in_progress', ?, ?, ?, ?, ?)
        ON CONFLICT(period_year, period_month, run_scope) DO UPDATE SET
            report_id = excluded.report_id,
            caught_up = excluded.caught_up,
            trigger_source = excluded.trigger_source,
            attempt_count = monthly_trend_schedule_runs.attempt_count + 1,
            status = 'in_progress',
            claim_token = excluded.claim_token,
            claim_expires_at = excluded.claim_expires_at,
            detail = excluded.detail,
            updated_at = excluded.updated_at
        """,
        (
            target_year,
            target_month,
            run_scope,
            scheduled_for,
            rep_id,
            1 if caught_up else 0,
            trigger_source,
            claim_token,
            claim_expires_at,
            f"Run geclaimd voor rapport #{rep_id} ({run_scope}).",
            now_iso,
            now_iso,
        ),
    )

    return {
        "kind": "claimed",
        "anchor_cid": anchor_cid,
        "rep_id": rep_id,
        "claim_token": claim_token,
        "target_year": target_year,
        "target_month": target_month,
        "scheduled_for": scheduled_for,
        "caught_up": caught_up,
    }


def _execute_and_finalize_in_conn(
    conn,
    *,
    claim: dict[str, Any],
    run_scope: str,
    allow_paid: bool,
    trigger_source: str,
    now_iso: str,
    exec_hook: Callable[[Any, int, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from maaike.reports import get_report

    anchor_cid = int(claim["anchor_cid"])
    rep_id = int(claim["rep_id"])
    target_year = int(claim["target_year"])
    target_month = int(claim["target_month"])
    scheduled_for = str(claim["scheduled_for"])
    caught_up = bool(claim["caught_up"])

    paid_ai_called = False
    final_status = "completed"
    if exec_hook is not None:
        final_payload = exec_hook(conn, anchor_cid, rep_id)
        paid_ai_called = bool(allow_paid)
        mode_label = "auto_paid_ai" if paid_ai_called else "simulation_no_paid_ai"
    elif allow_paid:
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
            logger.warning("Monthly paid trend execution failed, keeping prepared report #%s for retry: %s", rep_id, exc)
            mode_label = "prepared_retry_needed"
            final_status = "retry_needed"
            # Reset report status back to 'prepared' if execute_report left it failed/running so catch-up can retry cleanly
            conn.execute(
                "UPDATE client_reports SET status = 'prepared', updated_at = ? WHERE id = ? AND status != 'completed'",
                (now_iso, rep_id),
            )
            final_payload = get_report(conn, anchor_cid, rep_id)
    elif run_scope == "simulation":
        mode_label = "simulation_no_paid_ai"
        final_payload = _apply_simulated_channel_trend_body(
            conn, anchor_cid, rep_id, target_year, target_month
        )
    else:
        # Production wake-up without paid AI enabled: keep a prepared report (never mark as mock!).
        mode_label = "prepared_awaiting_paid_ai"
        final_status = "prepared"
        final_payload = get_report(conn, anchor_cid, rep_id)

    action = (
        "retry_scheduled"
        if final_status == "retry_needed"
        else (
            "prepared_awaiting_paid_ai"
            if final_status == "prepared"
            else ("caught_up_after_1st" if caught_up else "created")
        )
    )
    prefix = (
        f"Gemiste 1e-van-de-maand run ingehaald: algemeen trendrapport #{rep_id}"
        if caught_up and final_status == "completed"
        else f"Algemeen trendrapport #{rep_id}"
    )
    if final_status == "prepared":
        detail = (
            f"{prefix} voor {MONTHS_NL[target_month]} {target_year} klaargezet als concept. "
            "Betaalde AI-uitvoering staat nog niet aan (ENABLE_MONTHLY_TREND_PAID_AI); geen simulatie gemarkeerd als productiebron."
        )
    else:
        detail = (
            f"{prefix} voor {MONTHS_NL[target_month]} {target_year} "
            f"{'klaargezet voor automatische retry' if final_status == 'retry_needed' else 'aangemaakt en bewaard'} "
            f"({'betaalde AI-run' if paid_ai_called else 'simulatie zonder betaalde AI-run'})."
        )

    conn.execute(
        """
        UPDATE monthly_trend_schedule_runs
        SET mode = ?,
            paid_ai_called = ?,
            caught_up = ?,
            trigger_source = ?,
            status = ?,
            claim_token = '',
            claim_expires_at = '',
            detail = ?,
            updated_at = ?
        WHERE period_year = ? AND period_month = ? AND run_scope = ?
        """,
        (
            mode_label,
            1 if paid_ai_called else 0,
            1 if caught_up else 0,
            trigger_source,
            final_status,
            detail,
            now_iso,
            target_year,
            target_month,
            run_scope,
        ),
    )
    _last_event.update({"at": now_iso, "action": action, "detail": detail})
    return {
        "created": final_status == "completed",
        "deduped": False,
        "in_progress": False,
        "skipped": False,
        "caught_up": caught_up and final_status in {"completed", "prepared"},
        "action": action,
        "run_scope": run_scope,
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
        "detail": detail,
    }


def ensure_monthly_trend_report(
    conn,
    *,
    now_amsterdam: datetime | str | None = None,
    year: int | None = None,
    month: int | None = None,
    simulate_without_paid_ai: bool = True,
    only_on_first_of_month: bool = False,
    allow_catchup_after_first: bool = True,
    enforce_due_time: bool = False,
    enforce_active_from: bool = False,
    trigger_source: str = "internal",
) -> dict[str, Any]:
    """Single-connection idempotent monthly trend report ensure (used by unit tests & UI simulate)."""
    with _claim_lock:
        ensure_monthly_trend_tables(conn)
        local_dt = to_amsterdam(now_amsterdam)
        now_iso = local_dt.isoformat()
        settings = get_monthly_trend_planner_settings(conn)
        allow_paid = (
            not simulate_without_paid_ai
            and settings["production_enabled"]
            and os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}
            and bool(os.getenv("AI_API_KEY", "").strip())
        )
        run_scope = "production" if not simulate_without_paid_ai else "simulation"

        win = _evaluate_schedule_window(
            conn,
            local_dt=local_dt,
            year=year,
            month=month,
            run_scope=run_scope,
            only_on_first_of_month=only_on_first_of_month,
            allow_catchup_after_first=allow_catchup_after_first and settings["catchup_enabled"],
            enforce_due_time=enforce_due_time,
            enforce_active_from=enforce_active_from,
        )
        if not win["proceed"]:
            resp = win["response"]
            _last_event.update({"at": now_iso, "action": resp["action"], "detail": resp["detail"]})
            return resp

        decision = _claim_or_dedupe_in_conn(
            conn,
            target_year=win["target_year"],
            target_month=win["target_month"],
            scheduled_for=win["scheduled_for"],
            run_scope=run_scope,
            caught_up=win["caught_up"],
            trigger_source=trigger_source,
            now_iso=now_iso,
            allow_paid=allow_paid,
        )
        if decision["kind"] == "immediate":
            return decision["result"]

        return _execute_and_finalize_in_conn(
            conn,
            claim=decision,
            run_scope=run_scope,
            allow_paid=allow_paid,
            trigger_source=trigger_source,
            now_iso=now_iso,
        )


def run_monthly_trend_trigger(
    *,
    mode: str = "production",
    now_amsterdam: datetime | str | None = None,
    year: int | None = None,
    month: int | None = None,
    trigger_source: str = "external_trigger",
    record_external_audit: bool = False,
    _exec_hook: Callable[[Any, int, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Multi-request/concurrency-safe trigger used by GitHub Actions endpoint, startup catch-up, and APScheduler.

    Commits an atomic 'in_progress' lease in Phase 1 before running Phase 2 so simultaneous
    HTTP triggers or scheduler ticks NEVER create duplicate reports or duplicate AI calls.
    """
    from maaike.db import connect, transaction
    from maaike.persist_remote import push_if_changed

    clean_mode = (mode or "production").strip().lower()
    if clean_mode not in {"production", "simulation"}:
        raise ValueError("Ongeldige modus: kies 'production' of 'simulation'.")

    simulate = clean_mode == "simulation"
    # Security guard: production ALWAYS uses real Europe/Amsterdam clock and ignores synthetic overrides!
    effective_now = now_amsterdam if simulate else None
    effective_year = year if simulate else None
    effective_month = month if simulate else None
    local_dt = to_amsterdam(effective_now)
    now_iso = local_dt.isoformat()
    run_scope = "simulation" if simulate else "production"
    explicit_period = effective_year is not None or effective_month is not None

    # Phase 1: short atomic claim under process lock + BEGIN IMMEDIATE
    with _claim_lock:
        conn1 = connect()
        try:
            conn1.execute("BEGIN IMMEDIATE")
            ensure_monthly_trend_tables(conn1)
            settings = get_monthly_trend_planner_settings(conn1)
            allow_paid = (
                not simulate
                and settings["production_enabled"]
                and os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}
                and bool(os.getenv("AI_API_KEY", "").strip())
            )
            win = _evaluate_schedule_window(
                conn1,
                local_dt=local_dt,
                year=effective_year,
                month=effective_month,
                run_scope=run_scope,
                only_on_first_of_month=False,
                allow_catchup_after_first=bool(settings["catchup_enabled"]),
                enforce_due_time=not explicit_period,
                enforce_active_from=not simulate,
            )
            if not win["proceed"]:
                resp = win["response"]
                _last_event.update({"at": now_iso, "action": resp["action"], "detail": resp["detail"]})
                if record_external_audit:
                    record_external_trigger_audit(
                        conn1,
                        mode=clean_mode,
                        trigger_source=trigger_source,
                        action=resp["action"],
                        at_iso=now_iso,
                    )
                conn1.commit()
                return resp

            decision = _claim_or_dedupe_in_conn(
                conn1,
                target_year=win["target_year"],
                target_month=win["target_month"],
                scheduled_for=win["scheduled_for"],
                run_scope=run_scope,
                caught_up=win["caught_up"],
                trigger_source=trigger_source,
                now_iso=now_iso,
                allow_paid=allow_paid,
            )
            if decision["kind"] == "immediate":
                imm = decision["result"]
                if record_external_audit:
                    record_external_trigger_audit(
                        conn1,
                        mode=clean_mode,
                        trigger_source=trigger_source,
                        action=imm["action"],
                        at_iso=now_iso,
                    )
                conn1.commit()
                return imm

            conn1.commit()
        except Exception:
            conn1.rollback()
            raise
        finally:
            conn1.close()

    # Phase 2 & 3: execute claim outside _claim_lock (concurrent callers see status='in_progress' in SQLite!)
    try:
        with transaction() as conn2:
            result = _execute_and_finalize_in_conn(
                conn2,
                claim=decision,
                run_scope=run_scope,
                allow_paid=allow_paid,
                trigger_source=trigger_source,
                now_iso=now_iso,
                exec_hook=_exec_hook,
            )
            if record_external_audit:
                record_external_trigger_audit(
                    conn2,
                    mode=clean_mode,
                    trigger_source=trigger_source,
                    action=result["action"],
                    at_iso=now_iso,
                )
            try:
                result["persist"] = push_if_changed(conn2)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Persist push after monthly trend trigger failed: %s", exc)
                result["persist"] = {"pushed": False, "error": str(exc)[:200]}
            return result
    except Exception as exc:
        # Release lease cleanly into retry_needed so next retry/catch-up reuses the same prepared report_id!
        try:
            with transaction() as conn_err:
                conn_err.execute(
                    """
                    UPDATE monthly_trend_schedule_runs
                    SET status = 'retry_needed',
                        claim_token = '',
                        claim_expires_at = '',
                        detail = ?,
                        updated_at = ?
                    WHERE period_year = ? AND period_month = ? AND run_scope = ? AND claim_token = ?
                    """,
                    (
                        f"Onderbroken fout ({str(exc)[:160]}); wordt bij volgende trigger ingehaald zonder duplicaat.",
                        amsterdam_now().isoformat(),
                        int(decision["target_year"]),
                        int(decision["target_month"]),
                        run_scope,
                        str(decision["claim_token"]),
                    ),
                )
        except Exception:  # noqa: BLE001
            pass
        raise


def run_scheduled_first_of_month_tick(*, now_amsterdam: datetime | str | None = None) -> dict[str, Any]:
    """Entry point invoked by APScheduler & startup recovery (supports both 1st at 06:00 and catch-up after 1st)."""
    if now_amsterdam is not None:
        # Deterministic test path with synthetic timestamp
        from maaike.db import transaction

        paid_enabled = os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}
        with transaction() as conn:
            return ensure_monthly_trend_report(
                conn,
                now_amsterdam=now_amsterdam,
                simulate_without_paid_ai=not paid_enabled,
                only_on_first_of_month=False,
                allow_catchup_after_first=True,
                enforce_due_time=True,
                enforce_active_from=paid_enabled,
                trigger_source="apscheduler_tick",
            )

    paid_enabled = os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}
    return run_monthly_trend_trigger(
        mode="production" if paid_enabled else "simulation",
        trigger_source="apscheduler_tick",
        record_external_audit=False,
    )


def monthly_trend_schedule_status(conn) -> dict[str, Any]:
    ensure_monthly_trend_tables(conn)
    settings = get_monthly_trend_planner_settings(conn)
    runs = [
        dict(r)
        for r in conn.execute(
            """
            SELECT m.*, c.title AS report_title, c.status AS report_status, c.is_mock AS report_is_mock
            FROM monthly_trend_schedule_runs m
            LEFT JOIN client_reports c ON c.id = m.report_id
            ORDER BY m.period_year DESC, m.period_month DESC,
                     CASE WHEN m.run_scope = 'production' THEN 0 ELSE 1 END
            LIMIT 16
            """
        ).fetchall()
    ]
    paid_enabled = os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}
    ai_key_present = bool(os.getenv("AI_API_KEY", "").strip())
    cron_secret_configured = bool(os.getenv("MAAIKE_CRON_SECRET", "").strip())
    production_schedule_active = bool(
        settings["production_enabled"] and paid_enabled and ai_key_present and cron_secret_configured
    )
    next_run = next_first_of_month_amsterdam(active_from=settings["active_from"] if paid_enabled else None)
    return {
        "enabled": bool(settings["production_enabled"]),
        "production_schedule_active": production_schedule_active,
        "process_started": _started,
        "timezone": "Europe/Amsterdam",
        "rule": "1st_of_month_0600_with_catchup",
        "rule_label_nl": "Elke 1e van de maand rond 06:00 uur (Europe/Amsterdam) + automatische inhaalrun na de 1e",
        "paid_ai_enabled": paid_enabled,
        "ai_key_present": ai_key_present,
        "external_trigger_configured": cron_secret_configured,
        "external_trigger_endpoint": "/api/report-planning/monthly-trend/trigger",
        "catchup_after_first_enabled": bool(settings["catchup_enabled"]),
        "active_from": settings["active_from"],
        "last_external_trigger": {
            "at": settings["last_external_trigger_at"],
            "mode": settings["last_external_trigger_mode"],
            "source": settings["last_external_trigger_source"],
            "result": settings["last_external_trigger_result"],
        },
        "default_mode_label_nl": (
            f"Productieplanning actief (live AI vanaf {next_run['label_nl']}; inclusief externe wake-up & inhaalrun)"
            if production_schedule_active
            else (
                "Live AI-uitvoering geactiveerd (wacht op externe trigger-secret)"
                if paid_enabled
                else "Veilige simulatiemodus (geen betaalde AI-run tenzij live AI-uitvoering is vrijgegeven)"
            )
        ),
        "next_run": next_run,
        "last_event": dict(_last_event),
        "recent_runs": runs,
    }


def start_monthly_trend_scheduler() -> None:
    """Start automatic 1st-of-the-month + daily catch-up scheduler in Europe/Amsterdam."""
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
                CronTrigger(day=1, hour=SCHEDULED_HOUR_AMSTERDAM, minute=SCHEDULED_MINUTE_AMSTERDAM, timezone=AMSTERDAM),
                id="monthly_general_trend_primary",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600 * 18,
            )
            # Daily catch-up check at 06:20 Europe/Amsterdam (covers day 1 after 06:00 AND missed runs on day 2..31!)
            sched.add_job(
                run_scheduled_first_of_month_tick,
                CronTrigger(hour=6, minute=20, timezone=AMSTERDAM),
                id="monthly_general_trend_daily_catchup",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600 * 12,
            )
            sched.start()
            _scheduler = sched
            _started = True
            _last_event.update(
                {
                    "at": amsterdam_now().isoformat(),
                    "action": "started",
                    "detail": "Actief: elke 1e van de maand om 06:00 Europe/Amsterdam + automatische inhaalcontrole.",
                }
            )
            # Only run automatic startup catch-up when production paid mode is enabled (never create surprise mock rows on boot).
            if os.getenv("ENABLE_MONTHLY_TREND_PAID_AI", "0").strip().lower() in {"1", "true", "yes"}:
                def _startup_catchup() -> None:
                    try:
                        run_monthly_trend_trigger(
                            mode="production",
                            trigger_source="startup_catchup_check",
                            record_external_audit=False,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Startup monthly trend catch-up check failed: %s", exc)

                threading.Thread(target=_startup_catchup, name="monthly-trend-startup-catchup", daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not start monthly trend scheduler: %s", exc)
            _last_event.update(
                {
                    "at": amsterdam_now().isoformat(),
                    "action": "error",
                    "detail": f"Scheduler kon niet starten: {exc}",
                }
            )
