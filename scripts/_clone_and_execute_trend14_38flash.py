"""Clone #14 → new trend version; one-shot gemini-3.8-flash override; no retries."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.ai_trial import _now
from maaike.db import transaction
from maaike.migrate import apply_migrations
from maaike.report_execute import execute_report, execution_preview
from maaike.report_prompts import PROMPT_VERSION, load_report_instruction_bundle
from maaike.reports import _next_version, ensure_report_tables, get_report

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
DB = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_trend14_38flash_execute.json"
BUDGET = 0.05
SOURCE_ID = 14
CLIENT_ID = 1
MAX_OUT = 4096
MODEL = "gemini-3.8-flash"
# Official intro Standard rates through 2026-12-31 (ai.google.dev/gemini-api/docs/pricing)
RATES_38 = {
    "provider": "Google Gemini Developer API",
    "model": MODEL,
    "currency": "USD",
    "input_per_1m": 0.75,
    "output_per_1m": 3.75,
    "rate_date": "2026-11-05",
    "source_url": "https://ai.google.dev/gemini-api/docs/pricing",
    "notes": "Introductory Standard tier through 2026-12-31; thinking billed as output.",
}


def _estimate_with_rates(snap: dict, rates: dict) -> dict:
    sources = len(snap.get("sources") or [])
    base_in = 8000
    in_low = base_in + sources * 400
    in_high = base_in + sources * 900 + 4000
    out_low, out_high = 1500, min(4000, MAX_OUT)
    cost_low = (in_low / 1_000_000) * rates["input_per_1m"] + (out_low / 1_000_000) * rates[
        "output_per_1m"
    ]
    cost_high = (in_high / 1_000_000) * rates["input_per_1m"] + (MAX_OUT / 1_000_000) * rates[
        "output_per_1m"
    ]
    return {
        "currency": "USD",
        "rate": rates,
        "provider": "Google Gemini Developer API (native generateContent)",
        "exact_model": MODEL,
        "status": "estimate_only_not_executed",
        "token_usage_known": False,
        "actual_cost_known": False,
        "hard_cost_limit_guaranteed": False,
        "research_mode": "manual",
        "search_estimate": None,
        "search_tool_cost": None,
        "search_tool_cost_known": False,
        "assumed_input_tokens": {"low": in_low, "high": in_high, "known": False},
        "assumed_output_tokens": {"low": out_low, "high": MAX_OUT, "known": False},
        "estimated_cost_usd": {"low": round(cost_low, 5), "high": round(cost_high, 5)},
        "combined_high_usd": round(cost_high, 5),
        "includes_max_output_tokens": MAX_OUT,
        "model_override": MODEL,
        "thinking_level": "low",
        "note": "One-shot override estimate using official gemini-3.8-flash intro rates; search off.",
    }


def main() -> None:
    bundle = load_report_instruction_bundle("trend")
    with transaction(DB) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)
        src = conn.execute(
            "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
            (SOURCE_ID, CLIENT_ID),
        ).fetchone()
        assert src and src["status"] == "failed" and src["report_type"] == "trend"
        for keep in (12, 13, 14):
            assert (
                conn.execute(
                    "SELECT status FROM client_reports WHERE id = ?", (keep,)
                ).fetchone()["status"]
                == "failed"
            )

        snap = json.loads(src["input_snapshot_json"] or "{}")
        sources = list(snap.get("sources") or [])
        assert sources
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
        estimate = _estimate_with_rates(snap, RATES_38)
        high = float(estimate["combined_high_usd"])
        assert high <= BUDGET, f"estimate {high} > budget {BUDGET}"
        snap["execution_constraints"] = {
            "max_budget_usd": BUDGET,
            "max_output_tokens": MAX_OUT,
            "enable_google_search": False,
            "one_shot_no_retries": True,
            "no_model_switch_fallback": True,
            "model_override": MODEL,
            "thinking_level": "low",
            "structured_json": True,
            "token_rates": RATES_38,
            "cloned_from": SOURCE_ID,
            "default_env_model_unchanged": True,
        }

        version, _ = _next_version(
            conn, CLIENT_ID, "trend", int(src["period_year"]), int(src["period_month"])
        )
        now = _now()
        title = (snap.get("period") or {}).get("title_hint") or src["title"]
        if "(handmatige bronnen)" not in title:
            title = f"{title} (handmatige bronnen)"
        title = f"{title} — v{version} concept ({MODEL})"

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
                MODEL,  # intended override model recorded on prepared row
                now,
                json.dumps(snap, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                json.dumps(estimate, ensure_ascii=False),
                json.dumps(
                    [
                        f"Gekloond van #{SOURCE_ID}; eerdere failed versies behouden.",
                        f"One-shot model_override={MODEL} (AI_MODEL/.env niet gewijzigd).",
                        f"thinkingLevel=low; maxOutputTokens={MAX_OUT}; zoeken uit; structured JSON.",
                        f"Raming high USD {high} met officiële 3.8 intro-tarieven ≤ budget {BUDGET}.",
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
        pre_high = float((preview.get("estimate") or {}).get("combined_high_usd") or 99)
        assert pre_high <= BUDGET

        result = execute_report(
            conn,
            CLIENT_ID,
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

        for keep in (12, 13, 14):
            assert (
                conn.execute(
                    "SELECT status FROM client_reports WHERE id = ?", (keep,)
                ).fetchone()["status"]
                == "failed"
            )
        assert (
            conn.execute(
                "SELECT linked_trend_report_id FROM client_reports WHERE id = 11"
            ).fetchone()[0]
            in (None, "")
        )

        if report["status"] == "completed":
            body = {
                **body,
                "partial": True,
                "fully_researched": False,
                "human_review_required": True,
                "ai_concept_partial": True,
                "not_approved": True,
                "not_linked_to_client_report": True,
                "do_not_auto_link_client_report_11": True,
                "model": MODEL,
                "thinking_level": "low",
                "prompt_version": PROMPT_VERSION,
                "cloned_from_failed_report_id": SOURCE_ID,
            }
            conn.execute(
                """
                UPDATE client_reports SET body_json = ?, updated_at = datetime('now')
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
            blob = json.dumps(body, ensure_ascii=False).lower()
            if "ahrefs" in blob and "niet onderzocht" not in blob:
                attention.append("Mogelijke Ahrefs-claim zonder honesty-marker.")
            if "projectversies" in blob or "item-alignment" in blob:
                attention.append("Mogelijke Edits-bevinding ondanks uitsluiting.")
            if body.get("fully_researched") is True:
                attention.append("fully_researched=true ondanks partieel concept.")

        out = {
            "kept_failed": [12, 13, 14],
            "new_report_id": new_id,
            "version": version,
            "status": report["status"],
            "model": MODEL,
            "thinking_level": "low",
            "prompt_version": PROMPT_VERSION,
            "preflight": {
                "budget_usd": BUDGET,
                "combined_high_usd": pre_high,
                "within_budget": True,
                "max_output_tokens": MAX_OUT,
                "rates": RATES_38,
                "enable_google_search": False,
                "structured_json": True,
                "source_count": len(sources),
                "period": period,
                "chapters_expected": bundle.get("chapter_keys"),
            },
            "http_status": body.get("http_status") or usage.get("http_status"),
            "error_code": body.get("error_code") or usage.get("error_code"),
            "error_status": body.get("error_status") or usage.get("error_status"),
            "error_text": report.get("error_text") or body.get("error") or "",
            "endpoint": body.get("endpoint") or usage.get("endpoint"),
            "retries": usage.get("retries", 0),
            "partial": body.get("partial"),
            "fully_researched": body.get("fully_researched"),
            "human_review_required": body.get("human_review_required"),
            "ai_concept_partial": body.get("ai_concept_partial"),
            "validation": body.get("validation"),
            "chapter_presence": chapter_presence,
            "citations_count": len(citations) if isinstance(citations, list) else 0,
            "citations_sample": citations[:8] if isinstance(citations, list) else [],
            "distinctions_counts": {
                k: len(v) if isinstance(v, list) else (1 if v else 0)
                for k, v in (distinctions or {}).items()
            },
            "unassessable": body.get("unassessable"),
            "usage": usage,
            "raw_response_chars": len(str(body.get("raw_response") or "")),
            "attention_points": attention,
            "r11_linked": False,
            "env_model_unchanged": True,
            "reopen_ok": reopened["report"]["id"] == new_id
            and reopened["report"]["status"] == report["status"],
            "click_path": [
                "Dashboard → Red Rock → Rapporten",
                f"Open trendrapport #{new_id}",
                "Lees als partieel AI-concept (human review)",
                "Niet koppelen aan #11 tot inhoudelijke controle",
            ],
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        if chapters:
            (ROOT / "data" / "imports" / "redrock" / f"_trend{new_id}_chapters.json").write_text(
                json.dumps(
                    {
                        "report_id": new_id,
                        "model": MODEL,
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
                    "model": MODEL,
                    "http_status": out["http_status"],
                    "error": (out["error_text"] or "")[:180],
                    "tokens": {
                        "prompt": usage.get("prompt_tokens"),
                        "completion": usage.get("completion_tokens"),
                        "thoughts": usage.get("thoughts_tokens"),
                        "billed_output": usage.get("billed_output_tokens"),
                    },
                    "cost_usd": usage.get("actual_cost_usd"),
                    "validation": (body.get("validation") or {}).get("usable"),
                    "attention_n": len(attention),
                    "out": str(OUT),
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
