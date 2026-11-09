"""Audit trend #15 vs local instructions + stored sources. Does not modify the report."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from maaike.db import connect
from maaike.migrate import apply_migrations
from maaike.report_prompts import load_report_instruction_bundle

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_demo_trend15_audit.json"


def main() -> None:
    bundle = load_report_instruction_bundle("trend")
    conn = connect(DB)
    apply_migrations(conn)
    row = conn.execute("SELECT * FROM client_reports WHERE id = 15 AND client_id = 1").fetchone()
    assert row and row["report_type"] == "trend"
    body = json.loads(row["body_json"] or "{}")
    snap = json.loads(row["input_snapshot_json"] or "{}")
    sources = list(snap.get("sources") or [])
    period = snap.get("period") or {}
    chapters = body.get("chapters") if isinstance(body.get("chapters"), dict) else {}
    citations = body.get("claims_with_citations") or []
    unassessable = body.get("unassessable") or []
    distinctions = body.get("distinctions") or {}

    required_keys = bundle.get("chapter_keys") or []
    points = []

    # Period
    period_ok = (
        period.get("run_year") == 2026
        and period.get("run_month") == 9
        and period.get("lookback_start") == "2026-08-21"
        and period.get("lookback_end") == "2026-09-20"
        and period.get("planning_year") == 2026
        and period.get("planning_month") == 11
    )
    points.append(
        {
            "topic": "Periode (terugblik 21aug–20sep / planning nov / run sep)",
            "status": "ok" if period_ok else "needs_fix",
            "detail": period,
        }
    )

    # Chapters
    missing_ch = [k for k in required_keys if not str(chapters.get(k) or "").strip()]
    points.append(
        {
            "topic": "Verplichte hoofdstukken",
            "status": "ok" if not missing_ch else "needs_fix",
            "detail": {"present": {k: bool(str(chapters.get(k) or "").strip()) for k in required_keys}, "missing": missing_ch},
        }
    )

    # Bronoverzicht / citations
    source_urls = {str(s.get("url") or "").strip() for s in sources if isinstance(s, dict)}
    cite_urls = [str(c.get("source_url") or "").strip() for c in citations if isinstance(c, dict)]
    cite_ok = [u for u in cite_urls if u in source_urls or any(u.startswith(su) or su.startswith(u) for su in source_urls if su)]
    orphan_cites = [u for u in cite_urls if u not in cite_ok]
    # soft match hosts
    source_hosts = {urlparse(u).netloc.replace("www.", "") for u in source_urls if u}
    soft_ok = []
    still_orphan = []
    for u in orphan_cites:
        host = urlparse(u).netloc.replace("www.", "")
        if host and host in source_hosts:
            soft_ok.append(u)
        else:
            still_orphan.append(u)

    points.append(
        {
            "topic": "Bronverwijzingen (claims_with_citations vs opgeslagen bronnen)",
            "status": "ok" if not still_orphan and cite_urls else ("needs_fix" if still_orphan else "missing_data"),
            "detail": {
                "citations_n": len(cite_urls),
                "exact_or_prefix_match": len(cite_ok),
                "host_match": soft_ok,
                "orphan": still_orphan,
                "stored_sources_n": len(sources),
            },
        }
    )

    # Source roles / honesty
    blob = json.dumps(body, ensure_ascii=False).lower()
    ahrefs_honest = "ahrefs" in blob and ("niet onderzocht" in blob or "onvoldoende" in blob)
    edits_excluded = "edits" in " ".join(unassessable).lower() or "edits" in blob
    frankwatching_bg = "frankwatching" in blob and ("achtergrond" in blob or "maart 2026" in blob)
    woonhype_proxy = "woonhype" in blob and ("wikipedia" in blob or "proxy" in blob or "interesse" in blob)
    wonen360_uncertain = "wonen360" in blob and ("onzeker" in blob or "datum" in blob)

    points.append(
        {
            "topic": "Ahrefs/zoekvolumes niet verzonnen",
            "status": "ok" if ahrefs_honest else "needs_fix",
            "detail": "Honesty markers in unassessable/chapters" if ahrefs_honest else "Missing honesty marker",
        }
    )
    points.append(
        {
            "topic": "Edits uitgesloten als bewijs",
            "status": "ok" if edits_excluded else "needs_fix",
            "detail": [u for u in unassessable if "edit" in u.lower()],
        }
    )
    points.append(
        {
            "topic": "Frankwatching als achtergrond (pre-lookback)",
            "status": "ok" if frankwatching_bg else "needs_fix",
            "detail": "March 2026 LinkedIn claim labeled as background/historical",
        }
    )
    points.append(
        {
            "topic": "Woonhype als Wikipedia-interesseproxy",
            "status": "ok" if woonhype_proxy else "needs_fix",
            "detail": "Percentages must not be treated as Ahrefs volumes",
        }
    )
    points.append(
        {
            "topic": "Wonen360 datum-onzekerheid",
            "status": "ok" if wonen360_uncertain else "needs_fix",
            "detail": "Background with uncertain date",
        }
    )

    # Partial / not fully researched
    points.append(
        {
            "topic": "Partieel concept-flags",
            "status": "ok"
            if body.get("partial") and body.get("fully_researched") is False and body.get("human_review_required")
            else "needs_fix",
            "detail": {
                "partial": body.get("partial"),
                "fully_researched": body.get("fully_researched"),
                "human_review_required": body.get("human_review_required"),
                "not_linked_to_client_report": body.get("not_linked_to_client_report"),
            },
        }
    )

    # Distinctions
    points.append(
        {
            "topic": "Onderscheid facts / trends / suggestions",
            "status": "ok"
            if all(isinstance(distinctions.get(k), list) and distinctions.get(k) for k in ("facts", "trends", "suggestions"))
            else "needs_fix",
            "detail": {k: len(distinctions.get(k) or []) for k in ("facts", "trends", "suggestions")},
        }
    )

    # Content quality flags (human attention, not auto-fail)
    attention = []
    if "augustus 2026" in blob and period.get("lookback_start") == "2026-08-21":
        attention.append(
            "Woonhype-cijfers verwijzen naar augustus-2026 Wikipedia-proxy; deels vóór lookback-start 21 aug — als proxy-signaal OK, niet als lookback-feiten presenteren zonder voorbehoud."
        )
    if "meta one" in blob and "15 september" in blob:
        attention.append("Meta One 15 sep ligt binnen lookback tot 20 sep — OK indien bron in snapshot.")
    if still_orphan:
        attention.append(f"Citations zonder opgeslagen bron-URL: {still_orphan}")
    attention.append(
        "Geen Ahrefs/Google Trends/ATP/Social Media Today — zoekclusters zijn hypotheses; conclusie erkent dit."
    )
    attention.append("Origineel #15 niet gewijzigd; blijft partieel concept voor menselijke controle.")

    # Link-to-#11 recommendation
    allow_link = period_ok and not missing_ch and ahrefs_honest and body.get("partial")
    link_advice = (
        "Mag als partiële trend-input aan QA-klantrapport #11 gekoppeld worden, met expliciete warning dat het niet fully_researched is."
        if allow_link
        else "Niet koppelen tot correcties."
    )

    out = {
        "report_id": 15,
        "original_untouched": True,
        "prompt_version": row["prompt_version"],
        "model": row["model"],
        "instruction_file": "data/imports/redrock/social_agent/Trendrapport - opbouw en aanpak.txt",
        "chapter_keys_expected": required_keys,
        "points": points,
        "attention_for_humans": attention,
        "link_to_client_11_advice": link_advice,
        "allow_partial_link": allow_link,
        "summary_counts": {
            "ok": sum(1 for p in points if p["status"] == "ok"),
            "needs_fix": sum(1 for p in points if p["status"] == "needs_fix"),
            "missing_data": sum(1 for p in points if p["status"] == "missing_data"),
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), **out["summary_counts"], "allow_partial_link": allow_link}, indent=2))


if __name__ == "__main__":
    main()
