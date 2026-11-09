"""LOCAL_TEST: Claude post analyses attach into client-report input; source honesty.

No paid AI calls. Does not prove the model will never invent source claims.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from maaike.ai_response_validate import (
    NOT_RESEARCHED_PHRASE,
    audit_unfounded_source_claims,
    validate_client_report_body,
)
from maaike.db import connect
from maaike.report_metrics import attach_assessments_and_ai, summarize_attached_ai_analyses
from maaike.reports import (
    annotate_client_report_source_grounding,
    inspect_client_report_data,
)

REPO = Path(__file__).resolve().parents[1]
LIVE_DB = REPO / "data" / "maaike_redrock.db"


def _live_conn() -> sqlite3.Connection:
    if not LIVE_DB.exists():
        pytest.skip("maaike_redrock.db missing")
    return connect(LIVE_DB)


def test_local_preview_includes_analysis_2_for_post_3():
    """LOCAL_TEST preview: completed Claude analysis #2 for post #3 is in client input."""
    conn = _live_conn()
    try:
        row = conn.execute(
            """
            SELECT id, client_id, post_id, status, prompt_version
            FROM post_ai_analyses WHERE id = 2
            """
        ).fetchone()
        assert row is not None
        assert row["post_id"] == 3
        assert row["status"] == "completed"
        assert "v2" in (row["prompt_version"] or "")
        client_id = int(row["client_id"])

        preview = inspect_client_report_data(
            conn,
            client_id,
            period_year=2026,
            period_month=9,
        )
        assert preview["persisted"] is False
        assert preview["ai_analysis_executed"] is True
        assert preview["ai_analysis_status"] == "completed_analyses_attached"
        assert 2 in (preview.get("attached_ai_analysis_ids") or [])

        posts = preview["posts"]
        post3 = next(p for p in posts if p.get("post_id") == 3)
        ai = post3.get("ai_analysis") or {}
        assert ai.get("source") == "post_ai_analyses"
        assert ai.get("id") == 2
        assert ai.get("post_id") == 3
        assert ai.get("client_id") == client_id
        assert ai.get("status") == "completed"
        assert ai.get("prompt_version")
        assert (ai.get("insight_text") or ai.get("ai_insight") or "").strip()

        attached = preview["prompt_input"]["post_data"]["attached_ai_analyses"]
        assert 2 in attached["analysis_ids"]
        assert 3 in attached["post_ids"]
    finally:
        conn.close()


def test_report_7_snapshot_preserved_and_annotated_partial():
    """LOCAL_TEST: annotate #7 without rewriting snapshot or original AI chapters."""
    conn = _live_conn()
    try:
        before = conn.execute(
            "SELECT input_snapshot_json, body_json, notes_json FROM client_reports WHERE id = 7"
        ).fetchone()
        assert before is not None
        snap_before = before["input_snapshot_json"]
        body_before = json.loads(before["body_json"] or "{}")
        chapters_before = json.dumps(body_before.get("chapters") or {}, ensure_ascii=False)
        answers_before = json.dumps(body_before.get("six_answers") or {}, ensure_ascii=False)

        annotated = annotate_client_report_source_grounding(conn, 1, 7, preserve_snapshot=True)
        report = annotated["report"]
        after = conn.execute(
            "SELECT input_snapshot_json, body_json, notes_json FROM client_reports WHERE id = 7"
        ).fetchone()
        assert after["input_snapshot_json"] == snap_before

        body = json.loads(after["body_json"] or "{}")
        assert json.dumps(body.get("chapters") or {}, ensure_ascii=False) == chapters_before
        assert json.dumps(body.get("six_answers") or {}, ensure_ascii=False) == answers_before
        assert body.get("original_ai_output_preserved") is True
        assert body.get("partial") is True
        assert body.get("analysis_usable") is False
        grounding = body.get("source_grounding") or {}
        assert grounding.get("ok") is False
        assert grounding.get("approved") is False
        assert grounding.get("requires_human_review") is True
        assert grounding.get("unfounded_claims")
        kinds = {c.get("kind") for c in grounding["unfounded_claims"]}
        assert "ahrefs" in kinds or "seo_serp" in kinds
        assert "concurrenten" in kinds
        notes = json.loads(after["notes_json"] or "[]")
        assert any("PARTIEEL" in str(n) for n in notes)
        assert report["body"]["source_grounding"]["approved"] is False
    finally:
        conn.close()


