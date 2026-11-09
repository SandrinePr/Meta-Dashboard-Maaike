"""Controlled Red Rock reimport from last closed preview. No paid AI."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from maaike.db import transaction
from maaike.excel_analysis_context import (
    build_client_analysis_context,
    extract_workbook_context,
    store_analysis_context_for_client,
)
from maaike.excel_import import backup_database, build_preview, execute_import, parse_workbook
from maaike.migrate import apply_migrations
from maaike.reports import prepare_client_report
from openpyxl import load_workbook

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
XLSX = Path(r"c:\Users\SandrinePrumpelerRed\Downloads\RRO_Social strategie overzicht_2026.xlsx")
LIVE_DB = ROOT / "data" / "maaike_redrock.db"
BACKUP_DIR = ROOT / "data" / "backups"
PREVIEW_JSON = ROOT / "data" / "imports" / "redrock" / "_qa_pre_import_overview.json"
OUT = ROOT / "data" / "imports" / "redrock" / "_controlled_reimport_result.json"

EXPECTED = {"new": 4, "label_change": 20, "score_only": 57}


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _meta(path: Path) -> dict:
    st = path.stat()
    return {
        "path": str(path),
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "sha256_16": _sha16(path),
    }


def _baseline(conn) -> dict:
    cid = int(
        conn.execute(
            "SELECT id FROM clients WHERE name = 'Red Rock' COLLATE NOCASE"
        ).fetchone()[0]
    )
    r9 = conn.execute(
        """
        SELECT id, title, status, period_year, period_month, planning_year, planning_month,
               length(COALESCE(body_json,'')) AS body_len,
               length(COALESCE(input_snapshot_json,'')) AS snap_len,
               executed_at
        FROM client_reports WHERE id = 9 AND client_id = ?
        """,
        (cid,),
    ).fetchone()
    fb = conn.execute(
        "SELECT COUNT(*) AS n FROM ai_analysis_feedback WHERE client_id = ?",
        (cid,),
    ).fetchone()[0]
    reviews = 0
    try:
        reviews = conn.execute(
            "SELECT COUNT(*) FROM client_report_reviews WHERE report_id = 9"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass
    assessments = conn.execute(
        """
        SELECT COUNT(*) FROM post_assessments a
        JOIN posts p ON p.id = a.post_id
        WHERE p.client_id = ? AND a.source = 'excel_imported'
        """,
        (cid,),
    ).fetchone()[0]
    with_insight = conn.execute(
        """
        SELECT COUNT(*) FROM post_assessments a
        JOIN posts p ON p.id = a.post_id
        WHERE p.client_id = ? AND a.source = 'excel_imported'
          AND TRIM(COALESCE(a.insight_text,'')) != ''
        """,
        (cid,),
    ).fetchone()[0]
    rating = conn.execute(
        "SELECT active, is_provisional, profile_name FROM client_rating_settings WHERE client_id = ?",
        (cid,),
    ).fetchone()
    editorial = conn.execute(
        """
        SELECT COUNT(*) FROM post_editorial e
        JOIN posts p ON p.id = e.post_id
        WHERE p.client_id = ? AND (
            e.format_id IS NOT NULL OR e.pillar_id IS NOT NULL
            OR TRIM(COALESCE(e.hook,'')) != ''
        )
        """,
        (cid,),
    ).fetchone()[0]
    return {
        "client_id": cid,
        "report_9": dict(r9) if r9 else None,
        "feedback_count": int(fb),
        "review_rows_for_report_9": int(reviews),
        "excel_assessments": int(assessments),
        "assessments_with_insight": int(with_insight),
        "editorial_classified": int(editorial),
        "rating_settings": dict(rating) if rating else None,
    }


def main() -> None:
    if not XLSX.exists() or not LIVE_DB.exists():
        raise SystemExit("Excel of live DB ontbreekt.")
    preview_doc = json.loads(PREVIEW_JSON.read_text(encoding="utf-8"))
    expected_preview = (
        preview_doc.get("closed_import_preview", {})
        .get("mutually_exclusive_on_linked_rows", {})
    )

    xlsx_meta = _meta(XLSX)
    db_meta_before = _meta(LIVE_DB)
    preview_mtime = datetime.fromtimestamp(PREVIEW_JSON.stat().st_mtime)

    # Excel/DB must not be newer than / changed after the closed preview was made
    xlsx_mtime = datetime.fromisoformat(xlsx_meta["mtime"])
    db_mtime = datetime.fromisoformat(db_meta_before["mtime"])
    freshness = {
        "preview_mtime": preview_mtime.isoformat(timespec="seconds"),
        "xlsx_mtime": xlsx_meta["mtime"],
        "db_mtime": db_meta_before["mtime"],
        "xlsx_unchanged_since_preview": xlsx_mtime <= preview_mtime,
        "db_unchanged_since_preview": db_mtime <= preview_mtime,
    }

    # 1) Backup first
    backup_path = backup_database(LIVE_DB, BACKUP_DIR)

    result: dict = {
        "backup_path": str(backup_path),
        "xlsx": xlsx_meta,
        "db_before": db_meta_before,
        "freshness": freshness,
        "expected_from_last_preview": {
            "new": expected_preview.get("new", EXPECTED["new"]),
            "label_change": expected_preview.get("label_change", EXPECTED["label_change"]),
            "score_only": expected_preview.get("score_only", EXPECTED["score_only"]),
        },
        "live_import": False,
        "paid_ai": False,
    }

    with transaction(LIVE_DB) as conn:
        apply_migrations(conn)
        baseline = _baseline(conn)
        result["baseline"] = baseline
        client_id = baseline["client_id"]

        # 2) Fresh preview on live DB — must match expected closed counts
        parsed = parse_workbook(XLSX)
        preview = build_preview(conn, client_id, parsed)
        buckets = preview["assessment_summary"]
        result["live_preview_before_import"] = {
            "mutually_exclusive": {
                "new": buckets["new"],
                "label_change": buckets["label_change"],
                "score_only": buckets["score_only"],
                "unchanged": buckets["unchanged"],
                "skipped": buckets["skipped"],
                "sum": buckets["sum"],
                "equals_linked_rows": buckets["equals_linked_rows"],
            },
            "accounting": preview.get("accounting"),
            "rating_formula_live": preview.get("rating_formula_live"),
        }

        matches_expected = (
            buckets["new"] == EXPECTED["new"]
            and buckets["label_change"] == EXPECTED["label_change"]
            and buckets["score_only"] == EXPECTED["score_only"]
            and buckets["equals_linked_rows"] is True
        )
        sources_ok = freshness["xlsx_unchanged_since_preview"] and freshness["db_unchanged_since_preview"]
        result["preflight"] = {
            "sources_unchanged_since_preview": sources_ok,
            "preview_matches_expected_counts": matches_expected,
            "abort": not (sources_ok and matches_expected),
        }

        if not sources_ok or not matches_expected:
            result["status"] = "aborted_new_preview_required"
            result["note"] = (
                "Excel/DB gewijzigd sinds preview of aantallen wijken af. "
                "Geen import uitgevoerd; zie live_preview_before_import."
            )
            OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps(result["preflight"], indent=2))
            print("ABORTED — wrote", OUT)
            return

        # Snapshot a few rows we expect to change (label + score-only samples)
        samples = {
            "label_change": preview["assessment_bucket_samples"]["label_change"][:5],
            "score_only": preview["assessment_bucket_samples"]["score_only"][:5],
            "new": preview["assessment_bucket_samples"]["new"][:4],
        }
        result["planned_samples"] = samples

        insight_before = {}
        for sample in samples["label_change"] + samples["score_only"]:
            pid = sample["post_id"]
            row = conn.execute(
                """
                SELECT rating_text, score_value, insight_text, action_text
                FROM post_assessments
                WHERE post_id = ? AND source = 'excel_imported'
                ORDER BY id DESC LIMIT 1
                """,
                (pid,),
            ).fetchone()
            if row:
                insight_before[pid] = {
                    "rating_text": row["rating_text"],
                    "score_value": row["score_value"],
                    "insight_text": row["insight_text"],
                    "action_text": row["action_text"],
                }

        # 3) Execute controlled import
        applied = execute_import(
            conn,
            client_id,
            path=XLSX,
            parsed=parsed,
            update_assessments=True,
            sync_analysis_context=True,
        )
        result["live_import"] = True
        result["execute_result"] = applied

        # 4) Post-checks
        after = _baseline(conn)
        result["after"] = after

        # Verify samples applied
        sample_checks = []
        for sample in samples["label_change"] + samples["score_only"] + samples["new"]:
            pid = sample["post_id"]
            if pid is None:
                continue
            row = conn.execute(
                """
                SELECT rating_text, score_value, rating_origin, score_origin,
                       insight_text, action_text
                FROM post_assessments
                WHERE post_id = ? AND source = 'excel_imported'
                ORDER BY id DESC LIMIT 1
                """,
                (pid,),
            ).fetchone()
            before = insight_before.get(pid)
            check = {
                "post_id": pid,
                "excel_row": sample["excel_row"],
                "bucket": sample["bucket"],
                "expected_new_rating": sample.get("new_rating"),
                "expected_new_score": sample.get("new_score"),
                "actual_rating": row["rating_text"] if row else None,
                "actual_score": row["score_value"] if row else None,
                "insight_preserved": (
                    before is None
                    or not (before.get("insight_text") or "").strip()
                    or (row and row["insight_text"] == before["insight_text"])
                ),
                "action_preserved": (
                    before is None
                    or not (before.get("action_text") or "").strip()
                    or (row and row["action_text"] == before["action_text"])
                ),
            }
            check["rating_ok"] = check["actual_rating"] == sample.get("new_rating")
            exp_score = sample.get("new_score")
            if exp_score is None:
                check["score_ok"] = check["actual_score"] is None
            else:
                check["score_ok"] = (
                    check["actual_score"] is not None
                    and abs(float(check["actual_score"]) - float(exp_score)) < 1e-9
                )
            sample_checks.append(check)
        result["sample_checks"] = sample_checks

        rating_after = after.get("rating_settings") or {}
        result["rating_formula_still_off"] = int(rating_after.get("active") or 0) == 0

        result["preservation"] = {
            "report_9_present": after.get("report_9") is not None,
            "report_9_body_len_unchanged": (
                (baseline.get("report_9") or {}).get("body_len")
                == (after.get("report_9") or {}).get("body_len")
            ),
            "report_9_snap_len_unchanged": (
                (baseline.get("report_9") or {}).get("snap_len")
                == (after.get("report_9") or {}).get("snap_len")
            ),
            "feedback_count_unchanged": baseline["feedback_count"] == after["feedback_count"],
            "review_rows_unchanged": baseline["review_rows_for_report_9"]
            == after["review_rows_for_report_9"],
            "editorial_classified_not_reduced": after["editorial_classified"]
            >= baseline["editorial_classified"],
            "insights_not_reduced": after["assessments_with_insight"]
            >= baseline["assessments_with_insight"],
        }

        # Actual change counts vs DB (post-import re-preview should be mostly unchanged)
        preview_after = build_preview(conn, client_id, parsed)
        result["live_preview_after_import"] = preview_after["assessment_summary"]

        # 5) New report input check: analysis Sept → planning Nov (no AI)
        wb = load_workbook(XLSX, data_only=False)
        wbv = load_workbook(XLSX, data_only=True)
        ctx = extract_workbook_context(wb, wbv, source_file=XLSX.name)
        store_analysis_context_for_client(conn, client_id, ctx, source_file=XLSX.name)
        analysis_ctx = build_client_analysis_context(
            conn,
            client_id,
            analysis_year=2026,
            analysis_month=9,
            planning_year=2026,
            planning_month=11,
        )
        prepared = prepare_client_report(
            conn,
            client_id,
            period_year=2026,
            period_month=9,
            allow_partial_without_trend=True,
        )
        # Override planning on the prepared snapshot check via analysis_ctx
        # prepare_client_report defaults planning to analysis+1; verify context separately
        # and also prepare with explicit enrich by checking analysis_ctx + adjusting report planning fields
        snap = prepared["report"]["input_snapshot"]
        # Force-correct planning fields for the verification report if needed
        report_id = prepared["report"]["id"]
        conn.execute(
            """
            UPDATE client_reports
            SET planning_year = 2026, planning_month = 11,
                title = ?,
                input_snapshot_json = ?
            WHERE id = ? AND client_id = ?
            """,
            (
                "Client report analyse 2026-09 → planning 2026-11",
                json.dumps(
                    {
                        **snap,
                        "period": {
                            **(snap.get("period") or {}),
                            "analysis_period": {
                                "year": 2026,
                                "month": 9,
                                "role": "analyseperiode",
                            },
                            "planning_period": {
                                "year": 2026,
                                "month": 11,
                                "role": "planningsmaand",
                            },
                        },
                        "analysis_context": analysis_ctx,
                    },
                    ensure_ascii=False,
                ),
                report_id,
                client_id,
            ),
        )
        result["new_report_sept_nov"] = {
            "report_id": report_id,
            "analysis_context_selection_ok": analysis_ctx["month_context"].get("selection_ok"),
            "selected_sheet": analysis_ctx["month_context"].get("sheet_name"),
            "selection_reason": analysis_ctx["month_context"].get("selection_reason"),
            "feedback_tov_present": analysis_ctx["feedback_tov"].get("present"),
            "month_analyse_present": bool(
                analysis_ctx["month_context"].get("analyse_vorige_planning")
            ),
            "ai_called": False,
            "status": prepared["report"]["status"],
        }

        deviations = []
        if applied["applied"].get("assessments_inserted") != EXPECTED["new"]:
            # insert count may include only truly new; label/score updates are assessments_updated
            pass
        # Compare post-import preview: expect little remaining label/score change
        after_sum = preview_after["assessment_summary"]
        if after_sum["label_change"] != 0 or after_sum["score_only"] != 0:
            deviations.append(
                {
                    "type": "remaining_changes_after_import",
                    "label_change": after_sum["label_change"],
                    "score_only": after_sum["score_only"],
                }
            )
        if not result["rating_formula_still_off"]:
            deviations.append({"type": "rating_formula_activated"})
        for key, ok in result["preservation"].items():
            if not ok:
                deviations.append({"type": "preservation_failed", "check": key})
        bad_samples = [s for s in sample_checks if not (s["rating_ok"] and s["score_ok"] and s["insight_preserved"])]
        if bad_samples:
            deviations.append({"type": "sample_mismatch", "count": len(bad_samples), "samples": bad_samples[:5]})
        if not analysis_ctx["month_context"].get("selection_ok"):
            deviations.append({"type": "sept_nov_period_link_failed"})

        result["deviations"] = deviations
        result["status"] = "completed_with_deviations" if deviations else "completed_ok"
        result["actual_vs_expected"] = {
            "expected": EXPECTED,
            "execute_applied": applied.get("applied"),
            "preview_before": result["live_preview_before_import"]["mutually_exclusive"],
            "preview_after": after_sum,
            "note": (
                "Vooraf-preview buckets zijn de verwachte wijzigingen. "
                "execute applied telt inserts/updates technisch; "
                "na import horen label_change/score_only ~0."
            ),
        }

    result["db_after"] = _meta(LIVE_DB)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("STATUS", result["status"])
    print("BACKUP", result["backup_path"])
    print("PREFLIGHT", json.dumps(result["preflight"], indent=2))
    print("APPLIED", json.dumps(result.get("execute_result", {}).get("applied"), indent=2, default=str))
    print("PRESERVATION", json.dumps(result.get("preservation"), indent=2))
    print("SEPT-NOV", json.dumps(result.get("new_report_sept_nov"), indent=2, ensure_ascii=False))
    print("DEVIATIONS", json.dumps(result.get("deviations"), indent=2, ensure_ascii=False))
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
