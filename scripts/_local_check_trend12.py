"""Local checks for prepared trend #12 — no paid AI."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.db import transaction
from maaike.report_execute import execute_report, execution_preview
from maaike.report_prompts import load_report_instruction_bundle
from maaike.reports import get_report

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
DB = ROOT / "data" / "maaike_redrock.db"


def main() -> None:
    bundle = load_report_instruction_bundle("trend")
    with transaction(DB) as conn:
        detail = get_report(conn, 1, 12)
        report = detail["report"]
        snap = report["input_snapshot"] or {}
        sources = snap.get("sources") or []
        preview = execution_preview(conn, 1, 12, max_budget_usd=2.0)

        dry_blocked = False
        dry_msg = ""
        try:
            execute_report(conn, 1, 12, max_budget_usd=2.0, dry_run_paid=True)
        except ValueError as exc:
            dry_blocked = True
            dry_msg = str(exc)

        # Client isolation
        other = conn.execute("SELECT id FROM clients WHERE id != 1 LIMIT 1").fetchone()
        iso_ok = True
        if other:
            try:
                get_report(conn, int(other["id"]), 12)
                iso_ok = False
            except ValueError:
                iso_ok = True

        r11 = conn.execute(
            "SELECT linked_trend_report_id, status, period_year, period_month, planning_year, planning_month FROM client_reports WHERE id = 11"
        ).fetchone()

        # Existing reports unchanged statuses sample
        statuses = conn.execute(
            "SELECT id, report_type, status FROM client_reports WHERE id IN (9,10,11) ORDER BY id"
        ).fetchall()

        out = {
            "trend12_status": report["status"],
            "is_mock": report.get("is_mock"),
            "period": snap.get("period"),
            "research_mode": snap.get("research_mode"),
            "sources_read": sum(1 for s in sources if s.get("counted_as_read_source")),
            "sources_total": len(sources),
            "instructions_loaded": {
                "primary": bundle["primary_loaded"],
                "system_chars": bundle["system_chars"],
                "supporting": {k: v.get("loaded") for k, v in bundle["supporting_files"].items()},
                "missing": bundle["missing_instructions"],
                "style_notes_has_trend_radar": "Social Trend Radar" in (bundle["system_text"] or ""),
            },
            "preview_paid_call": preview.get("paid_call"),
            "preview_within_budget": preview.get("within_budget"),
            "estimate_high_usd": (preview.get("estimate") or {}).get("combined_high_usd"),
            "dry_run_blocked": dry_blocked,
            "dry_run_message": dry_msg[:240],
            "client_isolation_ok": iso_ok,
            "r11": dict(r11) if r11 else None,
            "existing_reports_sample": [dict(r) for r in statuses],
            "prompt_user_keys": list((preview.get("model_input") or {}).keys()),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
