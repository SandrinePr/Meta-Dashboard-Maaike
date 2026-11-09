"""Execute model-input preview matches execute payload; no paid AI."""

from __future__ import annotations

from pathlib import Path

from maaike.db import initialize_database, transaction
from maaike.migrate import apply_migrations
from maaike.report_execute import build_execute_model_input, model_input_presence_checklist
from maaike.reports import inspect_client_report_data, prepare_client_report
from maaike.repository import add_client
from maaike.strategy import save_strategy


def test_inspect_and_prepare_include_analysis_context(tmp_path: Path, monkeypatch):
    db = tmp_path / "model.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database(db)
    with transaction(db) as conn:
        apply_migrations(conn)
        client_id = add_client(conn, "QA Model")
        save_strategy(
            conn,
            client_id,
            account_info={"naam": "QA Model"},
            start_answers={
                "tone_of_voice": "Warm en concreet",
                "platforms": "Instagram; LinkedIn",
            },
            strategy_fields={
                "feedback_tov": "Feedback: blijf menselijk.",
                "excel_month_contexts": [
                    {
                        "sheet_name": "April 2026",
                        "client_label": "QA Model",
                        "planning_year": 2026,
                        "planning_month": 4,
                        "analysis_year": 2026,
                        "analysis_month": 3,
                        "analyse_vorige_planning": "Cases deden het beter.",
                        "bijzonderheden": "Event week 2",
                        "stories": [{"text": "Story A"}],
                        "has_analyse": True,
                        "has_bijzonderheden": True,
                    }
                ],
            },
            source_notes=[],
        )
        conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, content_kind, permalink,
                views, likes, comments, shares, saves, clicks, reach
            ) VALUES (?, 'instagram', 'x1', '2026-03-10T12:00:00+00:00', 'Reel', 'https://ig/p/1',
                      10, 1, 0, 0, 0, 0, 20)
            """,
            (client_id,),
        )
        inspect = inspect_client_report_data(
            conn, client_id, period_year=2026, period_month=3
        )
        assert inspect["prompt_input"]["analysis_context"]["feedback_tov"]["present"] is True
        assert inspect["prompt_input"]["analysis_context"]["month_context"]["present"] is True
        assert inspect["prompt_input"]["periods"]["analysis_period"]["month"] == 3

        prepared = prepare_client_report(
            conn,
            client_id,
            period_year=2026,
            period_month=3,
            allow_partial_without_trend=True,
        )
        snap = prepared["report"]["input_snapshot"]
        assert snap["period"]["analysis_period"]["month"] == 3
        assert snap["period"]["planning_period"]["month"] == 4
        assert snap["analysis_context"]["feedback_tov"]["present"] is True
        model = build_execute_model_input(prepared["report"], snap)
        checklist = model_input_presence_checklist(model)
        by_key = {c["key"]: c for c in checklist}
        assert by_key["feedback_tov"]["present"] is True
        assert by_key["month_analyse"]["present"] is True
        assert by_key["analysis_period"]["present"] is True
        assert by_key["planning_period"]["present"] is True
        assert by_key["client_isolation"]["present"] is True
        assert by_key["workflow_prompts_local"]["present"] is True
        other = add_client(conn, "Other")
        other_inspect = inspect_client_report_data(
            conn, other, period_year=2026, period_month=3
        )
        assert other_inspect["prompt_input"]["analysis_context"]["feedback_tov"]["present"] is False
