"""Patch Frankwatching source on trend #12 after HTTP 403: store free-read excerpt. No AI."""

from __future__ import annotations

import json
from pathlib import Path

from maaike.db import transaction
from maaike.migrate import apply_migrations
from maaike.report_execute import execution_preview
from maaike.reports import ensure_report_tables, get_report

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
LIVE_DB = ROOT / "data" / "maaike_redrock.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_trend_prep_sept_nov_2026.json"
REPORT_ID = 12
CLIENT_ID = 1
FW_URL = "https://www.frankwatching.com/archive/2026/03/26/linkedin-bereik-strategie/"

# Excerpt from free WebFetch (Cursor) after requests GET returned HTTP 403.
FW_EXCERPT = """
LinkedIn kiest voor mensen boven bedrijfspagina’s (Frankwatching, 26 mrt 2026, Marjolein Bongers).
Bedrijfspagina’s bereiken organisch vaak slechts 2–6% van hun volgers (soms 1–2%).
Persoonlijke profielen presteren beter; content via medewerkers tot ~561% meer bereik vs bedrijfspagina.
Algoritme beloont inhoudelijke reacties, discussies, dwell time en vervolginteractie.
360Brew: focus op gesprekken/interactie tussen mensen; persoonlijke verhalen hoger gewaardeerd dan bedrijfsupdates.
Employee advocacy: content door medewerkers 5–10× meer engagement dan via bedrijfspagina (reposts weinig bereik).
AFWIJKING: publicatie vóór lookback 21 aug–20 sep 2026 — structurele context, geen ‘nieuwe update’ in het venster.
""".strip()


