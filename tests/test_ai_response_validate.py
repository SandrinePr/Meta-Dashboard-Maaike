"""LOCAL_TEST: AI answer validation for posts/reports — no paid Claude/Gemini calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from maaike.ai_response_validate import (
    extract_json_object,
    format_specs,
    validate_client_report_body,
    validate_post_analysis,
    validate_report_body,
    validate_trend_report_body,
)
from maaike.ai_trial import apply_mock_ai_result, get_trial, prepare_redrock_trial
from maaike.ai_trial_feedback import save_feedback
from maaike.db import initialize_database, transaction
from maaike.report_execute import apply_execution_mock
from maaike.report_review import save_report_review
from maaike.reports import apply_mock_report, get_report, prepare_client_report, prepare_trend_report


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _valid_post() -> dict:
    return {
        "observations": [{"evidence_ref": "image", "fact": "LOCAL_TEST zichtbaar product in beeld"}],
        "proposed_format_code": "Geen passend bestaand format",
        "format_rationale": "Geen C-code voor stilstaande image in legenda.",
        "format_uncertainty": "laag",
        "proposed_pillar": "Strategie & Expertise",
        "proposed_hook": "LOCAL_TEST hookvoorbeeld",
        "ai_insight": "LOCAL_TEST: inzicht op basis van mockbeeld.",
        "ai_action": "LOCAL_TEST: actie voor menselijke check.",
        "hypotheses": ["Hypothese: bereik door thumbnail."],
        "unassessable": [],
        "limitations_acknowledged": ["LOCAL_TEST / MOCK"],
    }


def test_format_specs_documented():
    specs = format_specs()
    assert "post_analysis" in specs
    assert "six_answers" in str(specs["client_report"])
    assert "conclusie" in specs["trend_report"]["chapter_keys"]
    assert "Claude" in specs["note"] or "claude" in specs["note"].lower()


def test_post_full_incomplete_malformed_empty():
    full = validate_post_analysis(_valid_post(), test_label="LOCAL_TEST full")
    assert full.ok and full.usable
    assert full.normalized["ai_insight"].startswith("LOCAL_TEST")

    incomplete = validate_post_analysis(
        {
            "observations": [],
            "proposed_format_code": "",
            "format_rationale": "",
            "format_uncertainty": "",
            "proposed_pillar": "",
            "proposed_hook": "",
            "ai_insight": "",
            "ai_action": "",
        },
        test_label="LOCAL_TEST incomplete",
    )
    assert not incomplete.usable
    assert incomplete.errors

    malformed = validate_post_analysis(["not", "an", "object"], raw_text='["x"]', test_label="LOCAL_TEST malformed")
    assert not malformed.usable

    empty = validate_post_analysis({}, raw_text="", test_label="LOCAL_TEST empty")
    assert not empty.usable

    none_r = validate_post_analysis(None, raw_text="", test_label="LOCAL_TEST none")
    assert not none_r.usable

    # Placeholder-only shell
    shell = validate_post_analysis(
        {
            "observations": [],
            "proposed_format_code": "Niet vast te stellen",
            "format_rationale": "",
            "format_uncertainty": "onbekend",
            "proposed_pillar": "Niet vast te stellen",
            "proposed_hook": "Niet vast te stellen",
            "ai_insight": "",
            "ai_action": "",
            "hypotheses": [],
            "unassessable": [],
            "limitations_acknowledged": [],
        },
        test_label="LOCAL_TEST placeholders",
    )
    assert not shell.usable


def test_client_and_trend_shapes():
    client_ok = validate_client_report_body(
        {
            "six_answers": {
                "beter": "LOCAL_TEST beter antwoord lang genoeg.",
                "slechter": "LOCAL_TEST slechter antwoord lang genoeg.",
                "verklaring": "LOCAL_TEST verklaring met voldoende tekst.",
                "herhalen": "LOCAL_TEST herhalen met voldoende tekst.",
                "stoppen": "LOCAL_TEST stoppen met voldoende tekst.",
                "testen": "LOCAL_TEST testen met voldoende tekst.",
            },
            "chapters": {
                "input_brainstorm": "LOCAL_TEST input brainstorm met inhoud.",
                "per_kanaal": "LOCAL_TEST per kanaal met inhoud.",
                "seo_serp": "Niet onderzocht / onvoldoende gegevens — LOCAL_TEST seo.",
                "concurrenten": "Niet onderzocht / onvoldoende gegevens — LOCAL_TEST concurrenten.",
                "hooks_formats_testen": "LOCAL_TEST hooks formats met inhoud.",
                "laten_liggen_aanscherpen": "LOCAL_TEST laten liggen met inhoud.",
            },
            "action_plan": {
                "planning_note": "LOCAL_TEST planningsnoot voldoende tekst.",
                "hoofdfocus": "LOCAL_TEST hoofdfocus voldoende tekst.",
                "waarom_nu": "LOCAL_TEST waarom nu voldoende tekst.",
                "actions": [
                    "LOCAL_TEST actie één concreet.",
                    "LOCAL_TEST actie twee concreet.",
                    "LOCAL_TEST actie drie concreet.",
                ],
                "stop_or_test_decisions": ["LOCAL_TEST stop of test besluit."],
                "watch_outs": ["LOCAL_TEST watch-out."],
            },
        },
        test_label="LOCAL_TEST client full",
    )
    assert client_ok.usable
    assert client_ok.normalized["requires_human_approval"] is True
    assert client_ok.normalized["chapters"]["per_kanaal"]
    assert len(client_ok.normalized["action_plan"]["actions"]) == 3

    client_six_only = validate_client_report_body(
        {
            "six_answers": {
                "beter": "LOCAL_TEST beter antwoord lang genoeg.",
                "slechter": "LOCAL_TEST slechter antwoord lang genoeg.",
                "verklaring": "LOCAL_TEST verklaring met voldoende tekst.",
                "herhalen": "LOCAL_TEST herhalen met voldoende tekst.",
                "stoppen": "LOCAL_TEST stoppen met voldoende tekst.",
                "testen": "LOCAL_TEST testen met voldoende tekst.",
            }
        },
        test_label="LOCAL_TEST client six only",
    )
    assert not client_six_only.usable

    client_empty = validate_client_report_body({"six_answers": {}}, test_label="LOCAL_TEST client empty")
    assert not client_empty.usable

    client_raw_only = validate_client_report_body(
        {"raw_text": "Dit is proza zonder JSON."},
        raw_text="Dit is proza zonder JSON.",
        test_label="LOCAL_TEST client prose",
    )
    assert not client_raw_only.usable
    assert "raw_response" in (client_raw_only.normalized or {})

    trend_ok = validate_trend_report_body(
        {
            "chapters": {
                "managementsamenvatting": "LOCAL_TEST managementsamenvatting met inhoud.",
                "conclusie": "LOCAL_TEST conclusie met prioriteiten.",
                "positionering": "LOCAL_TEST positionering.",
            },
            "distinctions": {"facts": ["f"], "trends": [], "suggestions": []},
        },
        test_label="LOCAL_TEST trend full",
    )
    assert trend_ok.usable
    assert "conclusie" in trend_ok.normalized["chapters"]

    # Alias conclusion → conclusie
    trend_alias = validate_trend_report_body(
        {
            "chapters": {
                "managementsamenvatting": "LOCAL_TEST managementsamenvatting met inhoud.",
                "conclusion": "LOCAL_TEST via alias conclusion.",
            }
        },
        test_label="LOCAL_TEST trend alias",
    )
    assert trend_alias.usable

    trend_incomplete = validate_trend_report_body(
        {"chapters": {"managementsamenvatting": "kort"}},
        test_label="LOCAL_TEST trend incomplete",
    )
    assert not trend_incomplete.usable

    bad_json, err = extract_json_object("niet json {")
    assert bad_json is None and err


def test_mock_post_rejects_empty_and_keeps_feedback_on_reanalysis(tmp_path: Path, monkeypatch):
    db = tmp_path / "postval.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        now = _now()
        for post_id, kind, media in (
            (31, "image", "https://cdn.example/a.jpg"),
            (16, "carousel_album", "https://cdn.example/1.jpg"),
            (8, "reel", "https://cdn.example/v.mp4"),
        ):
            conn.execute(
                """
                INSERT OR REPLACE INTO posts (
                    id, client_id, platform, external_id, published_at, content_kind,
                    permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
                ) VALUES (?, ?, 'instagram', ?, ?, ?, ?, 'c', ?, 10, 1, 0, 0, 0, 0, 5)
                """,
                (post_id, client_id, f"ext-{post_id}", now, kind, f"https://ig/{post_id}", media),
            )
        prepare_redrock_trial(conn, client_id, download_media=False)

        # Empty / unusable → failed, not mock_completed
        try:
            apply_mock_ai_result(conn, client_id, 31, {})
            raised = False
        except ValueError as exc:
            raised = True
            assert "onbruikbaar" in str(exc).lower() or "Onbruikbaar" in str(exc)
        assert raised
        trial = get_trial(conn, client_id)["trial"]
        post = next(p for p in trial["posts"] if p["post_id"] == 31)
        assert post["status"] == "failed"
        live = (post.get("request_payload") or {}).get("_live_ai_result") or post.get("live_ai_result") or {}
        # get_trial may expose live differently — check DB
        row = conn.execute(
            "SELECT status, request_payload_json FROM ai_trial_posts WHERE post_id = 31"
        ).fetchone()
        assert row["status"] == "failed"
        blob = json.loads(row["request_payload_json"])["_live_ai_result"]
        assert blob.get("analysis_usable") is False
        assert blob.get("raw_response") is not None

        # Valid mock → success + feedback bound to execution_key
        apply_mock_ai_result(conn, client_id, 31, _valid_post())
        trial = get_trial(conn, client_id)["trial"]
        post = next(p for p in trial["posts"] if p["post_id"] == 31)
        key1 = post["execution_key"]
        assert post["status"] == "mock_completed"

        save_feedback(
            conn,
            client_id,
            31,
            {
                "usability": "usable",
                "notes": "LOCAL_TEST feedback",
                "final_verdict": "LOCAL_TEST eindversie goedgekeurd genoeg tekst.",
                "final_version_text": "LOCAL_TEST eindversie goedgekeurd genoeg tekst.",
                "reviewer_name": "QA Controle",
                "confirm_final_verdict": True,
                "item_decisions": [
                    {
                        "key": "insight",
                        "label": "Insight",
                        "ai_text": "x",
                        "decision": "accept",
                        "human_text": "",
                    }
                ],
            },
        )
        fb_count = conn.execute(
            "SELECT COUNT(*) n FROM ai_analysis_feedback WHERE client_id = ? AND post_id = 31",
            (client_id,),
        ).fetchone()["n"]
        assert fb_count == 1
        approved_key = conn.execute(
            "SELECT execution_key, final_verdict_confirmed FROM ai_analysis_feedback WHERE post_id = 31"
        ).fetchone()
        assert approved_key["final_verdict_confirmed"] == 1
        assert approved_key["execution_key"] == key1

        # Re-analyse: new key; old approval untouched
        apply_mock_ai_result(
            conn,
            client_id,
            31,
            {
                **_valid_post(),
                "ai_insight": "LOCAL_TEST tweede analyse — andere inhoud.",
                "ai_action": "LOCAL_TEST tweede actie voor heranalyse.",
            },
        )
        trial2 = get_trial(conn, client_id)["trial"]
        post2 = next(p for p in trial2["posts"] if p["post_id"] == 31)
        key2 = post2["execution_key"]
        assert key2 != key1
        assert post2.get("human_feedback_record") is None or post2["human_feedback_record"].get(
            "execution_key"
        ) != key1 or not post2["human_feedback_record"].get("final_verdict_confirmed")
        # Old row still approved on key1
        old = conn.execute(
            "SELECT final_verdict, final_verdict_confirmed FROM ai_analysis_feedback WHERE execution_key = ?",
            (key1,),
        ).fetchone()
        assert old["final_verdict_confirmed"] == 1
        assert "LOCAL_TEST eindversie" in old["final_verdict"]
        # New execution has no auto-copied approval
        new_fb = conn.execute(
            "SELECT COUNT(*) n FROM ai_analysis_feedback WHERE execution_key = ?",
            (key2,),
        ).fetchone()["n"]
        assert new_fb == 0


def test_report_validation_and_unusable_not_approvable(tmp_path: Path, monkeypatch):
    db = tmp_path / "repval.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    with transaction() as conn:
        qa = conn.execute(
            "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('QA Controle', ?, ?, 'not_connected')",
            (_now(), _now()),
        ).lastrowid

        # Empty-ish prose failure via sources_missing scenario
        trend = prepare_trend_report(
            conn, qa, run_year=2026, run_month=11, sources=[], research_mode="manual", max_budget_usd=0.01
        )
        tid = trend["report"]["id"]
        failed = apply_execution_mock(conn, qa, tid, scenario="sources_missing")
        assert failed["report"]["status"] == "failed"
        assert failed["report"]["body"].get("analysis_usable") is False
        assert failed["report"]["body"].get("raw_response")
        assert failed["review"]["can_review"] is False
        try:
            save_report_review(conn, qa, tid, {"approve": True, "reviewer_name": "X", "final_version_text": "y" * 20})
            ok = False
        except ValueError:
            ok = True
        assert ok

        # Full mock client success → reviewable
        client = prepare_client_report(
            conn, qa, period_year=2026, period_month=9, allow_partial_without_trend=True, max_budget_usd=0.01
        )
        rid = client["report"]["id"]
        mocked = apply_mock_report(conn, qa, rid)
        assert mocked["report"]["status"] == "mock_completed"
        assert mocked["report"]["body"].get("analysis_usable") is True
        assert mocked["report"]["body"].get("test_label", "").startswith("LOCAL_TEST")
        assert mocked["review"]["can_review"] is True
        key1 = mocked["review"]["execution_key"]

        items = mocked["review"]["item_feedback"]
        for item in items:
            if item["key"] == "six_answers.beter":
                item["decision"] = "accept"
            elif item["key"] == "addition.staff":
                item["decision"] = "add"
                item["human_text"] = "LOCAL_TEST aanvulling"
        draft = save_report_review(
            conn,
            qa,
            rid,
            {
                "reviewer_name": "QA Controle",
                "item_feedback": items,
                "compose_final_from_items": True,
            },
        )
        approved = save_report_review(
            conn,
            qa,
            rid,
            {
                "reviewer_name": "QA Controle",
                "item_feedback": items,
                "final_version_text": draft["review"]["final_version_text"],
                "approve": True,
            },
        )
        assert approved["review"]["is_approved"] is True

        # New version: old approval intact, new not approved
        client2 = prepare_client_report(
            conn, qa, period_year=2026, period_month=9, allow_partial_without_trend=True, max_budget_usd=0.01
        )
        mocked2 = apply_mock_report(conn, qa, client2["report"]["id"])
        assert mocked2["review"]["is_approved"] is False
        assert mocked2["review"]["execution_key"] != key1
        old = get_report(conn, qa, rid)
        assert old["review"]["is_approved"] is True
        assert old["review"]["execution_key"] == key1

        # Malformed success path should not mark completed — inject via validate_report_body
        bad = validate_report_body("client", {"six_answers": {"beter": "x"}}, test_label="LOCAL_TEST thin")
        assert not bad.usable
