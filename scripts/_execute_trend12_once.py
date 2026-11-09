"""One-shot paid execute of trend #12. No retries. No search. No #11 link."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.db import transaction
from maaike.migrate import apply_migrations
from maaike.report_execute import execute_report, execution_preview
from maaike.report_prompts import load_report_instruction_bundle
from maaike.reports import ensure_report_tables, get_report

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
DB = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_trend12_execute_once.json"
BUDGET = 0.05
REPORT_ID = 12
CLIENT_ID = 1


def _patch_sources(sources: list[dict]) -> list[dict]:
    out = []
    for s in sources:
        item = dict(s)
        url = str(item.get("url") or "")
        if "wonen360.nl" in url:
            item["usable_for_findings"] = "background_only"
            item["source_role"] = "background_uncertain_date"
            item["read_depth"] = "partial_uncertain_publication"
            item["historical_ok"] = False
            item["certainty"] = "achtergrond — publicatiedatum onzeker"
            item["limitations"] = (
                "ACHTERGROND: publicatiedatum niet hard vastgesteld. "
                "Niet als bewezen ontwikkeling binnen terugblik 21 aug–20 sep 2026. "
                "Geen Ahrefs; geen verzonnen volumes."
            )
            item["supported_finding"] = (
                "Achtergrondsignaal (datum onzeker): design/japandi vs industrieel in "
                "NL zitmeubel-zoekgedrag — niet venster-bewezen."
            )
            ex = item.get("excerpt") or ""
            if not ex.startswith("[ACHTERGROND"):
                item["excerpt"] = "[ACHTERGROND / PUBLICATIEDATUM ONZEKER] " + ex
        if "woonhype.nl" in url:
            item["certainty"] = (
                "Wikipedia-/YouTube-interesseproxy (Woonhype) — géén zoekvolume/Ahrefs/marktvraag"
            )
            lim = item.get("limitations") or ""
            note = (
                " Woonhype-cijfers zijn Wikipedia-interesseproxy, niet Google-zoekvolume "
                "en niet marktvraag."
            )
            if "Wikipedia-interesseproxy" not in lim:
                item["limitations"] = (lim + note).strip()
        if "workflow-editing" in url or item.get("source_role") == "unusable":
            item["usable_for_findings"] = False
            item["source_role"] = "unusable"
            item["counted_as_read_source"] = False
            item["supported_finding"] = None
        out.append(item)
    return out


def main() -> None:
    bundle = load_report_instruction_bundle("trend")
    with transaction(DB) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)
        row = conn.execute(
            "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
            (REPORT_ID, CLIENT_ID),
        ).fetchone()
        assert row and row["status"] == "prepared", f"expected prepared, got {row and row['status']}"
        snap = json.loads(row["input_snapshot_json"] or "{}")
        sources = _patch_sources(list(snap.get("sources") or []))
        snap["sources"] = sources
        snap["max_budget_usd"] = BUDGET
        snap["partial"] = True
        snap["research_mode"] = "manual"
        snap["labels"] = {
            **(snap.get("labels") or {}),
            "explicit_partial_trend_concept": True,
            "no_invented_ahrefs_or_volumes": True,
            "edits_excluded_as_evidence": True,
            "frankwatching_background_only": True,
            "wonen360_background_uncertain_date": True,
            "woonhype_wikipedia_interest_proxy": True,
        }
        snap["missing"] = [
            "Ahrefs — Niet onderzocht / onvoldoende gegevens",
            "AnswerThePublic — Niet onderzocht / onvoldoende gegevens",
            "Google Trends ruwe export — Niet onderzocht / onvoldoende gegevens",
            "Edits workflow — onbruikbaar fragment, uitgesloten als bewijs",
            "Social Media Today — Niet onderzocht / onvoldoende gegevens",
        ]
        snap["execution_constraints"] = {
            "max_budget_usd": BUDGET,
            "max_output_tokens": 4096,
            "enable_google_search": False,
            "one_shot_no_retries": True,
            "dry_run_paid": False,
        }
        conn.execute(
            """
            UPDATE client_reports
            SET input_snapshot_json = ?, sources_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                json.dumps(snap, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                REPORT_ID,
            ),
        )

        preview = execution_preview(conn, CLIENT_ID, REPORT_ID, max_budget_usd=BUDGET)
        assert preview["paid_call"] is False
        assert preview["enable_google_search"] is False
        assert preview["within_budget"] is True, preview.get("budget_note")
        high = float((preview.get("estimate") or {}).get("combined_high_usd") or 99)
        assert high <= BUDGET, f"estimate {high} > budget {BUDGET}"
        out_tokens = (preview.get("estimate") or {}).get("assumed_output_tokens") or {}
        assert int(out_tokens.get("high") or 0) <= 4096

        pre = {
            "within_budget": preview["within_budget"],
            "budget_usd": BUDGET,
            "combined_high_usd": high,
            "assumed_output_tokens": out_tokens,
            "max_output_tokens_execute": 4096,
            "enable_google_search": False,
            "instruction_chapters": bundle["chapters"],
            "period": snap.get("period"),
        }

        # ONE generation attempt — no retry wrapper
        result = execute_report(
            conn,
            CLIENT_ID,
            REPORT_ID,
            max_budget_usd=BUDGET,
            dry_run_paid=False,
        )

        report = result["report"]
        # Ensure #11 untouched
        r11 = conn.execute(
            "SELECT linked_trend_report_id, status FROM client_reports WHERE id = 11"
        ).fetchone()
        assert r11["linked_trend_report_id"] in (None, "")

        # Re-open check
        reopened = get_report(conn, CLIENT_ID, REPORT_ID)
        assert reopened["report"]["id"] == REPORT_ID
        assert reopened["report"]["status"] == report["status"]

        body = report.get("body") or {}
        usage = report.get("usage") or {}
        period = (report.get("input_snapshot") or {}).get("period") or {}
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
        chapter_presence = {
            k: bool(str(chapters.get(k) or "").strip()) for k in required
        }
        distinctions = body.get("distinctions") if isinstance(body.get("distinctions"), dict) else {}
        citations = body.get("claims_with_citations") or []

        attention = []
        if period.get("planning_month") != 11 or period.get("planning_year") != 2026:
            attention.append("Planning november 2026 ontbreekt/afwijkend in snapshot.")
        if period.get("lookback_start") != "2026-08-21" or period.get("lookback_end") != "2026-09-20":
            attention.append("Terugblikperiode wijkt af van 21 aug–20 sep 2026.")
        for k, present in chapter_presence.items():
            if not present:
                attention.append(f"Hoofdstuk ontbreekt/leeg: {k}")
        if not citations:
            attention.append("Geen claims_with_citations in body.")
        if body.get("fully_researched") is True:
            attention.append("fully_researched staat true — zou false moeten zijn (partieel).")
        raw = str(body.get("raw_response") or "")
        low = raw.lower() + json.dumps(body, ensure_ascii=False).lower()
        if "ahrefs" in low and "niet onderzocht" not in low:
            attention.append("Mogelijke Ahrefs-claim zonder 'Niet onderzocht'.")
        if "workflow-editing" in low or (
            "edits" in low and "onbruikbaar" not in low and "uitgesloten" not in low
        ):
            # soft check — flag if Edits used as positive evidence phrasing
            if "projectversies" in low or "item-alignment" in low:
                attention.append("Mogelijke Edits-bevinding ondanks uitsluiting.")
        if not distinctions.get("facts") and not distinctions.get("trends"):
            attention.append("Distinctions facts/trends lijken leeg.")

        out = {
            "no_retries": True,
            "no_search": True,
            "no_link_to_11": r11["linked_trend_report_id"] in (None, ""),
            "preflight": pre,
            "report_id": REPORT_ID,
            "status": report["status"],
            "error_text": report.get("error_text") or "",
            "partial": body.get("partial"),
            "fully_researched": body.get("fully_researched"),
            "human_review_required": body.get("human_review_required"),
            "ai_concept_partial": body.get("ai_concept_partial"),
            "period": period,
            "chapter_presence": chapter_presence,
            "distinctions_counts": {
                k: len(v) if isinstance(v, list) else (1 if v else 0)
                for k, v in (distinctions or {}).items()
            },
            "citations_count": len(citations) if isinstance(citations, list) else 0,
            "citations_sample": (citations or [])[:8],
            "unassessable": body.get("unassessable"),
            "validation": body.get("validation"),
            "usage": usage,
            "attention_points": attention,
            "reopen_ok": reopened["report"]["status"] == report["status"]
            and bool(reopened["report"].get("body")),
            "raw_response_chars": len(str(body.get("raw_response") or "")),
            "click_path": [
                "Dashboard → Red Rock → Rapporten",
                f"Open trendrapport #{REPORT_ID}",
                "Bekijk body als partieel AI-concept (human review)",
                "Niet koppelen aan klantrapport #11 zonder expliciete goedkeuring",
            ],
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        # Also dump chapters summary for human review (not full raw)
        summary_path = ROOT / "data" / "imports" / "redrock" / "_trend12_execute_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "report_id": REPORT_ID,
                    "status": report["status"],
                    "chapters": chapters,
                    "distinctions": distinctions,
                    "claims_with_citations": citations,
                    "unassessable": body.get("unassessable"),
                    "partial": body.get("partial"),
                    "fully_researched": body.get("fully_researched"),
                    "usage": usage,
                    "attention_points": attention,
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
                    "report_id": REPORT_ID,
                    "status": report["status"],
                    "partial": body.get("partial"),
                    "tokens": {
                        "prompt": usage.get("prompt_tokens"),
                        "completion": usage.get("completion_tokens"),
                    },
                    "cost_usd": usage.get("actual_cost_usd"),
                    "attention_n": len(attention),
                    "out": str(OUT),
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
