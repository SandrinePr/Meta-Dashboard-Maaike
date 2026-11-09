"""Audit/repair trend #12 sources before execution. No paid AI."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.db import transaction
from maaike.migrate import apply_migrations
from maaike.report_execute import build_execute_model_input, execution_preview
from maaike.reports import ensure_report_tables, get_report

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
DB = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_trend12_source_audit.json"
REPORT_ID = 12
CLIENT_ID = 1
BUDGET = 0.05

THREADS_FIRST_DRAFT = {
    "title": "Instagram First Draft — officiële aankondiging (@creators op Threads)",
    "url": "https://www.threads.com/@creators/post/Dcd8qfSEbEV",
    "published_at": "2026-08-25",
    "consulted_at": "2026-11-05",
    "source_kind": "official_platform",
    "excerpt": (
        "Introducing First draft, a new way to create a Reel within the Instagram app. "
        "Simply select your clips, and with one tap, it cuts the pauses and trims down your clips, "
        "so you have a starting point to build from in seconds. Everything First draft does is "
        "reversible, you can adjust or reorder anything before moving on. It handles the early "
        "video trimming so you can focus less on technical production, and get to the creative "
        "part sooner. (creators / Threads, 25 aug 2026)"
    ),
    "supported_finding": (
        "Officiële platformaankondiging: First Draft maakt een omkeerbare startmontage van "
        "geselecteerde Reels-clips door pauzes te trimmen."
    ),
    "certainty": "bevestigd (officieel Threads @creators)",
    "limitations": "Korte aankondigingstekst; geen technische specificaties of NL-adoptiecijfers.",
    "historical_ok": True,
    "fetch_status": "manual_excerpt_official_announcement",
    "content_fetched": False,
    "counted_as_read_source": True,
    "usable_for_findings": True,
    "read_depth": "full_announcement_text",
    "development_id": "ig_first_draft",
    "source_role": "primary_official",
}


def _patch(src: dict) -> dict:
    url = str(src.get("url") or "")
    out = dict(src)

    if "workflow-editing" in url:
        out.update(
            {
                "usable_for_findings": False,
                "counted_as_read_source": False,
                "content_fetched": False,
                "read_depth": "unusable",
                "fetch_status": "unusable_thin_extract",
                "certainty": "onbruikbaar als bron",
                "supported_finding": None,
                "limitations": (
                    "ONBRUIKBAAR: HTTP-extractie leverde slechts ~9 tekens ('Instagram'). "
                    "Geen betrouwbare paginatekst. Mag geen bevindingen ondersteunen; "
                    "niet als gelezen bron tellen."
                ),
                "development_id": "ig_edits_workflow",
                "source_role": "unusable",
                "exclude_reason": "excerpt_too_thin",
            }
        )
        # Keep raw thin excerpt visible in model input with warning prefix
        thin = (out.get("excerpt") or "").strip() or "Instagram"
        out["excerpt"] = (
            f"[ONBRUIKBAAR — {len(thin)} tekens, geen bruikbare inhoud] {thin}"
        )

    elif "frankwatching.com" in url:
        out.update(
            {
                "usable_for_findings": "background_only",
                "counted_as_read_source": True,
                "read_depth": "partial_manual_excerpt",
                "historical_ok": False,
                "source_role": "background_pre_lookback",
                "development_id": "linkedin_person_first_360brew",
                "certainty": "gedeeltelijk gelezen achtergrond (vóór terugblik)",
                "limitations": (
                    "GEDEELTELIJK GELEZEN ACHTERGRONDBRON vóór terugblik (pub 26 mrt 2026; "
                    "lookback 21 aug–20 sep 2026). HTTP 403; excerpt via alternatieve kosteloze "
                    "fetch. Mag géén ‘nieuwe LinkedIn-update in het venster’ claimen; alleen "
                    "structurele context person-first / 360Brew. Geen Ahrefs."
                ),
                "supported_finding": (
                    "Achtergrond: LinkedIn beloont persoonlijke gesprekken/dwell time; "
                    "360Brew versterkt person-first t.o.v. bedrijfspagina’s (structureel, "
                    "niet venster-specifiek)."
                ),
            }
        )
        out["excerpt"] = (
            "[ACHTERGROND / PRE-LOOKBACK / GEDEELTELIJK] " + (out.get("excerpt") or "")
        )

    elif "9to5mac.com" in url or "theverge.com" in url:
        out.update(
            {
                "usable_for_findings": True,
                "read_depth": "full_press_excerpt",
                "development_id": "ig_first_draft",
                "source_role": "secondary_press_same_development",
                "limitations": (
                    (out.get("limitations") or "")
                    + " Zelfde ontwikkeling als officiële Threads-aankondiging First Draft; "
                    "niet als aparte trend tellen. Persbron, geen platformdoc."
                ).strip(),
            }
        )

    elif "meta-one-creator-plans" in url:
        out.update(
            {
                "usable_for_findings": True,
                "read_depth": "full_official_page",
                "development_id": "ig_meta_one",
                "source_role": "primary_official",
                "historical_ok": True,
            }
        )

    elif "woonhype.nl" in url:
        out.update(
            {
                "usable_for_findings": True,
                "read_depth": "full_sector_page",
                "development_id": "nl_woon_search_aug2026",
                "source_role": "sector_search_proxy",
                "certainty": "sector-proxy (Wikipedia/YouTube-interesse), géén Ahrefs/Google Ads",
                "limitations": (
                    (out.get("limitations") or "")
                    + " Geen Ahrefs-volumes; geen verzonnen Trends-export. Alleen wat de pagina "
                    "zelf claimt over zoekinteresse."
                ).strip(),
                "historical_ok": True,
            }
        )

    elif "wonen360.nl" in url:
        out.update(
            {
                "usable_for_findings": True,
                "read_depth": "full_sector_page",
                "development_id": "nl_zitmeubel_search_styles",
                "source_role": "sector_search_proxy",
                "certainty": "sector-monitor; publicatiedatum onzeker",
                "limitations": (
                    (out.get("limitations") or "")
                    + " Publicatiedatum niet hard. Geen Ahrefs. Cijfers alleen overnemen als "
                    "expliciet in gelezen fragment; anders: Niet onderzocht."
                ).strip(),
                "historical_ok": None,
            }
        )

    elif "engadget.com" in url:
        out.update(
            {
                "usable_for_findings": True,
                "read_depth": "full_press_excerpt",
                "development_id": "tiktok_comment_tools_sep2026",
                "source_role": "secondary_press",
                "limitations": (
                    (out.get("limitations") or "")
                    + " Persbron; oorspronkelijke TikTok-productblog niet als aparte gelezen "
                    "bron in deze set. Geen adoptiecijfers verzinnen."
                ).strip(),
                "historical_ok": True,
            }
        )

    else:
        out.setdefault("usable_for_findings", True)
        out.setdefault("read_depth", "unknown")

    return out


def main() -> None:
    with transaction(DB) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)
        row = conn.execute(
            "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
            (REPORT_ID, CLIENT_ID),
        ).fetchone()
        assert row and row["status"] == "prepared" and row["report_type"] == "trend"
        snap = json.loads(row["input_snapshot_json"] or "{}")
        sources = [_patch(s) for s in (snap.get("sources") or []) if isinstance(s, dict)]

        # Insert official First Draft announcement if missing
        if not any("threads.com/@creators/post/Dcd8qfSEbEV" in str(s.get("url") or "") for s in sources):
            sources.insert(0, dict(THREADS_FIRST_DRAFT))
            conn.execute(
                """
                INSERT INTO client_report_sources (
                    report_id, title, url, published_at, consulted_at, excerpt, source_kind, created_at,
                    fetch_status, content_fetched, fetched_at, supported_finding, certainty,
                    limitations, historical_ok, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, 0, NULL, ?, ?, ?, 1, ?)
                """,
                (
                    REPORT_ID,
                    THREADS_FIRST_DRAFT["title"],
                    THREADS_FIRST_DRAFT["url"],
                    THREADS_FIRST_DRAFT["published_at"],
                    THREADS_FIRST_DRAFT["consulted_at"],
                    THREADS_FIRST_DRAFT["excerpt"],
                    THREADS_FIRST_DRAFT["source_kind"],
                    THREADS_FIRST_DRAFT["fetch_status"],
                    THREADS_FIRST_DRAFT["supported_finding"],
                    THREADS_FIRST_DRAFT["certainty"],
                    THREADS_FIRST_DRAFT["limitations"],
                    json.dumps(
                        {
                            "counted_as_read_source": True,
                            "usable_for_findings": True,
                            "development_id": "ig_first_draft",
                            "source_role": "primary_official",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

        # Sync DB rows for edited sources
        for s in sources:
            if "threads.com/@creators/post/Dcd8qfSEbEV" in str(s.get("url") or ""):
                continue
            conn.execute(
                """
                UPDATE client_report_sources SET
                    excerpt = ?, fetch_status = ?, content_fetched = ?,
                    supported_finding = ?, certainty = ?, limitations = ?,
                    historical_ok = ?, meta_json = ?
                WHERE report_id = ? AND url = ?
                """,
                (
                    s.get("excerpt") or "",
                    s.get("fetch_status") or "",
                    1 if s.get("content_fetched") else 0,
                    s.get("supported_finding") or "",
                    s.get("certainty") or "",
                    s.get("limitations") or "",
                    None
                    if s.get("historical_ok") is None
                    else (1 if s.get("historical_ok") else 0),
                    json.dumps(
                        {
                            k: s.get(k)
                            for k in (
                                "counted_as_read_source",
                                "usable_for_findings",
                                "read_depth",
                                "development_id",
                                "source_role",
                                "exclude_reason",
                                "fetch_error",
                            )
                            if s.get(k) is not None
                        },
                        ensure_ascii=False,
                    ),
                    REPORT_ID,
                    s.get("url"),
                ),
            )

        usable = [
            s
            for s in sources
            if s.get("usable_for_findings") is True
            and s.get("source_role") != "unusable"
        ]
        background = [s for s in sources if s.get("usable_for_findings") == "background_only"]
        unusable = [s for s in sources if s.get("usable_for_findings") is False]

        developments = {}
        for s in sources:
            did = s.get("development_id") or "ungrouped"
            developments.setdefault(did, []).append(
                {
                    "title": s.get("title"),
                    "role": s.get("source_role"),
                    "url": s.get("url"),
                    "usable": s.get("usable_for_findings"),
                }
            )

        missing = [
            "Ahrefs — Niet onderzocht / onvoldoende gegevens (geen volumes verzinnen)",
            "AnswerThePublic — Niet onderzocht / onvoldoende gegevens",
            "Google Trends ruwe export — Niet onderzocht / onvoldoende gegevens",
            "TikTok officiële productblog voor comment-tools — niet als gelezen bron aanwezig (alleen Engadget)",
            "Edits workflow-pagina — onbruikbaar (te dun fragment)",
            "Expliciet partieel: geen volledige bronmix uit trendinstructies",
        ]
        snap["sources"] = sources
        snap["max_budget_usd"] = BUDGET
        snap["missing"] = missing
        snap["partial"] = True
        snap["labels"] = {
            **(snap.get("labels") or {}),
            "facts_vs_trends_vs_suggestions": True,
            "no_future_info_as_historical": True,
            "not_standalone_web_research": True,
            "url_saved_is_not_content_read": True,
            "explicit_partial_trend_concept": True,
            "no_invented_ahrefs_or_volumes": True,
        }
        snap["source_read_summary"] = {
            "total": len(sources),
            "usable_for_findings": len(usable),
            "background_pre_lookback": len(background),
            "unusable": len(unusable),
            "developments": list(developments.keys()),
        }
        snap["context_preview"] = {
            **(snap.get("context_preview") or {}),
            "manual_source_count": len(sources),
            "sources_usable": len(usable),
            "max_budget_usd": BUDGET,
            "explicit_partial": True,
        }
        notes = json.loads(row["notes_json"] or "[]")
        notes = [n for n in notes if "Maximumbudget" not in str(n)]
        notes.append(
            f"Maximumbudget (schattingspoort): USD {BUDGET} — handmatige bronnentest; géén harde mid-flight limiet."
        )
        notes.append(
            "Bronaudit: Edits onbruikbaar; Frankwatching = gedeeltelijke pre-lookback achtergrond; "
            "First Draft geconsolideerd met officiële Threads-aankondiging."
        )

        # Refresh estimate with updated source count
        from maaike.reports import _estimate_report

        estimate = _estimate_report("trend", snap)
        conn.execute(
            """
            UPDATE client_reports SET
                input_snapshot_json = ?,
                sources_json = ?,
                estimate_json = ?,
                notes_json = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                json.dumps(snap, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                json.dumps(estimate, ensure_ascii=False),
                json.dumps(notes, ensure_ascii=False),
                REPORT_ID,
            ),
        )

        detail = get_report(conn, CLIENT_ID, REPORT_ID)
        report = detail["report"]
        model_input = build_execute_model_input(report, report["input_snapshot"])
        preview = execution_preview(conn, CLIENT_ID, REPORT_ID, max_budget_usd=BUDGET)

        model_sources = []
        for s in model_input.get("sources") or []:
            if not isinstance(s, dict):
                continue
            model_sources.append(
                {
                    "title": s.get("title"),
                    "url": s.get("url"),
                    "published_at": s.get("published_at"),
                    "consulted_at": s.get("consulted_at"),
                    "fetch_status": s.get("fetch_status"),
                    "usable_for_findings": s.get("usable_for_findings"),
                    "read_depth": s.get("read_depth"),
                    "development_id": s.get("development_id"),
                    "source_role": s.get("source_role"),
                    "supported_finding": s.get("supported_finding"),
                    "certainty": s.get("certainty"),
                    "limitations": s.get("limitations"),
                    "historical_ok": s.get("historical_ok"),
                    "excerpt_chars": len(s.get("excerpt") or ""),
                    "exact_excerpt_in_model_input": s.get("excerpt") or "",
                }
            )

        est = preview.get("estimate") or {}
        high = est.get("combined_high_usd")
        verdict_usable = len(usable) >= 4 and any(
            s.get("development_id") == "ig_first_draft" and s.get("source_role") == "primary_official"
            for s in sources
        )

        out = {
            "no_paid_ai": True,
            "report_id": REPORT_ID,
            "status": report["status"],
            "budget_usd": BUDGET,
            "within_budget": preview.get("within_budget"),
            "budget_note": preview.get("budget_note"),
            "cost_estimate": {
                "assumed_input_tokens": est.get("assumed_input_tokens"),
                "assumed_output_tokens": est.get("assumed_output_tokens"),
                "estimated_cost_usd": est.get("estimated_cost_usd"),
                "combined_high_usd": high,
                "includes_max_output_band": True,
                "search_cost": 0,
                "fits_under_0_05": high is not None and float(high) <= BUDGET,
            },
            "developments": developments,
            "usable_count": len(usable),
            "background_count": len(background),
            "unusable_count": len(unusable),
            "missing_research_layers": missing,
            "partial_concept_verdict": {
                "enough_for_explicit_partial_trend_concept": verdict_usable,
                "reason": (
                    "Voldoende bruikbare gelezen inhoud voor een EXPLICIET PARTIEEL concept: "
                    "platformupdates (First Draft officieel + Meta One + TikTok-pers) en "
                    "NL woon/zoekproxies. Niet volledig: Ahrefs/ATP/Trends-export ontbreken; "
                    "Edits onbruikbaar; Frankwatching alleen pre-lookback achtergrond; "
                    "First Draft-pers geconsolideerd tot één ontwikkeling."
                    if verdict_usable
                    else "Te weinig bruikbare broninhoud voor zelfs een partieel concept."
                ),
                "must_not_invent": [
                    "Ahrefs-volumes",
                    "Google Trends-percentages zonder bron",
                    "NL-adoptiecijfers First Draft/Meta One/TikTok",
                    "Edits-bevindingen uit dun fragment",
                    "Frankwatching als ‘nieuwe update’ in lookbackvenster",
                ],
            },
            "sources_in_model_input": model_sources,
            "preview_paid_call": preview.get("paid_call"),
            "r11_still_unlinked": conn.execute(
                "SELECT linked_trend_report_id FROM client_reports WHERE id = 11"
            ).fetchone()["linked_trend_report_id"]
            in (None, ""),
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "usable": len(usable),
                    "background": len(background),
                    "unusable": len(unusable),
                    "budget": BUDGET,
                    "high_usd": high,
                    "fits": out["cost_estimate"]["fits_under_0_05"],
                    "partial_ok": verdict_usable,
                    "sources_in_model": len(model_sources),
                    "out": str(OUT),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