def test_source_honesty_accepts_not_researched_phrase():
    body = {
        "six_answers": {
            "beter": "Format A had hogere bekende reach in Python-metrics.",
            "slechter": "Format B miste bereikcijfers; niet als 0 gelezen.",
            "verklaring": "Hypothese op basis van aangeleverde postmetrics alleen.",
            "herhalen": "Herhaal format A na menselijke check van Excel-rating.",
            "stoppen": "Stop format C na drie zwakke metingen indien bevestigd.",
            "testen": "Eén gecontroleerde test met meetplan op hook-variant.",
        },
        "chapters": {
            "input_brainstorm": "Brainstorm op basis van Python-aggregatie en strategie.",
            "per_kanaal": "Instagram: focus op formats met bekende reach in snapshot.",
            "seo_serp": NOT_RESEARCHED_PHRASE,
            "concurrenten": NOT_RESEARCHED_PHRASE,
            "hooks_formats_testen": "Test carrousel-hook in beeld i.p.v. alleen caption.",
            "laten_liggen_aanscherpen": "Laat zwakke formats liggen tot meetplan klaar is.",
        },
        "action_plan": {
            "planning_note": "Actieplan na inzichten; menselijke goedkeuring verplicht.",
            "hoofdfocus": "Herhaal sterk format met meetbare hook in openingsbeeld.",
            "waarom_nu": "Periode-metrics tonen herhaalbaar bereik op bekende posts.",
            "actions": ["Herhaal format A", "Plan één hook-test", "Bevestig stop op format C"],
            "stop_or_test_decisions": ["Format C: stop of één optimalisatietest"],
            "watch_outs": ["Geen SEO/concurrentclaims zonder bronnen"],
        },
    }
    result = validate_client_report_body(
        body,
        test_label="LOCAL_TEST honest missing sources",
        available_sources={
            "seo_sources_supplied": False,
            "ahrefs_sources_supplied": False,
            "competitor_sources_supplied": False,
            "trend_linked": False,
        },
    )
    assert result.usable is True
    assert result.normalized["source_grounding"]["ok"] is True


def test_source_honesty_rejects_ahrefs_without_sources():
    body = {
        "six_answers": {
            "beter": "Format A had hogere bekende reach in Python-metrics.",
            "slechter": "Format B miste bereikcijfers; niet als 0 gelezen.",
            "verklaring": "Hypothese op basis van aangeleverde postmetrics alleen.",
            "herhalen": "Herhaal format A na menselijke check van Excel-rating.",
            "stoppen": "Stop format C na drie zwakke metingen indien bevestigd.",
            "testen": "Eén gecontroleerde test met meetplan op hook-variant.",
        },
        "chapters": {
            "input_brainstorm": "Brainstorm op basis van Python-aggregatie en strategie.",
            "per_kanaal": "Instagram: focus op formats met bekende reach in snapshot.",
            "seo_serp": (
                "SEO via Ahrefs toont kansen met KD onder 5 en zoekvolume 200+ "
                "in de woonsector (conform richtlijnen)."
            ),
            "concurrenten": (
                "Concurrentieanalyse toont dat spelers die consistent expertise "
                "combineren meer autoriteit opbouwen."
            ),
            "hooks_formats_testen": "Test carrousel-hook in beeld i.p.v. alleen caption.",
            "laten_liggen_aanscherpen": "Laat zwakke formats liggen tot meetplan klaar is.",
        },
        "action_plan": {
            "planning_note": "Actieplan na inzichten; menselijke goedkeuring verplicht.",
            "hoofdfocus": "Herhaal sterk format met meetbare hook in openingsbeeld.",
            "waarom_nu": "Periode-metrics tonen herhaalbaar bereik op bekende posts.",
            "actions": ["Herhaal format A", "Plan één hook-test", "Bevestig stop op format C"],
            "stop_or_test_decisions": ["Format C: stop of één optimalisatietest"],
            "watch_outs": ["Controleer bronclaims handmatig"],
        },
    }
    findings = audit_unfounded_source_claims(
        body,
        available_sources={
            "seo_sources_supplied": False,
            "ahrefs_sources_supplied": False,
            "competitor_sources_supplied": False,
            "trend_linked": False,
        },
    )
    assert findings
    result = validate_client_report_body(
        body,
        test_label="LOCAL_TEST unfounded Ahrefs",
        available_sources={
            "seo_sources_supplied": False,
            "ahrefs_sources_supplied": False,
            "competitor_sources_supplied": False,
            "trend_linked": False,
        },
    )
    assert result.usable is False
    assert result.normalized["partial"] is True
    assert result.normalized["source_grounding"]["ok"] is False


