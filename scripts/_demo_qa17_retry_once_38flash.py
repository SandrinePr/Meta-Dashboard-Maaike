"""QA: one new paid attempt from #17 snapshot; keep #16+#17; no search/retries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA_DB = ROOT / "data" / "maaike_redrock_qa_demo.db"
LIVE = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_demo_qa17_retry_once.json"
PDF_DIR = ROOT / "data" / "report_pdfs"
BUDGET = 0.05
MODEL = "gemini-3.8-flash"
MAX_OUT = 4096
# Official Standard intro rates (same as #15/#17)
RATES_38 = {
    "provider": "Google Gemini Developer API",
    "model": MODEL,
    "currency": "USD",
    "input_per_1m": 0.75,
    "output_per_1m": 3.75,
    "rate_date": "2026-11-05",
    "source_url": "https://ai.google.dev/gemini-api/docs/pricing",
}
# Fallback proposal only if this attempt returns 503 (not auto-executed)
ALT_MODEL = "gemini-3.5-flash-lite"
ALT_RATES = {"input_per_1m": 0.30, "output_per_1m": 2.50, "model": ALT_MODEL}
MARKER = "QA REAL #from17: goedgekeurde eindtekst (pencil) — Maaike-demo"


def now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def _estimate(snap: dict, rates: dict, model: str) -> dict:
    posts = int((snap.get("metrics") or {}).get("post_count") or 0)
    sources = len(snap.get("sources") or [])
    base_in = 12000 + 4000
    in_low = base_in + sources * 200 + posts * 80
    in_high = base_in + sources * 400 + posts * 180 + 5000
    out_low, out_high = 1800, MAX_OUT
    cost_low = (in_low / 1e6) * rates["input_per_1m"] + (out_low / 1e6) * rates["output_per_1m"]
    cost_high = (in_high / 1e6) * rates["input_per_1m"] + (out_high / 1e6) * rates["output_per_1m"]
    return {
        "currency": "USD",
        "rate": {**rates, "model": model},
        "exact_model": model,
        "assumed_input_tokens": {"low": in_low, "high": in_high},
        "assumed_output_tokens": {"low": out_low, "high": out_high},
        "estimated_cost_usd": {"low": round(cost_low, 5), "high": round(cost_high, 5)},
        "combined_high_usd": round(cost_high, 5),
        "enable_google_search": False,
        "thinking_level": "low",
    }


def main() -> None:
    from maaike.client_report_pdf import render_client_report_pdf
    from maaike.client_report_view import default_review_attention_points
    from maaike.db import connect, transaction
    from maaike.migrate import apply_migrations
    from maaike.report_execute import execute_report, execution_preview
    from maaike.report_prompts import PROMPT_VERSION
    from maaike.report_review import ensure_report_review_tables, save_report_review, warning_ack_key
    from maaike.reports import _next_version, _trend_summary, ensure_report_tables, get_report

    assert QA_DB.exists()
    live = connect(LIVE)
    apply_migrations(live)
    assert live.execute("SELECT id FROM client_reports WHERE id IN (16,17)").fetchone() is None
    live.close()

    with transaction(QA_DB) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)
        ensure_report_review_tables(conn)

        src17 = conn.execute(
            "SELECT * FROM client_reports WHERE id = 17 AND client_id = 1"
        ).fetchone()
        assert src17 and src17["status"] == "failed"
        src16 = conn.execute(
            "SELECT status, is_mock FROM client_reports WHERE id = 16"
        ).fetchone()
        assert src16["status"] == "mock_completed" and src16["is_mock"] == 1

        t15 = conn.execute(
            "SELECT body_json FROM client_reports WHERE id = 15 AND client_id = 1"
        ).fetchone()
        body15 = json.loads(t15["body_json"] or "{}")

        snap = json.loads(src17["input_snapshot_json"] or "{}")
        # Same Red Rock input as #17; refresh partial trend #15 payload
        trend_meta = _trend_summary(conn, 1, 15)
        snap["linked_trend"] = {
            **(trend_meta or {}),
            "partial_concept": True,
            "fully_researched": False,
            "human_review_required": True,
            "chapters": body15.get("chapters") or {},
            "distinctions": body15.get("distinctions") or {},
            "unassessable": body15.get("unassessable") or [],
            "claims_with_citations": body15.get("claims_with_citations") or [],
            "usage_note": (
                "Gedeeltelijke trendbron (#15). Ontbrekende targets/stories/SEO "
                "als 'Niet onderzocht / onvoldoende gegevens'."
            ),
        }
        snap["partial"] = True
        snap["max_budget_usd"] = BUDGET
        snap["research_mode"] = "manual"
        snap["labels"] = {
            **(snap.get("labels") or {}),
            "qa_paid_from_report_17": True,
            "keeps_16_and_17": True,
            "linked_trend_partial_15": True,
        }
        estimate = _estimate(snap, RATES_38, MODEL)
        high = float(estimate["combined_high_usd"])
        assert high <= BUDGET, f"estimate {high} > {BUDGET}"
        snap["execution_constraints"] = {
            "max_budget_usd": BUDGET,
            "max_output_tokens": MAX_OUT,
            "enable_google_search": False,
            "one_shot_no_retries": True,
            "model_override": MODEL,
            "thinking_level": "low",
            "structured_json": True,
            "token_rates": RATES_38,
            "cloned_from": 17,
        }

        version, _ = _next_version(
            conn, 1, "client", int(src17["period_year"]), int(src17["period_month"])
        )
        ts = now()
        title = (
            f"QA REAL from #17 — analyse {src17['period_year']}-{int(src17['period_month']):02d} "
            f"→ planning {src17['planning_year']}-{int(src17['planning_month']):02d} "
            f"+ trend #15 ({MODEL})"
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(client_reports)").fetchall()]
        insert_cols = [c for c in cols if c != "id"]
        values = []
        for c in insert_cols:
            if c == "title":
                values.append(title)
            elif c == "status":
                values.append("prepared")
            elif c == "version":
                values.append(version)
            elif c == "supersedes_id":
                values.append(17)
            elif c == "linked_trend_report_id":
                values.append(15)
            elif c == "input_snapshot_json":
                values.append(json.dumps(snap, ensure_ascii=False))
            elif c == "estimate_json":
                values.append(json.dumps(estimate, ensure_ascii=False))
            elif c == "notes_json":
                values.append(
                    json.dumps(
                        [
                            "QA one-shot from #17 input; keep #16 mock + #17 failed as evidence.",
                            f"model_override={MODEL}; thinking=low; search off; maxOut={MAX_OUT}.",
                            f"Preflight high USD {high} ≤ {BUDGET}.",
                        ],
                        ensure_ascii=False,
                    )
                )
            elif c == "body_json":
                values.append("{}")
            elif c == "usage_json":
                values.append("{}")
            elif c == "error_text":
                values.append("")
            elif c == "executed_at":
                values.append(None)
            elif c in {"prepared_at", "created_at", "updated_at"}:
                values.append(ts)
            elif c == "is_mock":
                values.append(0)
            elif c == "model":
                values.append(MODEL)
            elif c == "provider":
                values.append("Google Gemini Developer API (native)")
            elif c == "prompt_version":
                values.append(PROMPT_VERSION)
            else:
                values.append(src17[c])
        cur = conn.execute(
            f"INSERT INTO client_reports ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
            values,
        )
        new_id = int(cur.lastrowid)

        preview = execution_preview(conn, 1, new_id, max_budget_usd=BUDGET)
        assert preview["within_budget"] is True

        result = execute_report(
            conn,
            1,
            new_id,
            max_budget_usd=BUDGET,
            dry_run_paid=False,
            model_override=MODEL,
            thinking_level="low",
            max_output_tokens=MAX_OUT,
        )
        report = result["report"]
        body = report.get("body") or {}
        usage = report.get("usage") or {}

        # Preserve #16/#17
        s16 = conn.execute("SELECT status, is_mock FROM client_reports WHERE id=16").fetchone()
        s17 = conn.execute("SELECT status, is_mock FROM client_reports WHERE id=17").fetchone()
        assert s16["status"] == "mock_completed" and s16["is_mock"] == 1
        assert s17["status"] == "failed"

        alt_est = _estimate(snap, ALT_RATES, ALT_MODEL)
        out: dict = {
            "new_report_id": new_id,
            "kept_16": True,
            "kept_17": True,
            "status": report["status"],
            "model": MODEL,
            "preflight_high_usd": high,
            "http_status": body.get("http_status") or usage.get("http_status"),
            "error_code": body.get("error_code") or usage.get("error_code"),
            "error_status": body.get("error_status") or usage.get("error_status"),
            "error_text": (report.get("error_text") or body.get("error") or "")[:500],
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "thoughts_tokens": usage.get("thoughts_tokens"),
                "billed_output_tokens": usage.get("billed_output_tokens"),
                "actual_cost_usd": usage.get("actual_cost_usd"),
                "cost_known": usage.get("cost_known"),
                "retries": usage.get("retries", 0),
                "search_queries": usage.get("search_queries"),
            },
            "validation": body.get("validation"),
            "alternative_if_503": {
                "model": ALT_MODEL,
                "combined_high_usd": alt_est["combined_high_usd"],
                "estimated_cost_usd": alt_est["estimated_cost_usd"],
                "note": "Not executed — proposal only after this one attempt.",
            },
        }

        if report["status"] != "completed":
            OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
            raise SystemExit("GENERATION_FAILED")

        # Content audit
        six = body.get("six_answers") or {}
        chapters = body.get("chapters") or {}
        unassessable = body.get("unassessable") or []
        blob = json.dumps(body, ensure_ascii=False).lower()
        period = (report.get("input_snapshot") or snap).get("period") or {}
        analysis = period.get("analysis_period") or {}
        planning = period.get("planning_period") or {}
        attention = []
        if analysis.get("month") != 9 or planning.get("month") != 11:
            attention.append(f"Periode mismatch analysis={analysis} planning={planning}")
        una = " ".join(str(u).lower() for u in unassessable)
        ch = " ".join(str(v).lower() for v in chapters.values())
        for label, needles in (
            ("targets", ("target", "doel")),
            ("stories", ("stor", "figma")),
            ("seo", ("seo", "serp", "ahrefs", "zoek")),
        ):
            if not any(n in una or n in ch for n in needles):
                attention.append(f"Geen honesty-marker voor ontbrekende {label}.")
        if "ahrefs" in blob and "niet onderzocht" not in blob and "onvoldoende" not in blob:
            attention.append("Mogelijke Ahrefs-claim zonder honesty.")
        for k in ("beter", "slechter", "verklaring", "herhalen", "stoppen", "testen"):
            if not str(six.get(k) or "").strip():
                attention.append(f"six_answers.{k} leeg")

        body = {
            **body,
            "partial": True,
            "human_review_required": True,
            "qa_real_from_17": True,
            "linked_trend_report_id": 15,
            "keeps_reports_16_and_17": True,
            "model": MODEL,
        }
        conn.execute(
            "UPDATE client_reports SET body_json=?, updated_at=? WHERE id=?",
            (json.dumps(body, ensure_ascii=False), now(), new_id),
        )

        detail = get_report(conn, 1, new_id)
        items = list(detail["review"]["item_feedback"] or [])
        target = next(
            (i for i in items if str(i.get("key") or "").startswith("six_answers.")),
            items[0] if items else None,
        )
        if target:
            target["feedback"] = "Interne QA-notitie: niet in klant-PDF."
            base = str(target.get("original_text") or six.get("beter") or "")[:500]
            target["edited_text"] = f"{MARKER}\n\n{base}".strip()

        saved = save_report_review(
            conn,
            1,
            new_id,
            {
                "reviewer_name": "QA Demo",
                "item_feedback": items,
                "compose_final_from_items": True,
            },
        )
        # Reload simulation
        reloaded = get_report(conn, 1, new_id)
        assert MARKER in (reloaded["review"].get("final_version_text") or "")

        points = default_review_attention_points(body)
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
                    "note": "QA ack after content check",
                    "kind": p.get("kind"),
                    "location": p.get("location") or "",
                    "by": "QA Demo",
                }
            )
        acked = save_report_review(
            conn,
            1,
            new_id,
            {
                "reviewer_name": "QA Demo",
                "item_feedback": saved["review"]["item_feedback"],
                "warning_acknowledgements": acks,
                "compose_final_from_items": True,
            },
        )
        approved = save_report_review(
            conn,
            1,
            new_id,
            {
                "reviewer_name": "QA Demo",
                "item_feedback": acked["review"]["item_feedback"],
                "warning_acknowledgements": acked["review"].get("warning_acknowledgements") or acks,
                "approve": True,
                "compose_final_from_items": True,
            },
        )
        pdf_bytes, pdf_pres = render_client_report_pdf(conn, 1, new_id)
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = PDF_DIR / f"qa-demo-{new_id}-approved-real.pdf"
        pdf_path.write_bytes(pdf_bytes)
        pdf_text = ""
        try:
            import fitz

            doc = fitz.open(pdf_path)
            pdf_text = "\n".join((page.get_text() or "") for page in doc)
        except Exception as exc:
            pdf_text = f"(extract_failed: {exc})"

        marker_in_pdf = "QA REAL" in pdf_text or MARKER[:24] in pdf_text
        feedback_leaked = "Interne QA-notitie" in pdf_text
        ready = (
            report["status"] == "completed"
            and (approved["review"].get("review_status") or "").lower() == "approved"
            and marker_in_pdf
            and not feedback_leaked
        )
        out.update(
            {
                "attention_points": attention,
                "unassessable": unassessable,
                "period": {"analysis": analysis, "planning": planning},
                "review_status": approved["review"].get("review_status"),
                "approved_at": approved["review"].get("approved_at"),
                "pdf_path": str(pdf_path),
                "pdf_content_source": pdf_pres.get("content_source"),
                "marker_in_pdf": marker_in_pdf,
                "internal_feedback_leaked": feedback_leaked,
                "ready_to_show_maaike": ready,
                "click_path": [
                    "MAAIKE_DATABASE_PATH=data/maaike_redrock_qa_demo.db",
                    "Dashboard → Red Rock → Reports & Analysis → Reports",
                    f"Open #{new_id} (QA REAL from #17)",
                    "#16 mock + #17 failed blijven staan als bewijs",
                ],
            }
        )
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        if not ready:
            raise SystemExit("NOT_READY")


if __name__ == "__main__":
    main()
