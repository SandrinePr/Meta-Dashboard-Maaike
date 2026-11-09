"""QA checks against maaike_redrock_qa_demo.db — no paid AI."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.db import connect, transaction
from maaike.figma_planning import suggest_post_matches, week_letter_for_date
from maaike.post_analysis_workflow import analysis_panel, prepare_post_analysis, save_reviewed_insight
from maaike.report_metrics import attach_assessments_and_ai, build_analysis_data_coverage, build_period_metrics
from maaike.reports import inspect_client_report_data

out: dict = {"db": os.environ["MAAIKE_DATABASE_PATH"], "paid_calls": False}

# Week B proof
out["week_b_nov3"] = week_letter_for_date(date(2026, 11, 3), year=2026, month=11)

with transaction() as conn:
    client = conn.execute("SELECT id, name, last_fetch_status, last_fetch_detail FROM clients WHERE id=1").fetchone()
    out["client"] = dict(client)

    # Figma B1 suggestions
    b1 = conn.execute(
        "SELECT id FROM figma_planning_items WHERE client_id=1 AND code='B1'"
    ).fetchone()
    if b1:
        suggestions = suggest_post_matches(conn, 1, int(b1["id"]), limit=5)
        out["figma_b1_suggestions"] = suggestions

    # Reel thumbnail-only style inventory (post 1 is reel)
    panel_reel = analysis_panel(conn, 1, 1)
    out["reel_panel_limitations"] = panel_reel["inventory"]["limitations"]
    out["reel_role"] = panel_reel["inventory"]["analysis_role"]
    out["reel_published_count"] = panel_reel["inventory"]["published_media"]["count"]

    # Image prepare + save (post 353) without download to keep fast/offline
    prep = prepare_post_analysis(conn, 1, 353, download_media=False)
    saved = save_reviewed_insight(
        conn,
        1,
        353,
        {
            "insight_text": "QA: beeldworkflow insight voor post 353 (prepare zonder paid call).",
            "action_text": "QA: herhaal sterke opening; test CTA in volgende planning.",
            "rating_text": "Gemiddeld",
            "source_analysis_id": prep["analysis_id"],
            "provider": "Specialist reviewed",
            "model": "manual-qa",
        },
    )
    out["saved_analysis"] = {
        "id": saved["analysis"]["id"],
        "post_id": 353,
        "status": saved["analysis"]["status"],
        "insight": saved["analysis"]["insight_text"][:80],
    }

    # Report attach for October (post 353 is Oct 22)
    preview = inspect_client_report_data(conn, 1, period_year=2026, period_month=10)
    posts = preview.get("posts") or []
    hit = next((p for p in posts if p.get("post_id") == 353), None)
    ai = (hit or {}).get("ai_analysis") or {}
    out["report_oct_post_353"] = {
        "found": hit is not None,
        "ai_source": ai.get("source"),
        "ai_id": ai.get("id"),
        "insight_prefix": (ai.get("insight_text") or "")[:60],
        "completed_ids": preview.get("attached_ai_analysis_ids") or preview.get("prompt_input", {})
        .get("post_data", {})
        .get("attached_ai_analyses", {})
        .get("analysis_ids"),
    }

    # Coverage card via report inspect (same path as UI)
    preview_sep = inspect_client_report_data(conn, 1, period_year=2026, period_month=9)
    coverage = preview_sep.get("data_coverage") or {}
    out["coverage_sep"] = {
        "posts_by_platform": coverage.get("posts_by_platform"),
        "coverage_label": coverage.get("coverage_label"),
        "linkedin_note": coverage.get("linkedin_note"),
        "fb_page_limit": (coverage.get("sync_mechanics") or {}).get("page_limit_facebook"),
        "reduce_retry": (coverage.get("sync_mechanics") or {}).get("facebook_reduce_data_retry"),
        "uncertain": (coverage.get("meta_sync") or {}).get("coverage_uncertain"),
    }

    from maaike.figma_planning import resolve_figma_token

    out["figma_token_configured"] = bool(resolve_figma_token().get("configured"))

Path("data/imports/redrock/_qa_verify_improvements.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(json.dumps(out, indent=2, ensure_ascii=False)[:4000])
