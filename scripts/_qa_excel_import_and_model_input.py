"""QA-only: Excel preview + label diffs + model-input checklist. No live reimport, no paid AI."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from openpyxl import load_workbook

from maaike.db import transaction
from maaike.excel_import import build_preview, parse_workbook
from maaike.migrate import apply_migrations
from maaike.report_execute import build_execute_model_input, model_input_presence_checklist
from maaike.reports import inspect_client_report_data, prepare_client_report

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
XLSX = Path(r"c:\Users\SandrinePrumpelerRed\Downloads\RRO_Social strategie overzicht_2026.xlsx")
LIVE_DB = ROOT / "data" / "maaike_redrock.db"
QA_DB = ROOT / "data" / "maaike_redrock_qa_excel_audit.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_qa_excel_model_input.json"


def _label_diff_investigation(xlsx: Path, qa_db: Path) -> dict:
    """Compare cached Excel labels vs QA DB excel_imported assessments (read-only on live)."""
    wb = load_workbook(xlsx, data_only=True)
    ws = wb["Post performance"]
    headers = {str(ws.cell(1, c).value or "").strip(): c for c in range(1, ws.max_column + 1)}
    excel_by_url = {}
    for r in range(2, ws.max_row + 1):
        url = ws.cell(r, headers["Post: URL van post"]).value
        if not url:
            continue
        key = str(url).strip().split("?")[0].rstrip("/").lower()
        excel_by_url[key] = {
            "row": r,
            "beoordeling": ws.cell(r, headers["Beoordeling"]).value,
            "score": ws.cell(r, headers["Score"]).value if "Score" in headers else None,
        }

    conn = sqlite3.connect(qa_db)
    conn.row_factory = sqlite3.Row
    # Investigate Red Rock rows inside the isolated QA DB copy (not the live file).
    qa = conn.execute(
        "SELECT id, name FROM clients WHERE name = 'Red Rock' COLLATE NOCASE"
    ).fetchone()
    if qa is None:
        conn.close()
        return {"error": "Red Rock ontbreekt in QA-kopie"}
    rows = conn.execute(
        """
        SELECT p.id, p.permalink, a.rating_text, a.score_value, a.rating_origin
        FROM posts p
        LEFT JOIN post_assessments a ON a.post_id = p.id AND a.source = 'excel_imported'
        WHERE p.client_id = ? AND p.permalink IS NOT NULL
        """,
        (qa["id"],),
    ).fetchall()
    diffs = []
    matched = 0
    formula_text_in_db = 0
    for row in rows:
        key = str(row["permalink"] or "").strip().split("?")[0].rstrip("/").lower()
        ex = excel_by_url.get(key)
        if not ex:
            # also try without host case / trailing
            continue
        matched += 1
        excel_label = ex["beoordeling"]
        db_label = row["rating_text"]
        if db_label and ("ArrayFormula" in str(db_label) or str(db_label).startswith("=")):
            formula_text_in_db += 1
        if (excel_label or None) != (db_label or None) and excel_label:
            diffs.append(
                {
                    "post_id": row["id"],
                    "excel_row": ex["row"],
                    "excel_label": excel_label,
                    "db_label": db_label,
                    "excel_score": ex["score"],
                    "db_score": row["score_value"],
                    "db_rating_origin": row["rating_origin"],
                }
            )
    conn.close()
    return {
        "qa_client_id": qa["id"],
        "qa_client_name": qa["name"],
        "matched_url_rows": matched,
        "label_diff_count": len(diffs),
        "formula_text_still_in_db": formula_text_in_db,
        "label_diffs": diffs[:30],
        "note": (
            "Labelafwijkingen Excel-cache vs bestaande excel_imported-rijen op QA-kopie. "
            "Geen live herimport; importpreview toont assessment_diffs. "
            "update_assessments=true zou labels/scores bijwerken met behoud van insights/acties."
        ),
    }


def main() -> None:
    if not XLSX.exists():
        raise SystemExit(f"Excel ontbreekt: {XLSX}")
    if not LIVE_DB.exists():
        raise SystemExit(f"Live DB ontbreekt: {LIVE_DB}")

    # Isolated QA copy — never touch live DB writes
    if QA_DB.exists():
        QA_DB.unlink()
    shutil.copy2(LIVE_DB, QA_DB)

    with transaction(QA_DB) as conn:
        apply_migrations(conn)
        parsed = parse_workbook(XLSX)
        # Use Red Rock id from copy for preview (client-scoped); do NOT execute_import
        rr = conn.execute(
            "SELECT id FROM clients WHERE name = 'Red Rock' COLLATE NOCASE"
        ).fetchone()
        if rr is None:
            raise SystemExit("Red Rock ontbreekt in QA-kopie")
        client_id = int(rr["id"])
        preview = build_preview(conn, client_id, parsed)

        # Sync analysis context only (strategy fields) — no post reimport
        from maaike.excel_analysis_context import store_analysis_context_for_client

        store_analysis_context_for_client(
            conn, client_id, parsed["analysis_context"], source_file=XLSX.name
        )

        inspect = inspect_client_report_data(
            conn, client_id, period_year=2026, period_month=3
        )
        prepared = prepare_client_report(
            conn,
            client_id,
            period_year=2026,
            period_month=3,
            allow_partial_without_trend=True,
        )
        snap = prepared["report"]["input_snapshot"]
        model = build_execute_model_input(prepared["report"], snap)
        checklist = model_input_presence_checklist(model)

        # Client isolation check: QA Controle must not receive Red Rock strategy keys
        qa_client = conn.execute(
            "SELECT id FROM clients WHERE name LIKE 'QA%' ORDER BY id LIMIT 1"
        ).fetchone()
        isolation = {"checked": False}
        if qa_client and int(qa_client["id"]) != client_id:
            other = inspect_client_report_data(
                conn, int(qa_client["id"]), period_year=2026, period_month=3
            )
            isolation = {
                "checked": True,
                "other_client_id": int(qa_client["id"]),
                "other_has_redrock_feedback_tov": bool(
                    ((other.get("prompt_input") or {}).get("analysis_context") or {})
                    .get("feedback_tov", {})
                    .get("present")
                ),
                "redrock_feedback_present": bool(
                    ((inspect.get("prompt_input") or {}).get("analysis_context") or {})
                    .get("feedback_tov", {})
                    .get("present")
                ),
            }

        rating = conn.execute(
            "SELECT active, is_provisional, profile_name FROM client_rating_settings WHERE client_id = ?",
            (client_id,),
        ).fetchone()

    label_inv = _label_diff_investigation(XLSX, QA_DB)

    out = {
        "qa_db": str(QA_DB),
        "live_db_untouched": str(LIVE_DB),
        "no_live_reimport": True,
        "no_paid_ai": True,
        "excel_preview": {
            "row_count": preview["row_count"],
            "counts": preview["counts"],
            "assessment_diff_count": preview.get("assessment_diff_count"),
            "missing_cached_formula_outcomes": preview.get("missing_cached_formula_outcomes"),
            "rating_formula_live": preview.get("rating_formula_live"),
            "assessment_diffs_sample": (preview.get("assessment_diffs") or [])[:10],
            "analysis_context_summary": preview.get("analysis_context_summary"),
        },
        "label_investigation": label_inv,
        "rating_settings": dict(rating) if rating else None,
        "inspect_available": inspect.get("available"),
        "inspect_missing": inspect.get("missing"),
        "model_input_checklist": checklist,
        "model_input_keys": sorted(model.keys()),
        "analysis_period": model.get("analysis_period"),
        "planning_period": model.get("planning_period"),
        "isolation": isolation,
        "api_endpoints": {
            "excel_preview": "POST /api/clients/{id}/excel/preview",
            "execution_preview": "GET /api/clients/{id}/reports/{report_id}/execution-preview",
            "model_input_preview": "GET /api/clients/{id}/reports/{report_id}/model-input-preview",
            "inspect": "GET /api/clients/{id}/reports/inspect (of bestaande inspect-route)",
        },
        "prepared_report_id": prepared["report"]["id"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in out if k not in {"excel_preview"}}, indent=2, default=str)[:4000])
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
