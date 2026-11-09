"""Prepare Red Rock trend report for planning Nov 2026 (run Sep). Fetch sources, no AI."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from maaike.db import transaction
from maaike.migrate import apply_migrations
from maaike.report_execute import execution_preview
from maaike.report_metrics import trend_lookback_bounds
from maaike.report_prompts import load_report_instruction_bundle
from maaike.reports import add_trend_sources, get_report, prepare_trend_report
from maaike.gemini_native import search_capability

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
LIVE_DB = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_trend_prep_sept_nov_2026.json"

# Historical cutoff: end of lookback for run September 2026
HISTORICAL_CUTOFF = date(2026, 9, 20)

# Lookback for run Sep 2026: 2026-08-21 … 2026-09-20. Prefer sources available by then.
CANDIDATE_SOURCES = [
    {
        "title": "Instagram First Draft — automatic Reel starting edit (9to5Mac)",
        "url": "https://9to5mac.com/2026/08/26/instagram-can-now-create-reels-automatically-but-meta-doesnt-want-to-upset-creators/",
        "published_at": "2026-08-26",
        "source_kind": "platform_press",
        "supported_finding": "Instagram First Draft verkort multi-clip Reels tot een bewerkbare startmontage; iPhone-first, omkeerbaar.",
        "certainty": "bevestigd (pers + Meta-communicatie)",
        "limitations": "Feature-rollout kan regio/device beperkt zijn; geen NL-specifieke adoptiecijfers.",
        "historical_ok": True,
    },
    {
        "title": "Instagram First Draft — The Verge",
        "url": "https://www.theverge.com/tech/984463/instagram-first-draft-edit-reels",
        "published_at": "2026-08-25",
        "source_kind": "platform_press",
        "supported_finding": "Second opinion: First Draft trimt pauzes; Instagram stelt dat het geen AI-tool is.",
        "certainty": "bevestigd",
        "limitations": "Persbron, geen productdoc van Meta.",
        "historical_ok": True,
    },
    {
        "title": "Edits app workflow — project versions & alignment (Instagram for Creators)",
        "url": "https://creators.instagram.com/blog/workflow-editing/",
        "published_at": "2026-08-19",
        "source_kind": "official_platform",
        "supported_finding": "Officiële Edits-update: projectversies en item-alignment voor sneller video-editproces.",
        "certainty": "bevestigd (officieel)",
        "limitations": "1 dag vóór lookbackstart (21 aug); productupdate ≠ contenttrend; geen bereikcijfers.",
        "historical_ok": True,
    },
    {
        "title": "Meta One creator plans on Instagram (official)",
        "url": "https://creators.instagram.com/blog/meta-one-creator-plans",
        "published_at": "2026-09-15",
        "source_kind": "official_platform",
        "supported_finding": "Meta One creator-abonnementen rollen uit met professionele tools in Instagram.",
        "certainty": "bevestigd (officieel) indien pagina bereikbaar",
        "limitations": "Binnen lookback (≤20 sep); relevantie voor B2B-merken indirect.",
        "historical_ok": True,
    },
    {
        "title": "LinkedIn: mensen boven bedrijfspagina’s / 360Brew (Frankwatching)",
        "url": "https://www.frankwatching.com/archive/2026/03/26/linkedin-bereik-strategie/",
        "published_at": "2026-03-26",
        "source_kind": "trade_press",
        "supported_finding": "LinkedIn beloont persoonlijke gesprekken/dwell time; 360Brew versterkt person-first vs bedrijfspagina’s.",
        "certainty": "sterk signaal (vakpers); structureel door 2026 heen relevant",
        "limitations": "AFWIJKING: publicatie vóór lookbackvenster (21 aug–20 sep). Alleen als structurele context, niet als ‘nieuwe update’ in het venster.",
        "historical_ok": False,
    },
    {
        "title": "Woontrends augustus 2026 — wabi-sabi/linnen zoekinteresse (Woonhype)",
        "url": "https://www.woonhype.nl/trendrapport/2026-08",
        "published_at": "2026-08-01",
        "source_kind": "sector_search_interest",
        "supported_finding": "NL zoekinteresse augustus 2026: wabi-sabi/linnen/jute omhoog; rotan/hygge terug.",
        "certainty": "vroeg/sector-signaal (Wikipedia/YouTube-proxy, geen Ahrefs)",
        "limitations": "Geen Ahrefs-volumes; methodiek Wikipedia/YouTube. September-editie (na 20 sep) bewust niet gebruikt voor historische test.",
        "historical_ok": True,
    },
    {
        "title": "Zitmeubels zoekgedrag — design/japandi vs industrieel (Wonen360)",
        "url": "https://www.wonen360.nl/article/9849007/consument-zoekt-massaal-naar-designmeubelen-terwijl-industriele-woonstijl-populariteit-verliest/",
        "published_at": None,
        "source_kind": "sector_search_interest",
        "supported_finding": "NL zoekgedrag zitmeubels: design dominant; japandi sterkste groei; industrieel zwakker.",
        "certainty": "sector-monitor (zoekvolumes Markdata/monitor)",
        "limitations": "Exacte publicatiedatum niet hard in snippet; geen ruwe Google Trends/Ahrefs-export. Outdoor niet primair.",
        "historical_ok": None,
    },
    {
        "title": "TikTok voice comments + comment polls (Engadget)",
        "url": "https://www.engadget.com/2250517/tiktok-introduces-voice-comments-and-simplified-polls/",
        "published_at": "2026-09-03",
        "source_kind": "platform_press",
        "supported_finding": "TikTok rollt voice comments (≤60s) en comment-polls (≤5 opties) uit; ook Live Photo/comment carousels.",
        "certainty": "bevestigd (pers)",
        "limitations": "Feature-rollout gefaseerd; geen NL-adoptiecijfers. Community Guidelines H2 effectief 24 sep = ná lookbackeinde — niet als van kracht in dit venster claimen.",
        "historical_ok": True,
    },
]


def main() -> None:
    period = trend_lookback_bounds(2026, 9)
    search = search_capability()
    bundle = load_report_instruction_bundle("trend")

    with transaction(LIVE_DB) as conn:
        apply_migrations(conn)
        rr = conn.execute(
            "SELECT id, name FROM clients WHERE name = 'Red Rock' COLLATE NOCASE"
        ).fetchone()
        client_id = int(rr["id"])
        r11 = conn.execute(
            """
            SELECT id, title, status, period_year, period_month, planning_year, planning_month,
                   linked_trend_report_id
            FROM client_reports WHERE id = 11 AND client_id = ?
            """,
            (client_id,),
        ).fetchone()

        # Prepare new trend version — do NOT link to #11
        prepared = prepare_trend_report(
            conn,
            client_id,
            run_year=2026,
            run_month=9,
            sources=[],
            research_mode="manual",
            max_budget_usd=2.0,
        )
        report_id = int(prepared["report"]["id"])
        assert prepared["report"]["status"] == "prepared"
        assert prepared["report"].get("linked_trend_report_id") in (None, "")

        # Fetch + attach sources (HTTP only)
        with_sources = add_trend_sources(
            conn,
            client_id,
            report_id,
            CANDIDATE_SOURCES,
            fetch_content=True,
        )
        # Ensure #11 still unlinked
        still = conn.execute(
            "SELECT linked_trend_report_id FROM client_reports WHERE id = 11"
        ).fetchone()
        assert still["linked_trend_report_id"] in (None, "")

        preview = execution_preview(conn, client_id, report_id, max_budget_usd=2.0)
        detail = get_report(conn, client_id, report_id)
        sources = (detail["report"].get("input_snapshot") or {}).get("sources") or []

        read = [s for s in sources if s.get("counted_as_read_source") or s.get("content_fetched")]
        unread = [s for s in sources if not (s.get("counted_as_read_source") or s.get("content_fetched"))]

        out = {
            "no_paid_ai": True,
            "no_paid_search_execute": True,
            "client_id": client_id,
            "client_report_11": dict(r11) if r11 else None,
            "client_report_11_still_unlinked": still["linked_trend_report_id"] in (None, ""),
            "route_separation": {
                "search_sources": (
                    "Gemini native google_search grounding — alleen bij execute met "
                    "research_mode=internet; vereist AI_API_KEY. Nu NIET aangeroepen."
                ),
                "fetch_source_content": (
                    "maaike.report_source_fetch.fetch_source_url — kosteloze HTTP GET, geen AI."
                ),
                "write_report_with_ai": (
                    "report_execute.execute_report — geblokkeerd tot dry_run_paid=false; niet uitgevoerd."
                ),
                "search_capability_config_only": {
                    k: search.get(k)
                    for k in (
                        "available",
                        "model",
                        "route",
                        "missing_setting",
                        "hard_search_budget_guaranteed",
                    )
                },
            },
            "instructions": {
                "prompt_version": bundle["prompt_version"],
                "system_chars": bundle["system_chars"],
                "primary_loaded": bundle["primary_loaded"],
                "supporting_loaded": {
                    k: v.get("loaded") for k, v in (bundle.get("supporting_files") or {}).items()
                },
                "missing_instructions": bundle["missing_instructions"],
                "reaches_execute_system_prompt": True,
                "note": "Bundle wordt opnieuw geladen bij execute; prepare bewaart metadata + system_chars.",
            },
            "period": {
                **period,
                "rule": "x+2: planning = runmaand + 2",
                "for_client_report_11_planning_november": True,
                "lookback": f"{period['lookback_start']} t/m {period['lookback_end']}",
                "historical_cutoff": HISTORICAL_CUTOFF.isoformat(),
                "historical_note": (
                    "Bronnen bij voorkeur ≤ 2026-09-20. Structurele LinkedIn-context van maart 2026 "
                    "expliciet als pre-lookback gelabeld. Geen toekomstclaims als historisch."
                ),
                "marketwide": True,
                "not_client_specific_translation": True,
            },
            "trend_report": {
                "id": report_id,
                "title": detail["report"]["title"],
                "status": detail["report"]["status"],
                "research_mode": (detail["report"].get("input_snapshot") or {}).get("research_mode"),
                "max_budget_usd": 2.0,
                "is_mock": bool(detail["report"].get("is_mock")),
            },
            "sources_summary": {
                "total": len(sources),
                "actually_read": len(read),
                "url_only_or_failed": len(unread),
                "read": [
                    {
                        "title": s.get("title"),
                        "url": s.get("url"),
                        "published_at": s.get("published_at"),
                        "consulted_at": s.get("consulted_at"),
                        "fetch_status": s.get("fetch_status"),
                        "excerpt_chars": len(s.get("excerpt") or ""),
                        "supported_finding": s.get("supported_finding"),
                        "certainty": s.get("certainty"),
                        "limitations": s.get("limitations"),
                        "historical_ok": s.get("historical_ok"),
                    }
                    for s in read
                ],
                "not_read": [
                    {
                        "title": s.get("title"),
                        "url": s.get("url"),
                        "fetch_status": s.get("fetch_status"),
                        "error": s.get("fetch_error"),
                    }
                    for s in unread
                ],
            },
            "missing_source_layers": [
                "Ahrefs (volumes/concurrentie) — Niet onderzocht / onvoldoende gegevens",
                "AnswerThePublic — Niet onderzocht / onvoldoende gegevens",
                "Google Trends ruwe export/CSV — niet als bestand opgeslagen (wel sectorproxies)",
                "TikTok officiële updates in dit venster — niet apart bevestigd in gelezen set",
            ],
            "execution_preview": {
                "paid_call": preview.get("paid_call"),
                "within_budget": preview.get("within_budget"),
                "max_budget_usd": preview.get("max_budget_usd"),
                "estimate": preview.get("estimate"),
                "budget_note": preview.get("budget_note"),
                "enable_google_search": preview.get("enable_google_search"),
                "missing": preview.get("missing"),
                "sources_read_count": sum(
                    1 for s in (preview.get("sources_read") or []) if s.get("counted_as_read_source")
                ),
                "prompt_package_system_chars": (preview.get("prompt_package") or {}).get(
                    "system_chars"
                ),
                "checklist": preview.get("model_input_checklist"),
            },
            "click_path": [
                "Open Maaike dashboard → kies klant Red Rock",
                "Navigeer naar Rapporten / Reports analysis → tab Reports",
                f"Open trendrapport #{report_id} (Created in 2026-09 | For 2026-11)",
                "Klik Admin → Show execution preview (geen betaalde call)",
                "Optioneel: GET /api/clients/1/reports/{id}/model-input-preview",
                "NIET op Execute met dry_run_paid=false klikken",
            ],
            "expected_cost_one_real_execute": {
                "mode_if_manual_as_prepared": {
                    "google_search": False,
                    "token_estimate_usd": (preview.get("estimate") or {})
                    .get("estimated_cost_usd"),
                    "search_cost_usd": 0,
                    "note": "Huidige voorbereiding is manual+gelezen bronnen; execute zonder search.",
                },
                "mode_if_switched_to_internet": {
                    "google_search": True,
                    "token_estimate_plus_search_band": (
                        "Tokens zoals estimate + zoekqueries × $0.014 na gratis quota; "
                        "gratis restant onbekend → schatting toont $0 én betaald band."
                    ),
                    "budget_gate_usd": 2.0,
                },
            },
        }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "trend_report_id": report_id,
        "period": out["period"]["title_hint"] if "title_hint" in out["period"] else out["period"],
        "read": out["sources_summary"]["actually_read"],
        "failed": out["sources_summary"]["url_only_or_failed"],
        "within_budget": out["execution_preview"]["within_budget"],
        "r11_unlinked": out["client_report_11_still_unlinked"],
        "out": str(OUT),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
