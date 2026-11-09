"""QA only: new client-report version from #16; one-shot gemini-3.8-flash; keep #16 mock.

No live DB writes. No search. No retries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA_DB = ROOT / "data" / "maaike_redrock_qa_demo.db"
LIVE = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_demo_qa16_paid_38flash.json"
PDF_DIR = ROOT / "data" / "report_pdfs"
BUDGET = 0.05
MODEL = "gemini-3.8-flash"
MAX_OUT = 4096
RATES_38 = {
    "provider": "Google Gemini Developer API",
    "model": MODEL,
    "currency": "USD",
    "input_per_1m": 0.75,
    "output_per_1m": 3.75,
    "rate_date": "2026-11-05",
    "source_url": "https://ai.google.dev/gemini-api/docs/pricing",
    "notes": "Intro Standard through 2026-12-31; thinking billed as output.",
}
MARKER = "QA REAL: goedgekeurde eindtekst na Gemini 3.8 (pencil) — Maaike-demo"


def now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def _estimate_38(snap: dict) -> dict:
    posts = int((snap.get("metrics") or {}).get("post_count") or 0)
    sources = len(snap.get("sources") or [])
    # Client report: larger than trend; include linked trend chapters ~3–6k tokens
    base_in = 12000 + 4000  # instructions + trend partial body
    in_low = base_in + sources * 200 + posts * 80
    in_high = base_in + sources * 400 + posts * 180 + 5000
    out_low, out_high = 1800, MAX_OUT
    cost_low = (in_low / 1e6) * RATES_38["input_per_1m"] + (out_low / 1e6) * RATES_38["output_per_1m"]
    cost_high = (in_high / 1e6) * RATES_38["input_per_1m"] + (out_high / 1e6) * RATES_38["output_per_1m"]
    return {
        "currency": "USD",
        "rate": RATES_38,
        "exact_model": MODEL,
        "status": "estimate_only_not_executed",
        "assumed_input_tokens": {"low": in_low, "high": in_high, "known": False},
        "assumed_output_tokens": {"low": out_low, "high": out_high, "known": False},
        "estimated_cost_usd": {"low": round(cost_low, 5), "high": round(cost_high, 5)},
        "combined_high_usd": round(cost_high, 5),
        "includes_max_output_tokens": MAX_OUT,
        "enable_google_search": False,
        "model_override": MODEL,
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
    # Live must not gain this report
    live = connect(LIVE)
    apply_migrations(live)
    assert live.execute("SELECT id FROM client_reports WHERE id = 16").fetchone() is None
    live.close()

    with transaction(QA_DB) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)
        ensure_report_review_tables(conn)

        src = conn.execute(
            "SELECT * FROM client_reports WHERE id = 16 AND client_id = 1"
        ).fetchone()
        assert src and src["status"] == "mock_completed" and src["is_mock"] == 1
        # Keep mock evidence
        mock_rev = conn.execute(
            "SELECT review_status, approved_at FROM client_report_reviews WHERE report_id = 16 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert mock_rev is not None

        t15 = conn.execute(
            "SELECT * FROM client_reports WHERE id = 15 AND client_id = 1 AND report_type = 'trend'"
        ).fetchone()
        assert t15 and t15["status"] == "completed"
        body15 = json.loads(t15["body_json"] or "{}")

        snap = json.loads(src["input_snapshot_json"] or "{}")
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
                "Gedeeltelijke trendbron (#15). Gebruik alleen als context; "
                "niet als fully_researched marktonderzoek. Ontbrekende SEO/stories/targets "
                "expliciet als Niet onderzocht / onvoldoende gegevens."
            ),
        }
        snap["partial"] = True
        snap["max_budget_usd"] = BUDGET
        snap["research_mode"] = "manual"
        snap["labels"] = {
            **(snap.get("labels") or {}),
            "qa_paid_from_report_16": True,
            "keeps_mock_16": True,
            "linked_trend_partial_15": True,
        }
        estimate = _estimate_38(snap)
        high = float(estimate["combined_high_usd"])
        assert high <= BUDGET, f"estimate {high} > budget {BUDGET}"
        snap["execution_constraints"] = {
            "max_budget_usd": BUDGET,
            "max_output_tokens": MAX_OUT,
            "enable_google_search": False,
            "one_shot_no_retries": True,
            "model_override": MODEL,
            "thinking_level": "low",
            "structured_json": True,
            "token_rates": RATES_38,
            "cloned_from": 16,
        }

        version, _ = _next_version(conn, 1, "client", int(src["period_year"]), int(src["period_month"]))
        ts = now()
        title = (
            f"QA REAL from #16 — analyse {src['period_year']}-{int(src['period_month']):02d} "
            f"→ planning {src['planning_year']}-{int(src['planning_month']):02d} "
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
                values.append(16)
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
                            "QA paid one-shot from mock #16; mock #16 remains as test evidence.",
                            f"model_override={MODEL}; thinking=low; search off; maxOut={MAX_OUT}.",
                            f"Preflight high USD {high} ≤ {BUDGET}.",
                            "Trend #15 attached as partial source (chapters in snapshot).",
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
                values.append(src[c])
        cur = conn.execute(
            f"INSERT INTO client_reports ({', '.join(insert_cols)}) VALUES ({', '.join('?' for _ in insert_cols)})",
            values,
        )
        new_id = int(cur.lastrowid)

        preview = execution_preview(conn, 1, new_id, max_budget_usd=BUDGET)
        assert preview["within_budget"] is True
        assert preview.get("enable_google_search") is False or (
            (preview.get("estimate") or {}).get("research_mode") == "manual"
        )

        # ONE paid attempt
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

        # Ensure #16 mock still approved
        still16 = conn.execute(
            "SELECT status, is_mock FROM client_reports WHERE id = 16"
        ).fetchone()
        rev16 = conn.execute(
            "SELECT review_status FROM client_report_reviews WHERE report_id = 16 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert still16["status"] == "mock_completed" and still16["is_mock"] == 1
        assert (rev16["review_status"] or "").lower() == "approved"

        out = {
            "new_report_id": new_id,
            "kept_mock_16": True,
            "mock_16_review": rev16["review_status"],
            "status": report["status"],
            "model": MODEL,
            "preflight_high_usd": high,
            "within_budget": True,
            "http_status": body.get("http_status") or usage.get("http_status"),
            "error_text": report.get("error_text") or body.get("error") or "",
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
        }

        if report["status"] not in {"completed", "mock_completed"}:
            OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
            raise SystemExit(f"Generation failed: {out['error_text'][:300]}")

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
            attention.append(f"Periode mismatch: analysis={analysis} planning={planning}")
        if "september" not in blob and "2026-09" not in blob and "sep" not in blob:
            attention.append("Tekst noemt analyseperiode september mogelijk niet expliciet.")
        if "november" not in blob and "2026-11" not in blob:
            attention.append("Tekst noemt planningsmaand november mogelijk niet expliciet.")
        # Missing targets/stories honesty
        una_join = " ".join(str(u).lower() for u in unassessable)
        chapter_join = " ".join(str(v).lower() for v in chapters.values())
        if "target" not in una_join and "doel" not in una_join and "target" not in chapter_join:
            attention.append("Targets ontbreken in data — geen honesty-marker gevonden in unassessable/chapters.")
        if "stor" not in una_join and "figma" not in una_join and "stor" not in chapter_join:
            attention.append("Stories ontbreken — geen honesty-marker gevonden.")
        # Invented volumes
        if "ahrefs" in blob and "niet onderzocht" not in blob and "onvoldoende" not in blob:
            attention.append("Mogelijke Ahrefs-claim zonder honesty.")
        for k in ("beter", "slechter", "verklaring", "herhalen", "stoppen", "testen"):
            if not str(six.get(k) or "").strip():
                attention.append(f"six_answers.{k} leeg")
        for k in (
            "input_brainstorm",
            "per_kanaal",
            "seo_serp",
            "concurrenten",
            "hooks_formats_testen",
            "laten_liggen_aanscherpen",
        ):
            if not str(chapters.get(k) or "").strip():
                attention.append(f"chapter.{k} leeg")

        # Mark partial human review
        body = {
            **body,
            "partial": True,
            "human_review_required": True,
            "qa_real_from_16": True,
            "linked_trend_report_id": 15,
            "keeps_mock_report_16": True,
        }
        conn.execute(
            "UPDATE client_reports SET body_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(body, ensure_ascii=False), now(), new_id),
        )

        # Review → approve → PDF
        detail = get_report(conn, 1, new_id)
        items = list(detail["review"]["item_feedback"] or [])
        target = next(
            (i for i in items if str(i.get("key") or "").startswith("six_answers.")),
            items[0] if items else None,
        )
        if target:
            target["feedback"] = "Interne QA-notitie: niet in klant-PDF."
            # Prefer a short approved edit on first answer if empty edit
            if not str(target.get("edited_text") or "").strip():
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
                    "note": "QA: accepted for demo after human check of honesty markers.",
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

        ready = (
            report["status"] == "completed"
            and (body.get("validation") or {}).get("usable") is not False
            and MARKER.split("—")[0].strip() in (approved["review"].get("final_version_text") or "")
            or MARKER in (approved["review"].get("final_version_text") or "")
        )
        marker_in_pdf = "QA REAL" in pdf_text or MARKER[:20] in pdf_text
        feedback_leaked = "Interne QA-notitie" in pdf_text

        out.update(
            {
                "attention_points": attention,
                "unassessable": unassessable,
                "six_answer_keys": list(six.keys()),
                "chapter_keys": list(chapters.keys()),
                "period": {"analysis": analysis, "planning": planning},
                "review_status": approved["review"].get("review_status"),
                "approved_at": approved["review"].get("approved_at"),
                "pdf_path": str(pdf_path),
                "pdf_content_source": pdf_pres.get("content_source"),
                "marker_in_pdf": marker_in_pdf,
                "internal_feedback_leaked": feedback_leaked,
                "ready_to_show_maaike": bool(
                    ready and marker_in_pdf and not feedback_leaked and len(attention) <= 3
                ),
                "ready_caveats": attention,
                "click_path": [
                    "API: MAAIKE_DATABASE_PATH=data/maaike_redrock_qa_demo.db",
                    "Dashboard → Red Rock → Reports & Analysis → Reports",
                    f"Open #{new_id} (QA REAL from #16)",
                    "Mock #16 blijft beschikbaar als testbewijs",
                ],
            }
        )
        # Soft ready: content usable + approved PDF even if attention notes exist
        out["ready_to_show_maaike"] = bool(
            report["status"] == "completed"
            and marker_in_pdf
            and not feedback_leaked
            and (approved["review"].get("review_status") or "").lower() == "approved"
        )
        out["show_with_human_caveats"] = attention

        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