def main() -> None:
    with transaction(LIVE_DB) as conn:
        apply_migrations(conn)
        ensure_report_tables(conn)
        row = conn.execute(
            "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
            (REPORT_ID, CLIENT_ID),
        ).fetchone()
        assert row and row["report_type"] == "trend" and row["status"] == "prepared"
        snap = json.loads(row["input_snapshot_json"] or "{}")
        sources = list(snap.get("sources") or [])
        patched = False
        for src in sources:
            if FW_URL in str(src.get("url") or ""):
                src["excerpt"] = FW_EXCERPT[:3500]
                src["fetch_status"] = "http_403_manual_excerpt"
                src["content_fetched"] = False
                src["counted_as_read_source"] = True
                src["fetch_error"] = "HTTP 403 via requests; excerpt from free WebFetch alternative"
                src["limitations"] = (
                    (src.get("limitations") or "")
                    + " HTTP GET 403; gelezen via alternatieve kosteloze fetch, niet via dashboard-HTTP."
                ).strip()
                src["content_chars"] = len(FW_EXCERPT)
                patched = True
                break
        assert patched, "Frankwatching source not found on report 12"

        read_n = sum(1 for s in sources if s.get("counted_as_read_source") or s.get("content_fetched"))
        unread_n = sum(
            1 for s in sources if s.get("url") and not (s.get("counted_as_read_source") or s.get("content_fetched"))
        )
        drop_markers = (
            "handmatige bronnen",
            "geen gelezen",
            "no manual sources",
            "bron(nen) zonder opgehaalde",
            "sources added yet",
        )
        missing = [
            m
            for m in (snap.get("missing") or [])
            if not any(marker in m.lower() for marker in drop_markers)
        ]
        if unread_n:
            missing.append(f"{unread_n} bron(nen) zonder opgehaalde inhoud.")
        snap["sources"] = sources
        snap["missing"] = missing
        snap["partial"] = bool(missing)
        snap["source_read_summary"] = {"total": len(sources), "read": read_n, "url_only_unread": unread_n}
        snap["context_preview"] = {
            **(snap.get("context_preview") or {}),
            "manual_source_count": len(sources),
            "sources_read": read_n,
        }

        fw_src = next(s for s in sources if FW_URL in str(s.get("url") or ""))
        conn.execute(
            """
            UPDATE client_report_sources SET
                excerpt = ?, fetch_status = ?, content_fetched = 0,
                limitations = ?, historical_ok = 0, meta_json = ?
            WHERE report_id = ? AND url = ?
            """,
            (
                FW_EXCERPT[:3500],
                "http_403_manual_excerpt",
                fw_src.get("limitations") or "",
                json.dumps(
                    {
                        "counted_as_read_source": True,
                        "fetch_status": "http_403_manual_excerpt",
                        "fetch_error": "HTTP 403; free WebFetch excerpt",
                    },
                    ensure_ascii=False,
                ),
                REPORT_ID,
                FW_URL,
            ),
        )
        conn.execute(
            """
            UPDATE client_reports SET
                input_snapshot_json = ?,
                sources_json = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                json.dumps(snap, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                REPORT_ID,
            ),
        )

        # Isolation: other client must not see this report
        other = conn.execute(
            "SELECT id FROM clients WHERE id != ? LIMIT 1", (CLIENT_ID,)
        ).fetchone()
        isolation = {"other_client_id": None, "blocked": True}
        if other:
            isolation["other_client_id"] = int(other["id"])
            try:
                get_report(conn, int(other["id"]), REPORT_ID)
                isolation["blocked"] = False
            except ValueError:
                isolation["blocked"] = True

        r11 = conn.execute(
            "SELECT linked_trend_report_id, status FROM client_reports WHERE id = 11"
        ).fetchone()
        preview = execution_preview(conn, CLIENT_ID, REPORT_ID, max_budget_usd=2.0)
        detail = get_report(conn, CLIENT_ID, REPORT_ID)
        sources_out = (detail["report"].get("input_snapshot") or {}).get("sources") or []

        # Merge into existing prep JSON
        base = {}
        if OUT.exists():
            base = json.loads(OUT.read_text(encoding="utf-8"))
        base["sources_summary"] = {
            "total": len(sources_out),
            "actually_read": sum(
                1 for s in sources_out if s.get("counted_as_read_source") or s.get("content_fetched")
            ),
            "url_only_or_failed": sum(
                1
                for s in sources_out
                if not (s.get("counted_as_read_source") or s.get("content_fetched"))
            ),
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
                for s in sources_out
                if s.get("counted_as_read_source") or s.get("content_fetched")
            ],
            "not_read": [
                {
                    "title": s.get("title"),
                    "url": s.get("url"),
                    "fetch_status": s.get("fetch_status"),
                    "error": s.get("fetch_error"),
                }
                for s in sources_out
                if not (s.get("counted_as_read_source") or s.get("content_fetched"))
            ],
        }
        base["missing_source_layers"] = [
            "Ahrefs (volumes/concurrentie) — Niet onderzocht / onvoldoende gegevens",
            "AnswerThePublic — Niet onderzocht / onvoldoende gegevens",
            "Google Trends ruwe export/CSV — niet als bestand opgeslagen (wel sectorproxies Woonhype/Wonen360)",
            "Social Media Today — niet in gelezen set",
            "Outdoor/zonwering-specifieke bron in lookback — niet hard gelezen (wooncontext via Woonhype/Wonen360)",
        ]
        base["execution_preview"] = {
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
            "prompt_package_system_chars": (preview.get("prompt_package") or {}).get("system_chars"),
            "checklist": preview.get("model_input_checklist"),
            "prompt_preview_head": ((preview.get("prompt_package") or {}).get("system_text_preview") or "")[
                :800
            ],
        }
        base["local_checks"] = {
            "report_status_prepared": detail["report"]["status"] == "prepared",
            "is_mock": bool(detail["report"].get("is_mock")),
            "client_report_11_unlinked": r11["linked_trend_report_id"] in (None, ""),
            "client_isolation_other_blocked": isolation["blocked"],
            "isolation_detail": isolation,
            "no_paid_ai": True,
            "edits_instagram_short_excerpt_chars": next(
                (
                    len(s.get("excerpt") or "")
                    for s in sources_out
                    if "workflow-editing" in str(s.get("url") or "")
                ),
                None,
            ),
            "edits_note": (
                "creators.instagram.com/blog/workflow-editing leverde slechts ~9 tekens via HTTP "
                "(waarschijnlijk JS-shell); bevinding steunt op WebSearch-snippet + titel, niet op volle paginatekst."
            ),
        }
        OUT.write_text(json.dumps(base, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "read": base["sources_summary"]["actually_read"],
                    "failed": base["sources_summary"]["url_only_or_failed"],
                    "missing": preview.get("missing"),
                    "r11_unlinked": base["local_checks"]["client_report_11_unlinked"],
                    "isolation_ok": isolation["blocked"],
                    "within_budget": preview.get("within_budget"),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
