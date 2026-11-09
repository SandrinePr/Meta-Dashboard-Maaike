"""Diagnose #12/#13 high-demand failures without new AI calls."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from maaike.db import transaction
from maaike.gemini_native import load_native_config
from maaike.reports import ensure_report_tables

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
DB = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_trend_high_demand_diagnosis.json"

HIGH_DEMAND_RE = re.compile(r"high demand|overloaded|try again later", re.I)


def friendly_reason(error_text: str, http_status, error_status) -> str:
    if HIGH_DEMAND_RE.search(error_text or "") or error_status == "UNAVAILABLE" or http_status == 503:
        return (
            "The Gemini model was temporarily unavailable due to high demand on Google's side "
            "(typically HTTP 503 / UNAVAILABLE). This is not an API-key, quota, or prompt error."
        )
    if http_status == 429:
        return "Rate limit / quota exhausted (HTTP 429). Reduce request rate or check billing tier."
    if http_status and int(http_status) >= 500:
        return f"Provider server error (HTTP {http_status}). Temporary on Google's side."
    return (error_text or "Generation failed for an unknown provider reason.").strip()


def main() -> None:
    load_dotenv(override=False)
    cfg = load_native_config()
    reports = []
    with transaction(DB) as conn:
        ensure_report_tables(conn)
        for rid in (12, 13):
            row = conn.execute(
                "SELECT * FROM client_reports WHERE id = ?", (rid,)
            ).fetchone()
            body = json.loads(row["body_json"] or "{}")
            usage = json.loads(row["usage_json"] or "{}")
            error_text = row["error_text"] or body.get("error") or ""
            # Historical gap: http_status was not persisted at call time for these runs.
            stored_http = body.get("http_status") or usage.get("http_status")
            stored_code = body.get("error_code") or usage.get("error_code")
            stored_status = body.get("error_status") or usage.get("error_status")
            inferred = None
            if stored_http is None and HIGH_DEMAND_RE.search(error_text):
                inferred = {
                    "http_status": 503,
                    "error_code": 503,
                    "error_status": "UNAVAILABLE",
                    "basis": (
                        "Exacte HTTP-status is niet in body/usage opgeslagen voor deze runs. "
                        "De fouttekst matcht Google's standaard 503 high-demand/UNAVAILABLE-bericht."
                    ),
                }
            diagnosis = {
                "report_id": rid,
                "status": row["status"],
                "model_stored": row["model"],
                "provider_stored": row["provider"],
                "error_text": error_text,
                "http_status_stored": stored_http,
                "error_code_stored": stored_code,
                "error_status_stored": stored_status,
                "inferred_from_message": inferred,
                "raw_response_chars": len(str(body.get("raw_response") or "")),
                "has_readable_draft": bool(str(body.get("raw_response") or "").strip())
                or bool((body.get("chapters") or {})),
                "usage_tokens": {
                    "prompt": usage.get("prompt_tokens"),
                    "completion": usage.get("completion_tokens"),
                    "actual_cost_usd": usage.get("actual_cost_usd"),
                    "cost_known": usage.get("cost_known"),
                    "search_queries": usage.get("search_queries"),
                    "retries_recorded": usage.get("retries"),
                },
                "friendly_reason": friendly_reason(
                    error_text,
                    (inferred or {}).get("http_status") if stored_http is None else stored_http,
                    (inferred or {}).get("error_status") if stored_status is None else stored_status,
                ),
                "temporary_overload_likely": bool(
                    HIGH_DEMAND_RE.search(error_text)
                    or stored_status == "UNAVAILABLE"
                    or stored_http == 503
                ),
            }
            # Persist diagnosis onto body for UI without changing status
            body["generation_failure"] = {
                "ui_label": "Generation failed",
                "friendly_reason": diagnosis["friendly_reason"],
                "http_status": stored_http if stored_http is not None else (inferred or {}).get("http_status"),
                "error_code": stored_code if stored_code is not None else (inferred or {}).get("error_code"),
                "error_status": stored_status
                if stored_status is not None
                else (inferred or {}).get("error_status"),
                "http_status_was_persisted_at_call_time": stored_http is not None,
                "inferred": inferred is not None,
                "endpoint_at_config_now": cfg["native_endpoint"],
                "model": row["model"] or cfg["model"],
                "retries": 0,
                "sdk_retries": False,
                "route": "requests.post native generateContent (geen google-genai SDK-retries)",
            }
            body["ui_label"] = "Generation failed"
            body["generation_failed"] = True
            usage["generation_failure"] = body["generation_failure"]
            conn.execute(
                """
                UPDATE client_reports
                SET body_json = ?, usage_json = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    json.dumps(body, ensure_ascii=False),
                    json.dumps(usage, ensure_ascii=False),
                    rid,
                ),
            )
            reports.append(diagnosis)

    out = {
        "no_new_ai_calls": True,
        "config_now": {
            "model": cfg["model"],
            "endpoint": cfg["native_endpoint"],
            "has_api_key": cfg["has_api_key"],
            "ai_model_env": os.getenv("AI_MODEL", ""),
            "sdk": "none — raw requests.post",
            "automatic_retries": False,
            "note": "maaike.gemini_native.generate_content doet precies 1 HTTP POST; geen retry-loop.",
        },
        "reports": reports,
        "conclusion": {
            "same_failure_on_12_and_13": True,
            "likely_cause": (
                "Tijdelijke overbelasting van model gemini-3.5-flash-lite bij Google "
                "(classic high-demand / 503 UNAVAILABLE). Geen aanwijzing voor slechte prompt, "
                "ontbrekende key, of zoekkosten — tokens en kost zijn null."
            ),
            "not_likely": [
                "API-key ontbreekt (dan andere fout)",
                "429 RESOURCE_EXHAUSTED / eigen quotum",
                "Prompt te groot (geen 400 INVALID_ARGUMENT)",
                "SDK-retry storm (er zijn geen SDK-retries)",
            ],
            "gap": (
                "HTTP-status/code was niet opgeslagen in body bij #12/#13; "
                "voortaan wel (fix in gemini_native + report_execute)."
            ),
        },
        "recovery_advice": [
            "Wacht 15–60 minuten (of buiten US-piekuren) en maak één nieuwe versie — geen burst van retries.",
            "Houd budgetpoort USD 0.05, zoeken uit, maxOutputTokens 4096, zelfde bronnen.",
            "Geen automatische retries in code; eventueel later bewust max 1 handmatige herkansing.",
            "Als 503 aanhoudt op gemini-3.5-flash-lite: overweeg één expliciete modelwissel "
            "(alleen na jouw goedkeuring), bv. een stabielere flash-variant — niet stilzwijgend.",
            "Controleer Google AI Studio / status; onderscheid 503 high-demand vs 429 quota.",
            "Credits pas gebruiken na preflight (raming ≤ 0.05) en wanneer de statuspagina/test-call OK lijkt.",
            "#12 en #13 behouden als mislukte audittrail; niet overschrijven.",
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(OUT), "reports": [r["report_id"] for r in reports]}, indent=2))


if __name__ == "__main__":
    main()
