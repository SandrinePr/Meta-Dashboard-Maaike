"""Exercise pencil-edit / approve flow on QA report #10. Leaves Red Rock #9 alone."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.client_report_pdf import render_client_report_pdf
from maaike.db import connect
from maaike.report_review import save_report_review
from maaike.reports import get_report

QA_CLIENT = 4
QA_REPORT = 10
RR_REPORT = 9


def main() -> None:
    conn = connect()
    try:
        rr_before = get_report(conn, 1, RR_REPORT)
        rr_final_before = (rr_before.get("review") or {}).get("final_version_text") or ""
        rr_items_before = json.dumps(
            (rr_before.get("review") or {}).get("item_feedback") or [], ensure_ascii=False
        )

        detail = get_report(conn, QA_CLIENT, QA_REPORT)
        assert detail["report"]["client_id"] == QA_CLIENT
        items = detail["review"]["item_feedback"]
        assert items, "expected seeded review items"

        # 1) Feedback only on first analysis item
        target = next(i for i in items if i["key"].startswith("six_answers."))
        target["feedback"] = "QA feedback-only note — keep AI text."
        # leave edited_text empty / unchanged
        target["edited_text"] = ""
        saved = save_report_review(
            conn,
            QA_CLIENT,
            QA_REPORT,
            {
                "reviewer_name": "QA Tester",
                "item_feedback": items,
                "compose_final_from_items": True,
            },
        )
        reloaded = get_report(conn, QA_CLIENT, QA_REPORT)
        fb_item = next(i for i in reloaded["review"]["item_feedback"] if i["key"] == target["key"])
        assert "QA feedback-only" in (fb_item.get("feedback") or "")
        assert not (fb_item.get("edited_text") or "").strip()
        print("OK feedback-only save + reload")

        # 2) Text edit
        fb_item["edited_text"] = "QA aangepaste concepttekst voor dit onderdeel."
        fb_item["edited_by"] = "QA Tester"
        edited = save_report_review(
            conn,
            QA_CLIENT,
            QA_REPORT,
            {
                "reviewer_name": "QA Tester",
                "item_feedback": reloaded["review"]["item_feedback"],
                "compose_final_from_items": True,
            },
        )
        assert "QA aangepaste concepttekst" in edited["review"]["final_version_text"]
        section = next(
            s
            for s in (edited.get("presentation") or {}).get("document_sections") or []
            if s["review_key"] == target["key"]
        )
        assert section["is_edited"] is True
        assert "QA aangepaste" in section["text"]
        print("OK text edit in concept")

        pdf_bytes, presentation = render_client_report_pdf(conn, QA_CLIENT, QA_REPORT)
        assert presentation["content_source"] == "ai_concept"
        assert b"%PDF" in pdf_bytes[:8]
        out = Path("data/report_pdfs/qa-report-10-draft.pdf")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(pdf_bytes)
        print(f"OK draft PDF -> {out} ({len(pdf_bytes)} bytes)")

        # 3) Approve
        approved = save_report_review(
            conn,
            QA_CLIENT,
            QA_REPORT,
            {
                "reviewer_name": "QA Tester",
                "item_feedback": edited["review"]["item_feedback"],
                "compose_final_from_items": True,
                "approve": True,
            },
        )
        assert approved["review"]["is_approved"] is True
        assert "QA aangepaste concepttekst" in approved["review"]["final_version_text"]
        pdf2, pres2 = render_client_report_pdf(conn, QA_CLIENT, QA_REPORT)
        assert pres2["content_source"] == "approved_final"
        assert "QA aangepaste concepttekst" in (pres2.get("approved_final_text") or "")
        out2 = Path("data/report_pdfs/qa-report-10-approved.pdf")
        out2.write_bytes(pdf2)
        print(f"OK approved PDF -> {out2}")

        # 4) Edit again -> back to concept, previous approval kept
        items2 = approved["review"]["item_feedback"]
        again = next(i for i in items2 if i["key"] == target["key"])
        again["edited_text"] = "QA herzien na goedkeuring — terug naar concept."
        reopened = save_report_review(
            conn,
            QA_CLIENT,
            QA_REPORT,
            {
                "reviewer_name": "QA Tester",
                "item_feedback": items2,
                "compose_final_from_items": True,
            },
        )
        assert reopened["review"]["is_approved"] is False
        prev = reopened["review"].get("previous_approved") or []
        assert prev, "expected archived previous approval"
        assert "QA aangepaste concepttekst" in (prev[-1].get("final_version_text") or "")
        print(f"OK reopen after edit; previous_approved={len(prev)}")

        # Red Rock #9 must stay clean of QA strings
        rr_after = get_report(conn, 1, RR_REPORT)
        rr_final_after = (rr_after.get("review") or {}).get("final_version_text") or ""
        rr_items_after = json.dumps(
            (rr_after.get("review") or {}).get("item_feedback") or [], ensure_ascii=False
        )
        assert rr_final_after == rr_final_before
        assert rr_items_after == rr_items_before
        blob = rr_final_after + rr_items_after + (rr_after["report"].get("title") or "")
        assert "QA feedback-only" not in blob
        assert "QA aangepaste" not in blob
        assert "QA herzien" not in blob
        print("OK Red Rock #9 untouched")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
