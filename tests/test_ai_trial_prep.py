"""AI trial preparation without paid API calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from maaike.ai_trial import (
    accept_ai_proposal,
    apply_mock_ai_result,
    begin_paid_execution_guard,
    get_trial,
    prepare_redrock_trial,
    save_human_feedback,
)
from maaike.ai_trial_request import filter_formats_for_role
from maaike.db import initialize_database, transaction
from maaike.strategy import get_strategy, prefill_red_rock_from_sources


def test_strategy_website_enrichment_splits_sectors_and_region(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "t.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    imports = Path(__file__).resolve().parents[1] / "data" / "imports" / "redrock"
    initialize_database()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        conn.execute(
            """
            INSERT INTO client_strategy (
                client_id, account_info_json, start_answers_json, strategy_fields_json,
                source_notes_json, completed_at, updated_at
            ) VALUES (?, '{}', ?, '{}', '[]', NULL, '2026-01-01T00:00:00+00:00')
            ON CONFLICT(client_id) DO UPDATE SET start_answers_json = excluded.start_answers_json
            """,
            (
                client_id,
                json.dumps({"tone_of_voice": "Handmatig bewaard zonder bronmarker."}, ensure_ascii=False),
            ),
        )
        prefill_red_rock_from_sources(conn, client_id, imports)
        strategy = get_strategy(conn, client_id)
    answers = strategy["start_answers"]
    assert answers["website"].startswith("https://redrockagency.nl")
    assert "sectoren" in answers and "woon" in answers["sectoren"].lower()
    assert "niet expliciet" in answers["geografische_regio"].lower()
    assert answers["tone_of_voice"] == "Handmatig bewaard zonder bronmarker."
    pending_keys = {item["key"] for item in strategy["pending_questions"]}
    assert "gewenste_socialresultaten" in pending_keys


def test_format_filter_blocks_c_codes_for_image() -> None:
    formats = [
        {"code": "C05", "explanation": "carrousel"},
        {"code": "R07", "explanation": "reel"},
    ]
    image_pack = filter_formats_for_role("image", formats)
    assert image_pack["eligible_formats"] == []
    assert image_pack["not_auto_assign_carousel_to_image"] is True
    carousel_pack = filter_formats_for_role("carousel", formats)
    assert [f["code"] for f in carousel_pack["eligible_formats"]] == ["C05"]
    reel_pack = filter_formats_for_role("reel", formats)
    assert [f["code"] for f in reel_pack["eligible_formats"]] == ["R07"]


def test_ai_trial_prepare_keeps_excel_out_and_isolates_clients(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "trial.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    now = datetime.now(tz=timezone.utc).isoformat()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        for post_id, kind, media in (
            (31, "image", "https://cdn.example/a.jpg"),
            (16, "carousel_album", "https://cdn.example/1.jpg https://cdn.example/2.jpg"),
            (8, "reel", "https://cdn.example/v.mp4"),
        ):
            conn.execute(
                """
                INSERT INTO posts (
                    id, client_id, platform, external_id, published_at, content_kind, permalink,
                    caption, media_urls
                ) VALUES (?, ?, 'instagram', ?, ?, ?, ?, 'caption', ?)
                """,
                (post_id, client_id, f"ext-{post_id}", now, kind, f"https://instagram.com/p/{post_id}", media),
            )
            conn.execute(
                """
                INSERT INTO post_assessments (
                    post_id, source, source_label, rating_text, insight_text, action_text, imported_at
                ) VALUES (?, 'excel_imported', 'Overgenomen uit Excel', 'Goed', 'geheim insight', 'geheim actie', ?)
                """,
                (post_id, now),
            )
            conn.execute(
                """
                INSERT INTO content_formats (client_id, name, explanation, created_at, updated_at)
                VALUES (?, ?, 'Uitleg', ?, ?)
                """,
                (client_id, "C05" if post_id == 16 else "R07" if post_id == 8 else "C01", now, now),
            )
        payload = prepare_redrock_trial(conn, client_id, download_media=False)
        trial = payload["trial"]
        assert trial["status"] == "prepared_not_executed"
        assert trial["prompt_version"].endswith("v2")
        assert trial["capability"]["is_claude"] is False
        assert "Gemini" in trial["capability"]["provider"] or trial["capability"]["provider"]
        for post in trial["posts"]:
            req = json.dumps(post["request_payload"])
            assert "geheim insight" not in req
            assert "geheim actie" not in req
            assert post["request_payload"]["excel_assessment_included"] is False
            assert post["excel_assessment"]["insight_text"] == "geheim insight"
            if post["role"] == "image":
                assert post["input_preview"]["format_pack"]["eligible_formats"] == []
        for ev in trial["usage_events"]:
            assert ev["prompt_tokens"] is None
            assert ev["actual_cost"] is None
            assert ev["cost_known"] == 0

        other = conn.execute("SELECT id FROM clients WHERE name = 'Test'").fetchone()
        if other is None:
            conn.execute(
                "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('Test', ?, ?, 'not_connected')",
                (now, now),
            )
            other_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Test'").fetchone()[0])
        else:
            other_id = int(other["id"])
        assert get_trial(conn, other_id)["trial"] is None

        begin_paid_execution_guard(conn, client_id)
        try:
            begin_paid_execution_guard(conn, client_id)
            raised = False
        except ValueError:
            raised = True
        assert raised
        # reset status so mock apply can continue
        conn.execute(
            "UPDATE ai_trial_runs SET status = 'prepared_not_executed', executed_at = NULL WHERE client_id = ?",
            (client_id,),
        )

        apply_mock_ai_result(
            conn,
            client_id,
            31,
            {
                "observations": [{"evidence_ref": "image", "fact": "mock"}],
                "proposed_format_code": "Geen passend bestaand format",
                "format_rationale": "geen image-code",
                "format_uncertainty": "hoog",
                "proposed_pillar": "Strategie & Expertise",
                "proposed_hook": "mock hook",
                "ai_insight": "mock insight",
                "ai_action": "mock action",
            },
            usage={"status": "mock_completed", "cost_known": False},
        )
        accepted = accept_ai_proposal(conn, client_id, 31, {})
        item = next(p for p in accepted["trial"]["posts"] if p["post_id"] == 31)
        assert item["accepted_proposal_json"]["overwrote_excel"] is False
        assert item["ai_format_code"] == "Geen passend bestaand format"
        assert conn.execute("SELECT format_id FROM post_editorial WHERE post_id = 31").fetchone() is None
        excel = conn.execute(
            "SELECT insight_text FROM post_assessments WHERE post_id = 31"
        ).fetchone()
        assert excel["insight_text"] == "geheim insight"

        save_human_feedback(conn, client_id, 31, "")
        again = get_trial(conn, client_id)
        item = next(p for p in again["trial"]["posts"] if p["post_id"] == 31)
        assert "niet menselijk beoordeeld" in item["joint_verdict"].lower()
