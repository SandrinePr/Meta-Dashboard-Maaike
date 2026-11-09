"""QA calm-document flow on a fresh clone of #9. Leaves Red Rock #9 alone."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.client_report_pdf import render_client_report_pdf
from maaike.client_report_view import default_review_attention_points
from maaike.db import connect
from maaike.report_review import save_report_review, warning_ack_key
from maaike.reports import get_report

def ack_all(conn, client_id: int, report_id: int, reviewer: str, items, existing_acks=None):
    detail = get_report(conn, client_id, report_id)
    body = detail["report"]["body"] or {}
    points = default_review_attention_points(body)
    acks = list(existing_acks or [])
    have = {a.get("key") for a in acks if isinstance(a, dict)}
    for p in points:
        key = warning_ack_key(p)
        if key in have:
            continue
        acks.append(
            {
                "key": key,
                "status": "accepted",
                "note": "QA: accepted for local verification without AI rewrite.",
                "kind": p.get("kind"),
                "location": p.get("location") or "",
                "by": reviewer,
            }
        )
    return save_report_review(
        conn,
        client_id,
        report_id,
        {
            "reviewer_name": reviewer,
            "item_feedback": items,
            "warning_acknowledgements": acks,
            "compose_final_from_items": True,
        },
    )


def main() -> None:
    # Expect a fresh QA clone already created by _qa_clone_report9.py
    conn = connect()
    try:
        qa = conn.execute("SELECT id FROM clients WHERE name LIKE 'QA%'").fetchone()["id"]
        row = conn.execute(
            """
            SELECT id FROM client_reports
            WHERE client_id = ? AND title LIKE '%QA COPY of #9%'
            ORDER BY id DESC LIMIT 1
            """,
            (qa,),
        ).fetchone()
        if row is None:
            raise SystemExit("No QA COPY of #9 found — run scripts/_qa_clone_report9.py first")
        rid = int(row["id"])
        print("QA report", rid)

        rr_before = get_report(conn, 1, 9)
        rr_blob_before = json.dumps(
            {
                "final": (rr_before.get("review") or {}).get("final_version_text"),
                "items": (rr_before.get("review") or {}).get("item_feedback"),
            },
            ensure_ascii=False,
        )

        detail = get_report(conn, qa, rid)
        assert detail["presentation"]["headline_metrics"]
        assert len(detail["presentation"]["headline_metrics"]) <= 4
        items = detail["review"]["item_feedback"]
        target = next(i for i in items if i["key"].startswith("six_answers."))

        # Feedback only
        target["feedback"] = "QA calm: feedback only"
        target["edited_text"] = ""
        saved = save_report_review(
            conn,
            qa,
            rid,
            {"reviewer_name": "QA Tester", "item_feedback": items, "compose_final_from_items": True},
        )
        fb = next(i for i in saved["review"]["item_feedback"] if i["key"] == target["key"])
        assert "feedback only" in fb["feedback"]
        assert not (fb.get("edited_text") or "").strip()
        print("OK feedback-only")

        # Text edit
        fb["edited_text"] = "QA calm: aangepaste tekst voor concept."
        edited = save_report_review(
            conn,
            qa,
            rid,
            {
                "reviewer_name": "QA Tester",
                "item_feedback": saved["review"]["item_feedback"],
                "compose_final_from_items": True,
            },
        )
        assert "QA calm: aangepaste" in edited["review"]["final_version_text"]
        pdf, pres = render_client_report_pdf(conn, qa, rid)
        assert pres["content_source"] == "ai_concept"
        Path("data/report_pdfs/qa-calm-draft.pdf").write_bytes(pdf)
        print("OK draft PDF")

        # Ack warnings then approve
        acked = ack_all(conn, qa, rid, "QA Tester", edited["review"]["item_feedback"])
        approved = save_report_review(
            conn,
            qa,
            rid,
            {
                "reviewer_name": "QA Tester",
                "item_feedback": acked["review"]["item_feedback"],
                "warning_acknowledgements": acked["review"]["warning_acknowledgements"],
                "compose_final_from_items": True,
                "approve": True,
            },
        )
        assert approved["review"]["is_approved"] is True
        pdf2, pres2 = render_client_report_pdf(conn, qa, rid)
        assert pres2["content_source"] == "approved_final"
        Path("data/report_pdfs/qa-calm-approved.pdf").write_bytes(pdf2)
        print("OK approved")

        # Reopen
        items2 = approved["review"]["item_feedback"]
        again = next(i for i in items2 if i["key"] == target["key"])
        again["edited_text"] = "QA calm: na goedkeuring opnieuw concept."
        reopened = save_report_review(
            conn,
            qa,
            rid,
            {
                "reviewer_name": "QA Tester",
                "item_feedback": items2,
                "warning_acknowledgements": approved["review"]["warning_acknowledgements"],
                "compose_final_from_items": True,
            },
        )
        assert reopened["review"]["is_approved"] is False
        assert reopened["review"]["previous_approved"]
        print("OK reopen + previous approval kept")

        rr_after = get_report(conn, 1, 9)
        rr_blob_after = json.dumps(
            {
                "final": (rr_after.get("review") or {}).get("final_version_text"),
                "items": (rr_after.get("review") or {}).get("item_feedback"),
            },
            ensure_ascii=False,
        )
        assert rr_blob_before == rr_blob_after
        assert "QA calm" not in rr_blob_after
        print("OK Red Rock #9 clean")
        conn.commit()
        print(json.dumps({"qa_client_id": qa, "qa_report_id": rid}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
