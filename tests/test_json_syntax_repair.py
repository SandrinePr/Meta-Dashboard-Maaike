"""LOCAL_TEST: mechanical JSON repair + recovery from report #8 — no paid AI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maaike.db import connect
from maaike.json_syntax_repair import repair_unambiguous_json_syntax
from maaike.report_json_schema import client_report_response_schema, structured_output_capability
from maaike.reports import recover_client_report_json_syntax

REPO = Path(__file__).resolve().parents[1]
LIVE_DB = REPO / "data" / "maaike_redrock.db"


def test_repair_single_missing_open_quote():
    raw = '```json\n{\n  "a": 1,\n  b": 2\n}\n```'
    result = repair_unambiguous_json_syntax(raw)
    assert result["ok"] is True
    assert result["parsed"] == {"a": 1, "b": 2}
    assert len(result["edits"]) == 1
    assert result["edits"][0]["key"] == "b"
    assert result["edits"][0]["type"] == "insert_opening_quote_before_property_name"


def test_repair_stops_when_still_invalid_after_quotes():
    raw = '{ "a": 1, b": 2, '  # truncated
    result = repair_unambiguous_json_syntax(raw)
    assert result["ok"] is False
    assert "stop" in (result["error"] or "").lower() or "ongeldige" in (result["error"] or "").lower()


def test_structured_json_capability_and_schema():
    assert structured_output_capability(enable_google_search=True)["supported"] is False
    assert structured_output_capability(enable_google_search=False)["supported"] is True
    schema = client_report_response_schema()
    assert "six_answers" in schema["properties"]
    assert "chapters" in schema["properties"]
    assert "action_plan" in schema["properties"]


def test_recover_report_8_from_live_db():
    if not LIVE_DB.exists():
        pytest.skip("maaike_redrock.db missing")
    conn = connect(LIVE_DB)
    try:
        row = conn.execute(
            "SELECT id, status, body_json FROM client_reports WHERE id = 8 AND client_id = 1"
        ).fetchone()
        if row is None:
            pytest.skip("report #8 missing")
        body8 = json.loads(row["body_json"] or "{}")
        raw = body8.get("raw_response") or ""
        assert "unassessable" in raw

        existing = conn.execute(
            """
            SELECT id FROM client_reports
            WHERE client_id = 1 AND supersedes_id = 8
              AND title LIKE '%JSON-syntaxherstel%'
            ORDER BY id ASC LIMIT 1
            """
        ).fetchone()
        before8 = conn.execute(
            "SELECT updated_at, body_json FROM client_reports WHERE id = 8"
        ).fetchone()
        if existing:
            from maaike.reports import get_report

            recovered = get_report(conn, 1, int(existing["id"]))
        else:
            recovered = recover_client_report_json_syntax(conn, 1, 8)
        report = recovered["report"]
        after8 = conn.execute(
            "SELECT updated_at, body_json FROM client_reports WHERE id = 8"
        ).fetchone()
        assert after8["updated_at"] == before8["updated_at"]
        assert after8["body_json"] == before8["body_json"]

        assert report["id"] != 8
        assert report["supersedes_id"] == 8
        body = report["body"]
        assert body["raw_response"] == raw
        assert body["json_syntax_recovery"]["source_report_id"] == 8
        assert body["json_syntax_recovery"]["content_rewritten"] is False
        assert body["json_syntax_recovery"]["auto_approved"] is False
        assert body["requires_human_approval"] is True
        assert body["partial"] is True
        edits = body["json_syntax_recovery"]["edits"]
        assert len(edits) == 1
        assert edits[0]["key"] == "unassessable"
        assert body.get("six_answers", {}).get("beter")
        assert "Niet onderzocht" in (body.get("chapters") or {}).get("seo_serp", "")
        assert "Niet onderzocht" in (body.get("chapters") or {}).get("concurrenten", "")
        # Parse success ≠ approval
        assert report["status"] in {"completed", "failed"}
        if report["status"] == "completed":
            assert body.get("analysis_usable") is True
            warnings = (body.get("validation") or {}).get("warnings") or []
            assert any("goedkeuring" in str(w).lower() or "parse" in str(w).lower() for w in warnings)
    finally:
        conn.close()
