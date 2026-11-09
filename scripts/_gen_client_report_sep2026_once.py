"""One-shot client report generation for Red Rock Sept 2026. No retries."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maaike.ai_response_validate import (
    audit_unfounded_source_claims,
    available_sources_from_snapshot,
)
from maaike.db import transaction
from maaike.report_execute import execute_report, execution_preview
from maaike.reports import get_report, prepare_client_report


def _fingerprint(row) -> dict:
    snap = row["input_snapshot_json"] or ""
    body = row["body_json"] or ""
    return {
        "updated_at": row["updated_at"],
        "status": row["status"],
        "version": row["version"],
        "snap_sha": hashlib.sha256(snap.encode("utf-8")).hexdigest(),
        "body_sha": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "snap_len": len(snap),
        "body_len": len(body),
    }


def main() -> int:
    out: dict = {"ok": False}
    with transaction() as conn:
        r7_before = conn.execute(
            "SELECT id, version, status, updated_at, input_snapshot_json, body_json "
            "FROM client_reports WHERE id = 7 AND client_id = 1"
        ).fetchone()
        if r7_before is None:
            raise SystemExit("Report #7 missing")
        out["report7_before"] = _fingerprint(r7_before)

        prepared = prepare_client_report(
            conn,
            1,
            period_year=2026,
            period_month=9,
            linked_trend_report_id=None,
            allow_partial_without_trend=True,
        )
        report = prepared["report"]
        report_id = int(report["id"])
        snap = report["input_snapshot"]
        out["prepared"] = {
            "id": report_id,
            "version": report["version"],
            "prompt_version": report["prompt_version"],
            "status": report["status"],
            "attached_ai_analysis_ids": snap.get("attached_ai_analysis_ids"),
            "ai_analysis_executed": snap.get("ai_analysis_executed"),
            "ai_analysis_status": snap.get("ai_analysis_status"),
            "partial": snap.get("partial"),
            "missing": snap.get("missing"),
        }
        posts = snap.get("posts") or []
        post3 = next((p for p in posts if p.get("post_id") == 3), None)
        ai = (post3 or {}).get("ai_analysis") or {}
        out["prepared"]["post3_ai"] = {
            "id": ai.get("id"),
            "post_id": ai.get("post_id"),
            "client_id": ai.get("client_id"),
            "status": ai.get("status"),
            "prompt_version": ai.get("prompt_version"),
            "source": ai.get("source"),
        }
        if (
            ai.get("id") != 2
            or ai.get("post_id") != 3
            or ai.get("status") != "completed"
            or ai.get("source") != "post_ai_analyses"
        ):
            raise SystemExit(
                f"Abort: Claude analysis #2 for post #3 not in prepared input: {out['prepared']['post3_ai']}"
            )
        if report["prompt_version"] != "maaike-rapporten-v2.1":
            raise SystemExit(f"Abort: unexpected prompt version {report['prompt_version']}")

        preview = execution_preview(conn, 1, report_id)
        out["execution_preview"] = {
            "model": preview.get("model"),
            "provider": preview.get("provider"),
            "enable_google_search": preview.get("enable_google_search"),
            "research_mode": preview.get("research_mode"),
            "within_budget": preview.get("within_budget"),
            "estimate": preview.get("estimate"),
            "partial": preview.get("partial"),
        }

        # Single generation attempt — no retries.
        executed = execute_report(conn, 1, report_id, dry_run_paid=False)
        result = executed["report"]
        body = result.get("body") or {}
        usage = result.get("usage") or {}
        sources = available_sources_from_snapshot(result.get("input_snapshot") or snap)
        findings = audit_unfounded_source_claims(body, available_sources=sources)

        out["executed"] = {
            "id": result["id"],
            "version": result["version"],
            "status": result["status"],
            "prompt_version": result["prompt_version"],
            "model": result.get("model"),
            "provider": result.get("provider"),
            "executed_at": result.get("executed_at"),
            "error_text": result.get("error_text") or "",
            "analysis_usable": body.get("analysis_usable"),
            "partial": body.get("partial"),
            "requires_human_approval": body.get("requires_human_approval"),
            "fully_researched": body.get("fully_researched"),
            "six_answer_keys": sorted((body.get("six_answers") or {}).keys()),
            "chapter_keys": sorted((body.get("chapters") or {}).keys()),
            "action_plan_keys": sorted((body.get("action_plan") or {}).keys()),
            "seo_serp_prefix": str((body.get("chapters") or {}).get("seo_serp") or "")[:180],
            "concurrenten_prefix": str((body.get("chapters") or {}).get("concurrenten") or "")[:180],
            "validation": body.get("validation"),
            "source_grounding": body.get("source_grounding"),
            "post_audit_unfounded": findings,
            "usage": usage,
        }

        r7_after = conn.execute(
            "SELECT id, version, status, updated_at, input_snapshot_json, body_json "
            "FROM client_reports WHERE id = 7 AND client_id = 1"
        ).fetchone()
        out["report7_after"] = _fingerprint(r7_after)
        out["report7_unchanged"] = out["report7_before"] == out["report7_after"]
        out["ok"] = True

    Path("data/_last_client_report_gen.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") and out.get("report7_unchanged") else 1


if __name__ == "__main__":
    raise SystemExit(main())
