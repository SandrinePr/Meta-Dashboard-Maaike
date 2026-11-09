import json
from pathlib import Path

from maaike.db import transaction
from maaike.report_execute import build_execute_model_input, execution_preview
from maaike.reports import _estimate_report, ensure_report_tables, get_report

DB = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock.db")
OUT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\imports\redrock\_trend12_source_audit.json")
BUDGET = 0.05

TT = {
    "title": "TikTok Newsroom — Voice Comments, Comment Polls, Photo Carousels",
    "url": "https://newsroom.tiktok.com/say-more-in-the-comments?lang=en",
    "published_at": "2026-09-03",
    "consulted_at": "2026-11-05",
    "source_kind": "official_platform",
    "excerpt": (
        "Say More in the Comments: Introducing Voice, Polls, and Carousels on TikTok "
        "(TikTok Newsroom).\n"
        "Voice Comments: record up to 60 seconds via mic icon; rolling out globally over "
        "next month to accounts 18+.\n"
        "Comment Polls: creators add poll on own video, up to 5 options + timeframe; "
        "available globally.\n"
        "Photo Carousel Comments: up to 9 photos; rolling out globally over next month.\n"
        "Live Photo Comments: available globally."
    ),
    "supported_finding": (
        "Officieel: TikTok introduceert voice comments (≤60s), comment-polls (≤5), "
        "photo carousel/Live Photo comments."
    ),
    "certainty": "bevestigd (TikTok Newsroom)",
    "limitations": "Geen NL-adoptiecijfers; rollout gefaseerd. Geen Ahrefs.",
    "historical_ok": True,
    "fetch_status": "manual_excerpt_official_announcement",
    "content_fetched": False,
    "counted_as_read_source": True,
    "usable_for_findings": True,
    "read_depth": "full_announcement_text",
    "development_id": "tiktok_comment_tools_sep2026",
    "source_role": "primary_official",
}


def main() -> None:
    with transaction(DB) as conn:
        ensure_report_tables(conn)
        row = conn.execute(
            "SELECT * FROM client_reports WHERE id = 12 AND client_id = 1"
        ).fetchone()
        snap = json.loads(row["input_snapshot_json"] or "{}")
        sources = list(snap.get("sources") or [])
        for s in sources:
            if "engadget.com" in str(s.get("url") or ""):
                s["source_role"] = "secondary_press_same_development"
                s["development_id"] = "tiktok_comment_tools_sep2026"
                lim = s.get("limitations") or ""
                note = " Zelfde ontwikkeling als TikTok Newsroom; niet als aparte trend tellen."
                if note.strip() not in lim:
                    s["limitations"] = (lim + note).strip()
        if not any(
            "newsroom.tiktok.com/say-more-in-the-comments" in str(s.get("url") or "")
            for s in sources
        ):
            idx = next(
                (
                    i
                    for i, s in enumerate(sources)
                    if "engadget.com" in str(s.get("url") or "")
                ),
                len(sources),
            )
            sources.insert(idx, dict(TT))
            conn.execute(
                """
                INSERT INTO client_report_sources (
                    report_id, title, url, published_at, consulted_at, excerpt, source_kind,
                    created_at, fetch_status, content_fetched, supported_finding, certainty,
                    limitations, historical_ok, meta_json
                ) VALUES (
                    12, ?, ?, ?, ?, ?, ?, datetime('now'), ?, 0, ?, ?, ?, 1, ?
                )
                """,
                (
                    TT["title"],
                    TT["url"],
                    TT["published_at"],
                    TT["consulted_at"],
                    TT["excerpt"],
                    TT["source_kind"],
                    TT["fetch_status"],
                    TT["supported_finding"],
                    TT["certainty"],
                    TT["limitations"],
                    json.dumps(
                        {
                            "counted_as_read_source": True,
                            "usable_for_findings": True,
                            "source_role": "primary_official",
                            "development_id": TT["development_id"],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        snap["sources"] = sources
        snap["max_budget_usd"] = BUDGET
        snap["partial"] = True
        est = _estimate_report("trend", snap)
        conn.execute(
            """
            UPDATE client_reports
            SET input_snapshot_json = ?, sources_json = ?, estimate_json = ?,
                updated_at = datetime('now')
            WHERE id = 12
            """,
            (
                json.dumps(snap, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                json.dumps(est, ensure_ascii=False),
            ),
        )
        detail = get_report(conn, 1, 12)
        mi = build_execute_model_input(detail["report"], detail["report"]["input_snapshot"])
        prev = execution_preview(conn, 1, 12, max_budget_usd=BUDGET)
        usable = sum(1 for s in sources if s.get("usable_for_findings") is True)
        bg = sum(1 for s in sources if s.get("usable_for_findings") == "background_only")
        un = sum(1 for s in sources if s.get("usable_for_findings") is False)
        audit = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        high = (prev.get("estimate") or {}).get("combined_high_usd")
        audit.update(
            {
                "budget_usd": BUDGET,
                "within_budget": prev["within_budget"],
                "budget_note": prev["budget_note"],
                "cost_estimate": {
                    "assumed_input_tokens": (prev.get("estimate") or {}).get(
                        "assumed_input_tokens"
                    ),
                    "assumed_output_tokens": (prev.get("estimate") or {}).get(
                        "assumed_output_tokens"
                    ),
                    "estimated_cost_usd": (prev.get("estimate") or {}).get(
                        "estimated_cost_usd"
                    ),
                    "combined_high_usd": high,
                    "includes_max_output_band": True,
                    "search_cost": 0,
                    "fits_under_0_05": high is not None and float(high) <= BUDGET,
                },
                "usable_count": usable,
                "background_count": bg,
                "unusable_count": un,
                "sources_in_model_input": [
                    {
                        "title": s.get("title"),
                        "url": s.get("url"),
                        "published_at": s.get("published_at"),
                        "usable_for_findings": s.get("usable_for_findings"),
                        "source_role": s.get("source_role"),
                        "development_id": s.get("development_id"),
                        "supported_finding": s.get("supported_finding"),
                        "certainty": s.get("certainty"),
                        "limitations": s.get("limitations"),
                        "historical_ok": s.get("historical_ok"),
                        "excerpt_chars": len(s.get("excerpt") or ""),
                        "exact_excerpt_in_model_input": s.get("excerpt") or "",
                    }
                    for s in (mi.get("sources") or [])
                ],
                "preview_paid_call": False,
            }
        )
        OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "n": len(sources),
                    "usable": usable,
                    "bg": bg,
                    "un": un,
                    "high": high,
                    "fits": audit["cost_estimate"]["fits_under_0_05"],
                    "within": prev["within_budget"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
