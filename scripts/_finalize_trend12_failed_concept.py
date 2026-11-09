import json
from pathlib import Path

from maaike.db import transaction
from maaike.reports import ensure_report_tables, get_report

DB = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock.db")
OUT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\imports\redrock\_trend12_execute_once.json")
SUMMARY = Path(
    r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\imports\redrock\_trend12_execute_summary.json"
)


def main() -> None:
    with transaction(DB) as conn:
        ensure_report_tables(conn)
        row = conn.execute(
            "SELECT * FROM client_reports WHERE id = 12 AND client_id = 1"
        ).fetchone()
        body = json.loads(row["body_json"] or "{}")
        usage = json.loads(row["usage_json"] or "{}")
        snap = json.loads(row["input_snapshot_json"] or "{}")
        body.update(
            {
                "partial": True,
                "fully_researched": False,
                "human_review_required": True,
                "ai_concept_partial": True,
                "not_approved": True,
                "not_linked_to_client_report": True,
                "execution_attempts": 1,
                "no_retries": True,
                "enable_google_search": False,
                "generation_failed": True,
                "raw_response": body.get("raw_response")
                or ((body.get("grounding") or {}).get("text") or ""),
                "validation": {
                    "ok": False,
                    "usable": False,
                    "user_message": row["error_text"]
                    or body.get("error")
                    or "Generatie mislukt",
                    "warnings": [
                        "Geen modeltekst ontvangen door provider high-demand error."
                    ],
                },
                "label": "Partieel AI-concept — generatie mislukt (1 poging, geen retry)",
                "source_constraints_applied": snap.get("labels") or {},
                "missing_research": snap.get("missing") or [],
                "period": snap.get("period"),
            }
        )
        usage = {
            **usage,
            "status": usage.get("status") or "failed_may_still_cost",
            "execution_attempts": 1,
            "no_retries": True,
            "preflight_combined_high_usd": 0.0163,
            "budget_usd": 0.05,
            "max_output_tokens": 4096,
            "notes": (
                (usage.get("notes") or "")
                + " Opgeslagen als partieel concept voor menselijke controle; geen tweede aanroep."
            ).strip(),
        }
        notes = json.loads(row["notes_json"] or "[]")
        notes.append(
            "1 generatiepoging mislukt (high demand). Geen retry. Geen koppeling aan #11. "
            "Partieel concept voor menselijke controle."
        )
        conn.execute(
            """
            UPDATE client_reports
            SET body_json = ?, usage_json = ?, notes_json = ?, updated_at = datetime('now')
            WHERE id = 12
            """,
            (
                json.dumps(body, ensure_ascii=False),
                json.dumps(usage, ensure_ascii=False),
                json.dumps(notes, ensure_ascii=False),
            ),
        )
        r11 = conn.execute(
            "SELECT linked_trend_report_id FROM client_reports WHERE id = 11"
        ).fetchone()
        reopened = get_report(conn, 1, 12)
        assert reopened["report"]["status"] == "failed"
        assert r11["linked_trend_report_id"] in (None, "")

    out = {
        "report_id": 12,
        "result": "failed_generation_high_demand",
        "status": "failed",
        "saved_as": "partieel AI-concept voor menselijke controle (geen goedgekeurd rapport)",
        "period": {
            "run": "2026-09",
            "lookback": "2026-08-21 t/m 2026-09-20",
            "planning": "2026-11",
        },
        "preflight": {
            "budget_usd": 0.05,
            "estimate_high_usd": 0.0163,
            "within_budget": True,
            "max_output_tokens": 4096,
            "assumed_output_high": 4000,
            "google_search": False,
        },
        "usage": usage,
        "error": row["error_text"],
        "raw_response_chars": len(body.get("raw_response") or ""),
        "validation": body["validation"],
        "r11_linked": False,
        "attempts": 1,
        "retries": 0,
        "reopen_ok": True,
        "attention_points": [
            "Generatie mislukt door provider high-demand; geen hoofdstukken geproduceerd.",
            "Raw modeltekst leeg; error + usage wel opgeslagen.",
            "Geen tweede poging (expliciet 1 shot).",
            "Bronconstraints klaar: Edits uitgesloten; Frankwatching/Wonen360 achtergrond; "
            "Woonhype=Wikipedia-proxy; Ahrefs/ATP/Trends-export ontbreken.",
            "Terugblik/planning in snapshot correct (21 aug–20 sep → nov 2026); niet in AI-body "
            "omdat body ontbreekt.",
            "Niet goedgekeurd; niet gekoppeld aan #11.",
        ],
        "click_path": [
            "Dashboard → Red Rock → Rapporten",
            "Open trendrapport #12 (status failed)",
            "Bekijk error_text, body.validation, usage_json",
            "Niet koppelen aan #11; geen auto-retry",
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "failed",
                "cost": usage.get("actual_cost_usd"),
                "r11": False,
                "saved": True,
                "reopen_ok": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
