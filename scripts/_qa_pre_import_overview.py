"""Sluitende pre-live-import preview. Geen live import, geen betaalde AI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from openpyxl import load_workbook

from maaike.db import transaction
from maaike.excel_analysis_context import (
    build_client_analysis_context,
    extract_workbook_context,
    store_analysis_context_for_client,
)
from maaike.excel_import import build_preview, parse_workbook
from maaike.migrate import apply_migrations

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
XLSX = Path(r"c:\Users\SandrinePrumpelerRed\Downloads\RRO_Social strategie overzicht_2026.xlsx")
LIVE_DB = ROOT / "data" / "maaike_redrock.db"
QA_DB = ROOT / "data" / "maaike_redrock_qa_excel_audit.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_qa_pre_import_overview.json"


def _period_check(conn, client_id: int, ctx: dict, *, ay: int, am: int, py: int, pm: int) -> dict:
    store_analysis_context_for_client(conn, client_id, ctx, source_file=XLSX.name)
    analysis_ctx = build_client_analysis_context(
        conn,
        client_id,
        analysis_year=ay,
        analysis_month=am,
        planning_year=py,
        planning_month=pm,
    )
    month = analysis_ctx["month_context"]
    return {
        "analysis_period": analysis_ctx["analysis_period"],
        "planning_period": analysis_ctx["planning_period"],
        "selected_month_sheet": month.get("sheet_name"),
        "selection_ok": month.get("selection_ok"),
        "selection_reason": month.get("selection_reason"),
        "analysis_month_label_on_sheet": month.get("analysis_month_label"),
        "planning_credit_month_label": month.get("planning_credit_month_label"),
        "period_link_source": month.get("period_link_source"),
        "sheet_analysis_ym": {
            "year": month.get("sheet_analysis_year"),
            "month": month.get("sheet_analysis_month"),
        },
        "client_label_on_sheet": month.get("client_label"),
        "has_analyse": bool(month.get("analyse_vorige_planning")),
        "has_bijzonderheden": bool(month.get("bijzonderheden")),
        "sheet_content_link": {
            "sheet_name": month.get("sheet_name"),
            "source": month.get("source"),
        },
    }


def main() -> None:
    if QA_DB.exists():
        QA_DB.unlink()
    shutil.copy2(LIVE_DB, QA_DB)

    wb = load_workbook(XLSX, data_only=False)
    wbv = load_workbook(XLSX, data_only=True)
    ctx = extract_workbook_context(wb, wbv, source_file=XLSX.name)
    sheet_index = [
        {
            "sheet_name": m.get("sheet_name"),
            "planning": f"{m.get('planning_year')}-{int(m.get('planning_month') or 0):02d}",
            "analysis_content_month": m.get("analysis_month_label"),
            "analysis_ym": (
                f"{m.get('analysis_year')}-{int(m.get('analysis_month') or 0):02d}"
                if m.get("analysis_month")
                else None
            ),
            "period_link_source": m.get("period_link_source"),
        }
        for m in ctx["month_sheets"]
    ]

    with transaction(QA_DB) as conn:
        apply_migrations(conn)
        rr = conn.execute(
            "SELECT id FROM clients WHERE name = 'Red Rock' COLLATE NOCASE"
        ).fetchone()
        client_id = int(rr["id"])

        # Primary check: actuele Excel-koppeling analyse september → planning november
        sept_nov = _period_check(
            conn, client_id, ctx, ay=2026, am=9, py=2026, pm=11
        )
        # Reference: earlier QA used maart→april (content on April sheet = Februari)
        mar_apr = _period_check(
            conn, client_id, ctx, ay=2026, am=3, py=2026, pm=4
        )

        parsed = parse_workbook(XLSX)
        preview = build_preview(conn, client_id, parsed)
        summary = preview["assessment_summary"]
        accounting = preview["accounting"]

        out = {
            "no_live_reimport": True,
            "no_paid_ai": True,
            "qa_db": str(QA_DB),
            "excel_month_sheet_index": sheet_index,
            "period_check_analysis_september_planning_november": sept_nov,
            "period_check_reference_march_april": mar_apr,
            "closed_import_preview": {
                "excel_rows_parsed": accounting["excel_rows_parsed"],
                "match_actions": accounting["match"],
                "linked_unique_posts": accounting["linked_posts_unique"],
                "mutually_exclusive_on_linked_rows": accounting[
                    "linked_assessment_buckets_mutually_exclusive"
                ],
                "missing_cached_formula_outcomes": accounting[
                    "missing_cached_formula_outcomes"
                ],
                "definitions": accounting["definitions"],
                "samples": {
                    "label_change": preview["assessment_bucket_samples"]["label_change"][:12],
                    "score_only": preview["assessment_bucket_samples"]["score_only"][:8],
                    "new": preview["assessment_bucket_samples"]["new"][:5],
                    "unchanged": preview["assessment_bucket_samples"]["unchanged"][:5],
                    "skipped": preview["assessment_bucket_samples"]["skipped"][:5],
                },
            },
            "identity_check": {
                "label_change_plus_score_only": (
                    summary["label_change"] + summary["score_only"]
                ),
                "equals_changed_alias": summary["changed"],
                "all_linked_buckets_sum": summary["sum"],
                "equals_linked_91": summary["equals_linked_rows"],
                "excel_rows_match_sum_ok": accounting["match"]["equals_excel_rows"],
            },
            "review_verdict": {
                "september_november_period_ok": bool(sept_nov.get("selection_ok")),
                "september_november_sheet": sept_nov.get("selected_month_sheet"),
                "counts_closed": bool(summary.get("equals_linked_rows"))
                and bool(accounting["match"]["equals_excel_rows"]),
                "wipe_protection": "ontbrekende cache wist geen bestaande geldige waarden",
                "live_import_executed": False,
                "required_for_assessment_updates": "update_assessments=true",
            },
        }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print("=== PERIODE: analyse september → planning november ===")
    print("Analyse:", sept_nov["analysis_period"])
    print("Planning:", sept_nov["planning_period"])
    print("Blad:", sept_nov["selected_month_sheet"], "| OK:", sept_nov["selection_ok"])
    print("Reden:", sept_nov["selection_reason"])
    print()
    print("=== SLUITENDE IMPORTPREVIEW ===")
    mx = accounting["linked_assessment_buckets_mutually_exclusive"]
    print("Excel-rijen:", accounting["excel_rows_parsed"])
    print("Match add/link/skip/conflict:", accounting["match"])
    print("Unieke gekoppelde posts:", accounting["linked_posts_unique"])
    print("Op gekoppelde rijen (wederzijds uitsluitend):")
    print(f"  nieuw:              {mx['new']}")
    print(f"  labelwijziging:     {mx['label_change']}")
    print(f"  uitsluitend score:  {mx['score_only']}")
    print(f"  ongewijzigd:        {mx['unchanged']}")
    print(f"  overgeslagen:       {mx['skipped']}")
    print(f"  som:                {mx['sum']} (equals linked={mx['equals_linked_rows']})")
    print("Missing cache:", accounting["missing_cached_formula_outcomes"])
    print()
    print("Identity:", out["identity_check"])
    print("Verdict:", json.dumps(out["review_verdict"], ensure_ascii=False))
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
