"""Isolated QA demo: copy DB, new version from #11 + optional #15 link, model-input check, mock body.

No paid AI. Does not modify live DB file after the initial copy.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "data" / "maaike_redrock.db"
QA_DB = ROOT / "data" / "maaike_redrock_qa_demo.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_demo_qa11_prep.json"
AUDIT = ROOT / "data" / "imports" / "redrock" / "_demo_trend15_audit.json"


def now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def main() -> None:
    from maaike.db import connect, transaction
    from maaike.migrate import apply_migrations
    from maaike.report_execute import (
        apply_execution_mock,
        build_execute_model_input,
        execution_preview,
        model_input_presence_checklist,
    )
    from maaike.reports import _trend_summary, ensure_report_tables, get_report
    from maaike.report_review import ensure_report_review_tables

    if not LIVE.exists():
        raise SystemExit(f"Live DB missing: {LIVE}")
    if QA_DB.exists():
        QA_DB.unlink()
    shutil.copy2(LIVE, QA_DB)

    audit = json.loads(AUDIT.read_text(encoding="utf-8")) if AUDIT.exists() else {}
    allow_link = bool(audit.get("allow_partial_link"))

    with transaction(QA_DB) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)
        ensure_report_review_tables(conn)

        # Prove live-equivalent rows present in copy only
        src = conn.execute("SELECT * FROM client_reports WHERE id = 11 AND client_id = 1").fetchone()
        assert src and src["report_type"] == "client" and src["status"] == "prepared"
        t15 = conn.execute("SELECT id, status, report_type FROM client_reports WHERE id = 15").fetchone()
        assert t15 and t15["report_type"] == "trend" and t15["status"] == "completed"

        snap = json.loads(src["input_snapshot_json"] or "{}")
        estimate = json.loads(src["estimate_json"] or "{}")
        notes = json.loads(src["notes_json"] or "[]")
        if not isinstance(notes, list):
            notes = []

        linked_trend = None
        linked_id = None
        if allow_link:
            linked_id = 15
            linked_trend = _trend_summary(conn, 1, 15)
            assert linked_trend and linked_trend.get("body_present")
            snap["linked_trend"] = linked_trend
            snap["partial"] = True
            snap["labels"] = {
                **(snap.get("labels") or {}),
                "qa_demo_from_report_11": True,
                "linked_trend_partial_concept": True,
                "trend_report_id": 15,
            }
            notes.append(
                "QA demo: gekoppeld aan trend #15 (partieel concept; human review; niet fully_researched)."
            )
        else:
            snap["linked_trend"] = None
            notes.append("QA demo: trend #15 niet gekoppeld (audit weigerde).")

        # Clone #11 → new prepared row (same client inside QA DB only)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(client_reports)").fetchall()]
        insert_cols = [c for c in cols if c != "id"]
        values = []
        ts = now()
        for c in insert_cols:
            if c == "title":
                values.append(
                    f"QA DEMO from #11 — analyse {src['period_year']}-{int(src['period_month']):02d} "
                    f"→ planning {src['planning_year']}-{int(src['planning_month']):02d}"
                    + (" + trend #15" if linked_id else "")
                )
            elif c == "status":
                values.append("prepared")
            elif c == "version":
                values.append(int(src["version"] or 1) + 100)  # clearly QA-offset
            elif c == "supersedes_id":
                values.append(11)
            elif c == "linked_trend_report_id":
                values.append(linked_id)
            elif c == "input_snapshot_json":
                values.append(json.dumps(snap, ensure_ascii=False))
            elif c == "estimate_json":
                values.append(json.dumps(estimate, ensure_ascii=False))
            elif c == "notes_json":
                values.append(json.dumps(notes, ensure_ascii=False))
            elif c == "body_json":
                values.append("{}")
            elif c == "usage_json":
                values.append("{}")
            elif c == "error_text":
                values.append("")
            elif c in {"executed_at"}:
                values.append(None)
            elif c in {"prepared_at", "created_at", "updated_at"}:
                values.append(ts)
            elif c == "is_mock":
                values.append(0)
            else:
                values.append(src[c])
        cur = conn.execute(
            f"INSERT INTO client_reports ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
            values,
        )
        new_id = int(cur.lastrowid)

        # Model-input / preview (no paid call)
        preview = execution_preview(conn, 1, new_id, max_budget_usd=0.05)
        report_payload = get_report(conn, 1, new_id)
        model_input = build_execute_model_input(report_payload["report"], snap)
        checklist = model_input_presence_checklist(model_input)

        period = (snap.get("period") or {})
        analysis = period.get("analysis_period") or {}
        planning = period.get("planning_period") or {}
        period_checks = {
            "analysis_september": analysis.get("month") == 9 and analysis.get("year") == 2026,
            "planning_november": planning.get("month") == 11 and planning.get("year") == 2026,
            "strategy_present": bool((model_input.get("strategy") or {}).get("start_answers") or (model_input.get("strategy") or {}).get("targets")),
            "targets_present": bool((model_input.get("strategy") or {}).get("targets")),
            "excel_or_feedback_context": bool(
                (model_input.get("analysis_context") or {}).get("feedback_tov")
                or (model_input.get("analysis_context") or {}).get("maandteksten")
            ),
            "post_analyses_or_metrics": bool(
                (model_input.get("metrics") or {}).get("post_count")
                or model_input.get("attached_ai_analysis_ids")
            ),
            "linked_trend_in_input": bool(model_input.get("linked_trend")),
        }

        estimate = preview.get("estimate") or estimate
        cost = {
            "combined_high_usd": estimate.get("combined_high_usd"),
            "estimated_cost_usd": estimate.get("estimated_cost_usd"),
            "exact_model": estimate.get("exact_model") or (estimate.get("rate") or {}).get("model"),
            "rate": estimate.get("rate"),
            "status": "estimate_only — paid execute NOT run; awaiting explicit approval for one attempt",
            "budget_gate_usd": 0.05,
            "within_0_05": (
                estimate.get("combined_high_usd") is not None
                and float(estimate["combined_high_usd"]) <= 0.05
            ),
        }

        # Mock concept so review→PDF chain can be exercised without paid AI
        mocked = apply_execution_mock(conn, 1, new_id, scenario="success_with_sources")
        mock_report = mocked["report"]
        assert mock_report["status"] == "mock_completed"
        body = mock_report.get("body") or {}
        body.update(
            {
                "qa_demo": True,
                "qa_from_report_11": True,
                "linked_trend_report_id": linked_id,
                "human_review_required": True,
                "partial": True,
                "label": "QA DEMO mock concept from #11 snapshot — not paid Gemini output",
                "not_approved": True,
            }
        )
        conn.execute(
            "UPDATE client_reports SET body_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(body, ensure_ascii=False), ts, new_id),
        )

        # Verify originals in QA copy still match expected (live file was only copied, not written)
        still11 = conn.execute(
            "SELECT status, length(body_json) AS bl, linked_trend_report_id FROM client_reports WHERE id = 11"
        ).fetchone()
        still15 = conn.execute(
            "SELECT status, model FROM client_reports WHERE id = 15"
        ).fetchone()

        out = {
            "qa_db": str(QA_DB),
            "live_db_untouched_after_copy": True,
            "new_report_id": new_id,
            "supersedes": 11,
            "linked_trend_id": linked_id,
            "allow_partial_link": allow_link,
            "period_checks": period_checks,
            "checklist": checklist,
            "cost_estimate_for_paid_attempt": cost,
            "paid_generation": "BLOCKED_PENDING_APPROVAL",
            "mock_status": mock_report["status"],
            "mock_usable": bool((body.get("validation") or {}).get("usable") or body.get("six_answers")),
            "report_11_in_qa_copy": dict(still11),
            "report_15_in_qa_copy": dict(still15),
            "click_path": [
                "Start API with MAAIKE_DATABASE_PATH=data/maaike_redrock_qa_demo.db",
                "Dashboard → Red Rock → Reports & Analysis → Reports",
                f"Open report #{new_id} (QA DEMO from #11)",
                "Pencil → edit text / feedback → Save",
                "Acknowledge warnings → Approve",
                "Download PDF → verify approved text; feedback not in client PDF",
            ],
            "model_input_keys": sorted(model_input.keys()),
            "metrics_post_count": (model_input.get("metrics") or {}).get("post_count"),
            "analysis_label": (period.get("label")),
            "planning_label": f"{planning.get('year')}-{planning.get('month')}",
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
