"""Medewerkercontrole op rapporten: AI → feedback → eindversie → Goedgekeurd (geen betaalde AI)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from maaike.db import initialize_database, transaction
from maaike.report_review import save_report_review
from maaike.reports import apply_mock_report, get_report, list_reports, prepare_client_report


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def test_report_review_route_versioning_and_isolation(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "review.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()

    with transaction() as conn:
        qa = conn.execute(
            "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('QA Controle', ?, ?, 'not_connected')",
            (_now(), _now()),
        ).lastrowid
        other = conn.execute(
            "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('Other Co', ?, ?, 'not_connected')",
            (_now(), _now()),
        ).lastrowid

        prepared = prepare_client_report(
            conn,
            qa,
            period_year=2026,
            period_month=9,
            allow_partial_without_trend=True,
            max_budget_usd=0.01,
        )
        rid = prepared["report"]["id"]
        assert prepared["report"]["status"] == "prepared"
        assert prepared["review"]["can_review"] is False
        assert prepared["review"]["is_approved"] is False
        assert "Approved" not in (prepared["review"]["review_status_label"] or "")

        try:
            save_report_review(conn, qa, rid, {"approve": True, "reviewer_name": "X"})
            raised = False
        except ValueError:
            raised = True
        assert raised, "prepare zonder AI mag niet goedgekeurd worden"

        listed = list_reports(conn, qa)
        row = next(r for r in listed["reports"] if r["id"] == rid)
        assert row["is_approved"] is False
        assert row["status"] == "prepared"

        mocked = apply_mock_report(conn, qa, rid)
        assert mocked["report"]["status"] == "mock_completed"
        assert mocked["report"]["body"]["label"].startswith("MOCK")
        assert mocked["review"]["can_review"] is True
        assert mocked["review"]["is_approved"] is False
        key1 = mocked["review"]["execution_key"]
        assert "QA" in json_label(mocked["report"]["body"]) or "MOCK" in mocked["report"]["body"]["label"]

        # Marked test content in item feedback
        items = mocked["review"]["item_feedback"]
        for item in items:
            if item["key"] == "six_answers.beter":
                item["decision"] = "accept"
            elif item["key"] == "six_answers.slechter":
                item["decision"] = "correct"
                item["human_text"] = "QA Controle — gecorrigeerd slechter-punt (test)."
            elif item["key"] == "six_answers.testen":
                item["decision"] = "reject"
            elif item["key"] == "addition.staff":
                item["decision"] = "add"
                item["human_text"] = "QA Controle — eigen aanvulling zonder Claude."

        draft = save_report_review(
            conn,
            qa,
            rid,
            {
                "reviewer_name": "QA Controle Medewerker",
                "item_feedback": items,
                "compose_final_from_items": True,
            },
        )
        assert draft["review"]["review_status"] == "final_draft"
        assert "QA Controle — gecorrigeerd" in draft["review"]["final_version_text"]
        assert draft["review"]["is_approved"] is False
        assert draft["review"]["execution_key"] == key1

        # Reload persists
        reloaded = get_report(conn, qa, rid)
        assert reloaded["review"]["final_version_text"] == draft["review"]["final_version_text"]
        assert reloaded["review"]["reviewer_name"] == "QA Controle Medewerker"
        assert reloaded["review"]["ai_original"]["label"].startswith("MOCK")

        approved = save_report_review(
            conn,
            qa,
            rid,
            {
                "reviewer_name": "QA Controle Medewerker",
                "item_feedback": items,
                "final_version_text": draft["review"]["final_version_text"],
                "approve": True,
            },
        )
        assert approved["review"]["is_approved"] is True
        assert approved["review"]["review_status"] == "approved"
        assert approved["review"]["review_status_label"] == "Approved"
        assert approved["review"]["record"]["approved_at"]

        listed2 = list_reports(conn, qa)
        row2 = next(r for r in listed2["reports"] if r["id"] == rid)
        assert row2["is_approved"] is True
        assert row2["review_status_label"] == "Approved"

        # Client isolation
        try:
            get_report(conn, other, rid)
            iso_ok = False
        except ValueError:
            iso_ok = True
        assert iso_ok
        try:
            save_report_review(conn, other, rid, {"reviewer_name": "Intruder", "approve": True})
            iso_save = False
        except ValueError:
            iso_save = True
        assert iso_save

        # New mock execution must not inherit approval (new execution_key)
        # Same report cannot re-mock if already executed — prepare new version.
        prepared2 = prepare_client_report(
            conn,
            qa,
            period_year=2026,
            period_month=9,
            allow_partial_without_trend=True,
            max_budget_usd=0.01,
        )
        rid2 = prepared2["report"]["id"]
        assert rid2 != rid
        mocked2 = apply_mock_report(conn, qa, rid2)
        key2 = mocked2["review"]["execution_key"]
        assert key2 != key1
        assert mocked2["review"]["is_approved"] is False
        assert mocked2["review"]["review_status"] in {"", "awaiting_review"}

        # Old approval still on original report/execution
        old = get_report(conn, qa, rid)
        assert old["review"]["is_approved"] is True
        assert old["review"]["execution_key"] == key1
        assert "QA Controle — eigen aanvulling" in old["review"]["final_version_text"]


def json_label(body: dict) -> str:
    return str(body.get("label") or "")
