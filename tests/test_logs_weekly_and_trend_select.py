"""Logs weekly plan (separate from Competitors) + shared trend selection."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from maaike.comparison_service import save_weekly_plan, comparison_state
from maaike.db import initialize_database, transaction
from maaike.logs_weekly import (
    get_logs_weekly_plan,
    next_weekly_check_date,
    save_logs_weekly_plan,
    two_month_logs_window,
)
from maaike.migrate import apply_migrations
from maaike.report_planning import (
    last_sunday_of_month,
    resolve_report_period,
    resolve_shared_trend_report,
    start_or_resume_run,
    update_plan,
)
from maaike.repository import add_client
from maaike.reports import _trend_summary, ensure_report_tables


def test_logs_weekly_separate_from_competitors(tmp_path: Path, monkeypatch):
    db = tmp_path / "logs_weekly.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database(db)
    with transaction(db) as conn:
        apply_migrations(conn)
        cid = add_client(conn, "QA Logs")
        save_weekly_plan(conn, cid, enabled=True, weekday=1, time="10:00", note="competitors")
        # 2026-11-09 = Monday; 2026-11-10 = Tuesday
        logs = save_logs_weekly_plan(
            conn, cid, enabled=True, weekday=0, time="09:15", note="logs only", today=date(2026, 11, 9)
        )
        competitors = comparison_state(conn, cid)["weekly_plan"]
        assert logs["separate_from_competitors"] is True
        assert logs["auto_execute"] is False
        assert logs["weekday"] == 0
        assert logs["time"] == "09:15"
        assert logs["next_check_date"] == "2026-11-09"  # Monday on/after today
        assert competitors["weekday"] == 1
        assert competitors["time"] == "10:00"
        assert logs["window_from"] == "2026-10-01"
        assert logs["window_to"] == "2026-11-30"
        assert two_month_logs_window(date(2026, 11, 10)) == {
            "from": "2026-10-01",
            "to": "2026-11-30",
        }
        assert next_weekly_check_date(weekday=0, from_day=date(2026, 11, 10)) == date(2026, 11, 16)
        again = get_logs_weekly_plan(conn, cid, today=date(2026, 11, 9))
        assert again["enabled"] is True


def test_last_sunday_vs_qa_date_and_trend_pick(tmp_path: Path, monkeypatch):
    db = tmp_path / "trend_pick.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database(db)
    with transaction(db) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)
        owner = add_client(conn, "Trend Owner")
        other = add_client(conn, "Other Client")
        # Sept analysis → Nov planning trend (completed)
        conn.execute(
            """
            INSERT INTO client_reports (
                client_id, report_type, title, status, period_year, period_month,
                planning_year, planning_month, version, input_snapshot_json, body_json,
                prepared_at, executed_at, is_mock, created_at, updated_at
            ) VALUES (?, 'trend', 'Social trends – planning november 2026', 'completed',
                      2026, 9, 2026, 11, 1, '{}', '{}',
                      '2026-01-01', '2026-01-02', 0, '2026-01-01', '2026-01-02')
            """,
            (owner,),
        )
        nov_id = int(conn.execute("SELECT id FROM client_reports ORDER BY id DESC LIMIT 1").fetchone()["id"])
        # Oct analysis → Dec planning (mock)
        conn.execute(
            """
            INSERT INTO client_reports (
                client_id, report_type, title, status, period_year, period_month,
                planning_year, planning_month, version, input_snapshot_json, body_json,
                prepared_at, executed_at, is_mock, created_at, updated_at
            ) VALUES (?, 'trend', 'Social trends – planning december 2026', 'mock_completed',
                      2026, 10, 2026, 12, 1, '{}', '{}',
                      '2026-01-01', '2026-01-02', 1, '2026-01-01', '2026-01-02')
            """,
            (owner,),
        )
        dec_id = int(conn.execute("SELECT id FROM client_reports ORDER BY id DESC LIMIT 1").fetchone()["id"])

        assert last_sunday_of_month(2026, 11) == date(2026, 11, 29)
        # QA date 2026-11-30 is NOT last_sunday; both resolve previous calendar month → Oct
        assert resolve_report_period(
            {"period_mode": "previous_calendar_month", "period_year": None, "period_month": None},
            planned_day=date(2026, 11, 30),
        ) == (2026, 10)
        assert resolve_report_period(
            {"period_mode": "previous_calendar_month", "period_year": None, "period_month": None},
            planned_day=date(2026, 11, 29),
        ) == (2026, 10)

        picked = resolve_shared_trend_report(conn, analysis_year=2026, analysis_month=9)
        assert picked["id"] == nov_id
        assert picked["match_reason"] == "matched_planning_x2"

        picked_oct = resolve_shared_trend_report(conn, analysis_year=2026, analysis_month=10)
        assert picked_oct["id"] == dec_id

        # Shared across clients: other client can link owner trend
        summary = _trend_summary(conn, other, nov_id)
        assert summary["shared_across_clients"] is True
        assert summary["id"] == nov_id

        update_plan(
            conn,
            {
                "auto_execute": False,
                "include_trend_report": True,
                "shared_trend_report_id": None,
                "period_mode": "fixed_month",
                "period_year": 2026,
                "period_month": 9,
                "client_ids": [other],
                "recurring_rule": "last_sunday_of_month",
                "start_time": "09:00",
            },
        )
        run = start_or_resume_run(conn, planned_date="2026-11-30", prepare_concepts=True)
        assert run["deduped"] is False
        assert run["trend_selection"]["id"] == nov_id
        assert run["run"]["shared_trend_report_id"] == nov_id
        assert run["run"]["period_year"] == 2026
        assert run["run"]["period_month"] == 9
