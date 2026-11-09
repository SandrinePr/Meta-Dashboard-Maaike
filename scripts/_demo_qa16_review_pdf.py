"""Exercise review → approve → PDF on QA report #16. Uses QA DB only."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.client_report_pdf import render_client_report_pdf
from maaike.client_report_view import default_review_attention_points
from maaike.db import connect, transaction
from maaike.migrate import apply_migrations
from maaike.report_review import ensure_report_review_tables, save_report_review, warning_ack_key
from maaike.reports import get_report

ROOT = Path(__file__).resolve().parents[1]
QA_DB = ROOT / "data" / "maaike_redrock_qa_demo.db"
LIVE = ROOT / "data" / "maaike_redrock.db"
PDF_DIR = ROOT / "data" / "report_pdfs"
OUT = ROOT / "data" / "imports" / "redrock" / "_demo_qa16_review_pdf.json"
REPORT_ID = 16
CLIENT_ID = 1
MARKER = "QA DEMO approved text — pencil edit Nov 2026"


def main() -> None:
    assert QA_DB.exists()
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    # Live must still show #11 prepared empty and no #16
    live = connect(LIVE)
    apply_migrations(live)
    live11 = live.execute(
        "SELECT status, length(body_json) AS bl FROM client_reports WHERE id = 11"
    ).fetchone()
    live16 = live.execute("SELECT id FROM client_reports WHERE id = 16").fetchone()
    assert live11["status"] == "prepared" and int(live11["bl"] or 0) <= 2
    assert live16 is None
    live.close()

    with transaction(QA_DB) as conn:
        apply_migrations(conn)
        ensure_report_review_tables(conn)
        detail = get_report(conn, CLIENT_ID, REPORT_ID)
        assert detail["report"]["status"] in {"mock_completed", "completed"}
        items = list(detail["review"]["item_feedback"] or [])
        assert items, "expected review items from mock body"
        target = next(
            (i for i in items if str(i.get("key") or "").startswith("six_answers.")),
            items[0],
        )
        target["feedback"] = "Internal QA feedback — must stay out of client PDF."
        target["edited_text"] = MARKER

        saved = save_report_review(
            conn,
            CLIENT_ID,
            REPORT_ID,
            {
                "reviewer_name": "QA Demo",
                "item_feedback": items,
                "compose_final_from_items": True,
            },
        )
        assert MARKER in (saved["review"].get("final_version_text") or "")

        # Draft PDF before approve — concept source
        draft_pdf, draft_pres = render_client_report_pdf(conn, CLIENT_ID, REPORT_ID)
        draft_path = PDF_DIR / "qa-demo-16-draft.pdf"
        draft_path.write_bytes(draft_pdf)

        # Ack warnings
        points = default_review_attention_points(detail["report"]["body"] or {})
        acks = list(saved["review"].get("warning_acknowledgements") or [])
        have = {a.get("key") for a in acks if isinstance(a, dict)}
        for p in points:
            key = warning_ack_key(p)
            if key in have:
                continue
            acks.append(
                {
                    "key": key,
                    "status": "accepted",
                    "note": "QA demo ack",
                    "kind": p.get("kind"),
                    "location": p.get("location") or "",
                    "by": "QA Demo",
                }
            )
        acked = save_report_review(
            conn,
            CLIENT_ID,
            REPORT_ID,
            {
                "reviewer_name": "QA Demo",
                "item_feedback": saved["review"]["item_feedback"],
                "warning_acknowledgements": acks,
                "compose_final_from_items": True,
            },
        )
        approved = save_report_review(
            conn,
            CLIENT_ID,
            REPORT_ID,
            {
                "reviewer_name": "QA Demo",
                "item_feedback": acked["review"]["item_feedback"],
                "warning_acknowledgements": acked["review"].get("warning_acknowledgements") or acks,
                "approve": True,
                "compose_final_from_items": True,
            },
        )
        assert (approved["review"].get("review_status") or "").lower() in {
            "approved",
            "goedgekeurd",
        } or approved["review"].get("approved_at")

        final_pdf, final_pres = render_client_report_pdf(conn, CLIENT_ID, REPORT_ID)
        final_path = PDF_DIR / "qa-demo-16-approved.pdf"
        final_path.write_bytes(final_pdf)

        # Extract text via pymupdf if available
        pdf_text = ""
        try:
            import fitz

            doc = fitz.open(final_path)
            pdf_text = "\n".join(page.get_text() or "" for page in doc)
        except Exception as exc:
            pdf_text = f"(extract_failed: {exc})"

        feedback_leaked = "Internal QA feedback" in pdf_text
        marker_present = MARKER in pdf_text or "QA DEMO approved text" in pdf_text

        out = {
            "qa_report_id": REPORT_ID,
            "live_11_status": dict(live11),
            "live_has_16": False,
            "draft_pdf": str(draft_path),
            "draft_content_source": draft_pres.get("content_source"),
            "approved_pdf": str(final_path),
            "approved_content_source": final_pres.get("content_source"),
            "review_status": approved["review"].get("review_status"),
            "approved_at": approved["review"].get("approved_at"),
            "marker_in_final_text": MARKER in (approved["review"].get("final_version_text") or ""),
            "marker_in_pdf": marker_present,
            "internal_feedback_leaked_to_pdf": feedback_leaked,
            "pdf_text_chars": len(pdf_text),
            "pdf_text_sample": pdf_text[:800],
            "ok": marker_present and not feedback_leaked,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        if not out["ok"]:
            raise SystemExit("PDF checks failed")


if __name__ == "__main__":
    main()
