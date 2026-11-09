"""Clone failed trend #13 → new version; one execute; keep #12/#13; no retries."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.ai_trial import _now
from maaike.db import transaction
from maaike.gemini_native import load_native_config
from maaike.migrate import apply_migrations
from maaike.report_execute import execute_report, execution_preview
from maaike.report_prompts import PROMPT_VERSION, load_report_instruction_bundle
from maaike.reports import (
    _estimate_report,
    _next_version,
    ensure_report_tables,
    get_report,
)

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
DB = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_trend13v3_execute.json"
BUDGET = 0.05
SOURCE_ID = 13
CLIENT_ID = 1
MAX_OUT = 4096


def main() -> None:
    cfg = load_native_config()
    bundle = load_report_instruction_bundle("trend")
    assert cfg["has_api_key"], "AI_API_KEY ontbreekt"
    assert cfg["model"] == "gemini-3.5-flash-lite" or cfg["model"].startswith("gemini"), cfg["model"]

    with transaction(DB) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)

        src = conn.execute(
            "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
            (SOURCE_ID, CLIENT_ID),
        ).fetchone()
        assert src and src["status"] == "failed" and src["report_type"] == "trend"

        # Preserve earlier versions
        for keep_id in (12, 13):
            st = conn.execute(
                "SELECT status FROM client_reports WHERE id = ?", (keep_id,)
            ).fetchone()["status"]
            assert st == "failed", f"#{keep_id} must stay failed, got {st}"

        snap = json.loads(src["input_snapshot_json"] or "{}")
        sources = list(snap.get("sources") or [])
        assert len(sources) >= 8

        snap["max_budget_usd"] = BUDGET
        snap["research_mode"] = "manual"
        snap["partial"] = True
        snap["labels"] = {
            **(snap.get("labels") or {}),
            "explicit_partial_trend_concept": True,
            "cloned_from_failed_report_id": SOURCE_ID,
            "edits_excluded_as_evidence": True,
            "frankwatching_background_only": True,
            "wonen360_background_uncertain_date": True,
            "woonhype_wikipedia_interest_proxy": True,
            "no_invented_ahrefs_or_volumes": True,
        }
        snap["execution_constraints"] = {
            "max_budget_usd": BUDGET,
            "max_output_tokens": MAX_OUT,
            "enable_google_search": False,
            "one_shot_no_retries": True,
            "no_model_switch": True,
            "cloned_from": SOURCE_ID,
            "model": cfg["model"],
            "endpoint": cfg["native_endpoint"],
        }
        estimate = _estimate_report("trend", snap)
        high = float(estimate.get("combined_high_usd") or 99)
        assert high <= BUDGET, f"estimate {high} > {BUDGET}"
        out_high = int((estimate.get("assumed_output_tokens") or {}).get("high") or 0)
        assert out_high <= MAX_OUT

        version, _ = _next_version(
            conn, CLIENT_ID, "trend", int(src["period_year"]), int(src["period_month"])
        )
        now = _now()
        title = (snap.get("period") or {}).get("title_hint") or src["title"]
        if "(handmatige bronnen)" not in title:
            title = f"{title} (handmatige bronnen)"
        title = f"{title} — v{version} concept"

        cur = conn.execute(
            """
            INSERT INTO client_reports (
                client_id, report_type, period_year, period_month, planning_year, planning_month,
                title, status, version, supersedes_id, prompt_version, provider, model,
                prepared_at, executed_at, input_snapshot_json, sources_json, body_json,
                estimate_json, usage_json, linked_trend_report_id, error_text, is_mock,
                notes_json, created_at, updated_at
            ) VALUES (
                ?, 'trend', ?, ?, ?, ?, ?, 'prepared', ?, ?, ?, ?, ?,
                ?, NULL, ?, ?, '{}', ?, '{}', NULL, '', 0, ?, ?, ?
            )
            """,
            (
                CLIENT_ID,
                int(src["period_year"]),
                int(src["period_month"]),
                int(src["planning_year"]),
                int(src["planning_month"]),
                title,
                version,
                SOURCE_ID,
                PROMPT_VERSION,
                "Google Gemini Developer API (native)",
                cfg["model"],
                now,
                json.dumps(snap, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                json.dumps(estimate, ensure_ascii=False),
                json.dumps(
                    [
                        f"Gekloond van #{SOURCE_ID}; #12/#13 blijven failed.",
                        f"Budgetpoort USD {BUDGET}; zoeken uit; maxOutputTokens={MAX_OUT}.",
                        "Eén generatiepoging; geen retries/modelwissel.",
                        f"Model/config (geen probe): {cfg['model']} @ {cfg['native_endpoint']}",
                        f"Raming high USD {high} ≤ {BUDGET}.",
                    ],
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
        new_id = int(cur.lastrowid)

        for s in sources:
            if not isinstance(s, dict):
                continue
            meta = {
                k: s.get(k)
                for k in (
                    "counted_as_read_source",
                    "usable_for_findings",
                    "read_depth",
                    "development_id",
                    "source_role",
                    "exclude_reason",
                    "fetch_error",
                    "content_chars",
                )
                if s.get(k) is not None
            }
            conn.execute(
                """
                INSERT INTO client_report_sources (
                    report_id, title, url, published_at, consulted_at, excerpt, source_kind,
                    created_at, fetch_status, content_fetched, fetched_at, supported_finding,
                    certainty, limitations, historical_ok, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    s.get("title") or "",
                    s.get("url") or "",
                    s.get("published_at"),
                    s.get("consulted_at") or now[:10],
                    s.get("excerpt") or "",
                    s.get("source_kind") or "manual",
                    now,
                    s.get("fetch_status") or "",
                    1 if s.get("content_fetched") else 0,
                    s.get("fetched_at"),
                    s.get("supported_finding") or "",
                    s.get("certainty") or "",
                    s.get("limitations") or "",
                    None
                    if s.get("historical_ok") is None
                    else (1 if s.get("historical_ok") else 0),
                    json.dumps(meta, ensure_ascii=False),
                ),
            )

        preview = execution_preview(conn, CLIENT_ID, new_id, max_budget_usd=BUDGET)
        assert preview["enable_google_search"] is False
        assert preview["within_budget"] is True, preview.get("budget_note")
        preflight = {
            "new_id": new_id,
            "version": version,
            "supersedes_id": SOURCE_ID,
            "model": cfg["model"],
            "endpoint": cfg["native_endpoint"],
            "budget_usd": BUDGET,
            "combined_high_usd": float(
                (preview.get("estimate") or {}).get("combined_high_usd") or high
            ),
            "within_budget": True,
            "max_output_tokens": MAX_OUT,
            "assumed_output_tokens": (preview.get("estimate") or {}).get(
                "assumed_output_tokens"
            ),
            "enable_google_search": False,
            "source_count": len(sources),
            "period": snap.get("period"),
            "chapters_expected": bundle.get("chapter_keys") or bundle.get("chapters"),
            "no_api_probe": True,
        }

        # ONE attempt
        result = execute_report(
            conn,
            CLIENT_ID,
            new_id,
            max_budget_usd=BUDGET,
            dry_run_paid=False,
        )
        report = result["report"]
        body = report.get("body") or {}
        usage = report.get("usage") or {}

        # Keep prior versions failed / unlinked
        for keep_id in (12, 13):
            assert (
                conn.execute(
                    "SELECT status FROM client_reports WHERE id = ?", (keep_id,)
                ).fetchone()["status"]
                == "failed"
            )
        r11 = conn.execute(
            "SELECT linked_trend_report_id FROM client_reports WHERE id = 11"
        ).fetchone()
        assert r11["linked_trend_report_id"] in (None, "")

        if report["status"] == "completed":
            body = {
                **body,
                "partial": True,
                "fully_researched": False,
                "human_review_required": True,
                "ai_concept_partial": True,
                "not_approved": True,
                "not_linked_to_client_report": True,
                "cloned_from_failed_report_id": SOURCE_ID,
                "do_not_auto_link_client_report_11": True,
            }
            conn.execute(
                """
                UPDATE client_reports
                SET body_json = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (json.dumps(body, ensure_ascii=False), new_id),
            )

        reopened = get_report(conn, CLIENT_ID, new_id)
        chapters = body.get("chapters") if isinstance(body.get("chapters"), dict) else {}
        required = [
            "positionering",
            "managementsamenvatting",
            "belangrijkste_trends",
            "platform_verschuivingen",
            "contentkansen",
            "zoekclusters",
            "conclusie",
        ]
        chapter_presence = {k: bool(str(chapters.get(k) or "").strip()) for k in required}
        citations = body.get("claims_with_citations") or []
        distinctions = (
            body.get("distinctions") if isinstance(body.get("distinctions"), dict) else {}
        )
        period = (report.get("input_snapshot") or {}).get("period") or {}
        attention = []
        if report["status"] != "completed":
            attention.append(
                f"Status={report['status']}: {report.get('error_text') or body.get('error')}"
            )
        else:
            for k, ok in chapter_presence.items():
                if not ok:
                    attention.append(f"Hoofdstuk ontbreekt/leeg: {k}")
            if not citations:
                attention.append("Geen claims_with_citations.")
            if period.get("planning_month") != 11 or period.get("lookback_start") != "2026-08-21":
                attention.append("Periode wijkt af van nov-2026 / lookback 21aug–20sep.")
            if body.get("fully_researched") is True:
                attention.append("fully_researched=true ondanks partieel concept.")
            blob = json.dumps(body, ensure_ascii=False).lower()
            if "ahrefs" in blob and "niet onderzocht" not in blob:
                attention.append("Mogelijke Ahrefs-claim zonder honesty-marker.")
            if "projectversies" in blob or "item-alignment" in blob:
                attention.append("Mogelijke Edits-bevinding ondanks uitsluiting.")

        out = {
            "kept_failed": [12, 13],
            "new_report_id": new_id,
            "version": version,
            "status": report["status"],
            "preflight": preflight,
            "http_status": body.get("http_status") or usage.get("http_status"),
            "error_code": body.get("error_code") or usage.get("error_code"),
            "error_status": body.get("error_status") or usage.get("error_status"),
            "error_text": report.get("error_text") or body.get("error") or "",
            "provider_error": body.get("provider_error"),
            "endpoint": body.get("endpoint") or usage.get("endpoint") or cfg["native_endpoint"],
            "retries": body.get("retries") if body.get("retries") is not None else usage.get("retries"),
            "partial": body.get("partial"),
            "fully_researched": body.get("fully_researched"),
            "human_review_required": body.get("human_review_required"),
            "ai_concept_partial": body.get("ai_concept_partial"),
            "period": period,
            "chapter_presence": chapter_presence,
            "citations_count": len(citations) if isinstance(citations, list) else 0,
            "citations_sample": citations[:6] if isinstance(citations, list) else [],
            "distinctions_counts": {
                k: len(v) if isinstance(v, list) else (1 if v else 0)
                for k, v in (distinctions or {}).items()
            },
            "unassessable": body.get("unassessable"),
            "validation": body.get("validation"),
            "usage": usage,
            "raw_response_chars": len(str(body.get("raw_response") or "")),
            "attention_points": attention,
            "r11_linked": False,
            "reopen_ok": reopened["report"]["id"] == new_id
            and reopened["report"]["status"] == report["status"],
            "click_path": [
                "Dashboard → Red Rock → Rapporten",
                f"Open trendrapport #{new_id}",
                "Lees als partieel concept (human review)",
                "Niet koppelen aan #11 tot inhoudelijke controle klaar is",
            ],
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        if chapters:
            (ROOT / "data" / "imports" / "redrock" / f"_trend{new_id}_chapters.json").write_text(
                json.dumps(
                    {
                        "report_id": new_id,
                        "chapters": chapters,
                        "distinctions": distinctions,
                        "claims_with_citations": citations,
                        "unassessable": body.get("unassessable"),
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        print(
            json.dumps(
                {
                    "new_id": new_id,
                    "status": report["status"],
                    "http_status": out["http_status"],
                    "error_code": out["error_code"],
                    "error_status": out["error_status"],
                    "error": (out["error_text"] or "")[:200],
                    "tokens": {
                        "prompt": usage.get("prompt_tokens"),
                        "completion": usage.get("completion_tokens"),
                    },
                    "cost_usd": usage.get("actual_cost_usd"),
                    "out": str(OUT),
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
