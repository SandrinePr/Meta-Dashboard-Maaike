"""Edit insight/action for analysis #11, reload, verify report attach + report #20 PDF."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.db import transaction
from maaike.post_analysis_workflow import analysis_panel, save_reviewed_insight
from maaike.reports import get_report, inspect_client_report_data

EDITED_INSIGHT = (
    "QA-review t.o.v. beeld: donkere showroom/eetkamer (houten tafel, designstoelen, mobiel aan plafond) "
    "met overlay ‘Dit zijn de marketingfouten die wij direct zien / Lees de caption’. "
    "AI noemde ten onrechte bank/planten; wel terecht dat de hook in beeld+caption zit en interactie laag is. "
    "Statische single image stuurt naar de caption."
)
EDITED_ACTION = (
    "QA-review: Behoud sterke tekst-overlay + premium interieurbeeld; test of een carrousel "
    "(fouten als slides) of reel meer comments/saves oplevert dan één stilstaand frame."
)

out: dict = {"analysis_id": 11, "post_id": 31}

with transaction() as conn:
    before = conn.execute(
        "SELECT insight_text, action_text, status, actual_cost_usd, cost_known FROM post_ai_analyses WHERE id=11"
    ).fetchone()
    out["before"] = dict(before)

    saved = save_reviewed_insight(
        conn,
        1,
        31,
        {
            "insight_text": EDITED_INSIGHT,
            "action_text": EDITED_ACTION,
            "rating_text": "Gemiddeld",
            "source_analysis_id": 11,
            "provider": "Specialist reviewed after Gemini",
            "model": "gemini-3.5-flash-lite",
        },
    )
    out["saved_status"] = saved["analysis"]["status"]
    out["saved_insight"] = saved["analysis"]["insight_text"]
    out["saved_action"] = saved["analysis"]["action_text"]

    panel = analysis_panel(conn, 1, 31)
    out["reload_draft"] = panel.get("draft")
    out["reload_matches_edit"] = (
        (panel.get("draft") or {}).get("insight_text") == EDITED_INSIGHT
        and (panel.get("draft") or {}).get("action_text") == EDITED_ACTION
    )

    # Post 31 published 2025-09-ish? Check — attach via period that includes it
    pub = conn.execute("SELECT published_at FROM posts WHERE id=31").fetchone()["published_at"]
    out["published_at"] = pub
    year = int(str(pub)[:4])
    month = int(str(pub)[5:7])
    preview = inspect_client_report_data(conn, 1, period_year=year, period_month=month)
    hit = next((p for p in (preview.get("posts") or []) if p.get("post_id") == 31), None)
    ai = (hit or {}).get("ai_analysis") or {}
    out["report_period"] = f"{year}-{month:02d}"
    out["report_attach"] = {
        "found_post": hit is not None,
        "ai_id": ai.get("id"),
        "ai_source": ai.get("source"),
        "insight_prefix": (ai.get("insight_text") or "")[:80],
        "matches_edited": (ai.get("insight_text") or "") == EDITED_INSIGHT,
        "completed_ids": (preview.get("prompt_input") or {})
        .get("post_data", {})
        .get("attached_ai_analyses", {})
        .get("analysis_ids"),
    }

    # Report #20 PDF check
    report20 = get_report(conn, 1, 20)
    rep = report20.get("report") or report20
    body = rep.get("body") or {}
    pdf_path = rep.get("pdf_path") or rep.get("approved_pdf_path")
    # try common fields
    out["report_20"] = {
        "id": rep.get("id") or 20,
        "status": rep.get("status"),
        "approval_status": rep.get("approval_status") or rep.get("review_status"),
        "pdf_path": pdf_path or rep.get("pdf_file") or rep.get("final_pdf_path"),
        "has_six_answers": bool(body.get("six_answers")),
        "keys": sorted([k for k in rep.keys()])[:40],
    }
    # Find pdf on disk if path stored elsewhere
    for key in ("pdf_path", "approved_pdf_path", "final_pdf_path", "pdf_file"):
        if rep.get(key):
            out["report_20"]["pdf_path"] = rep.get(key)
            break
    row20 = conn.execute("SELECT * FROM client_reports WHERE id=20").fetchone()
    if row20:
        cols = row20.keys()
        out["report_20"]["db"] = {
            c: row20[c]
            for c in cols
            if c
            in {
                "id",
                "status",
                "approval_status",
                "pdf_path",
                "approved_pdf_path",
                "period_year",
                "period_month",
                "model",
            }
            or "pdf" in c
            or "approv" in c
        }

Path("data/imports/redrock/_qa_post31_review_and_report.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(json.dumps(out, indent=2, ensure_ascii=False))