def test_attach_prefers_completed_post_ai_over_trial(tmp_path):
    """Unit: completed post_ai_analyses wins over ai_trial_posts for same post."""
    db = tmp_path / "attach.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY, client_id INTEGER, published_at TEXT, platform TEXT
        );
        CREATE TABLE post_assessments (
            id INTEGER PRIMARY KEY, post_id INTEGER, source_label TEXT,
            rating_text TEXT, insight_text TEXT, action_text TEXT, imported_at TEXT
        );
        CREATE TABLE ai_trial_runs (
            id INTEGER PRIMARY KEY, client_id INTEGER, executed_at TEXT, model TEXT, prompt_version TEXT
        );
        CREATE TABLE ai_trial_posts (
            id INTEGER PRIMARY KEY, trial_run_id INTEGER, post_id INTEGER,
            ai_format_code TEXT, ai_pillar TEXT, ai_hook TEXT, ai_insight TEXT, ai_action TEXT,
            status TEXT, joint_verdict TEXT
        );
        CREATE TABLE ai_analysis_feedback (
            id INTEGER PRIMARY KEY, client_id INTEGER, post_id INTEGER, usability TEXT,
            notes TEXT, final_verdict TEXT, final_verdict_confirmed INTEGER,
            corrected_format TEXT, corrected_pillar TEXT, corrected_hook TEXT,
            updated_at TEXT, execution_key TEXT
        );
        INSERT INTO clients(id, name) VALUES (1, 'Test');
        INSERT INTO posts(id, client_id, published_at, platform) VALUES (3, 1, '2026-09-24', 'instagram');
        INSERT INTO ai_trial_runs(id, client_id, executed_at, model, prompt_version)
        VALUES (1, 1, '2026-01-01', 'mock', 'trial-v1');
        INSERT INTO ai_trial_posts(
            id, trial_run_id, post_id, ai_format_code, ai_pillar, ai_hook,
            ai_insight, ai_action, status, joint_verdict
        ) VALUES (1, 1, 3, 'X', 'Y', 'Z', 'trial insight', 'trial action', 'done', 'ok');
        """
    )
    from maaike.claude_analysis import ensure_analysis_tables

    ensure_analysis_tables(conn)
    conn.execute(
        """
        INSERT INTO post_ai_analyses (
            id, client_id, post_id, provider, model, prompt_version, status,
            started_at, finished_at, insight_text, action_text, rating_text,
            raw_response_json, usage_json, input_snapshot_json, error_text, cost_known
        ) VALUES (
            2, 1, 3, 'Anthropic Claude', 'claude-test', 'maaike-performance-analyse-v2',
            'completed', '2026-11-03T00:00:00+00:00', '2026-11-03T00:01:00+00:00',
            'claude insight', 'claude action', 'Gemiddeld', '{}', '{}', '{}', '', 0
        )
        """
    )
    conn.commit()
    posts = attach_assessments_and_ai(conn, 1, [{"post_id": 3}])
    assert posts[0]["ai_analysis"]["source"] == "post_ai_analyses"
    assert posts[0]["ai_analysis"]["id"] == 2
    assert posts[0]["ai_analysis"]["status"] == "completed"
    assert posts[0]["ai_trial_analysis"]["source"] == "ai_trial_posts"
    summary = summarize_attached_ai_analyses(posts)
    assert summary["ai_analysis_executed"] is True
    assert summary["completed_analysis_ids"] == [2]
    conn.close()
