"""Trend- and client-report preparation, storage and mocks (no paid calls on open/reload)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from maaike.ai_status import public_ai_status
from maaike.ai_trial import OFFICIAL_RATES
from maaike.gemini_native import estimate_search_cost_usd
from maaike.report_metrics import (
    build_analysis_data_coverage,
    build_period_metrics,
    summarize_attached_ai_analyses,
    trend_lookback_bounds,
)
from maaike.report_prompts import PROMPT_VERSION, internet_search_capability, load_report_instruction_bundle
from maaike.repository import list_formats, list_hooks, list_pillars
from maaike.strategy import get_strategy


TOPIC_ANSWER_KEYS = (
    "onderwerpen",
    "topics",
    "themas",
    "thema's",
    "contentpijlers",
    "pijlers",
    "doelgroep",
    "positionering",
    "usp",
    "merk",
)

MONTHS_NL = (
    "",
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)


def month_label_nl(year: int | None, month: int | None) -> str:
    if year and month and 1 <= int(month) <= 12:
        return f"{MONTHS_NL[int(month)]} {int(year)}"
    return "—"


def suggested_client_report_title(client_name: str, year: int, month: int) -> str:
    return f"{client_name} – analyse {month_label_nl(year, month)}"


def suggested_trend_report_title(year: int, month: int) -> str:
    return f"Social trends – planning {month_label_nl(year, month)}"


def _client_name(conn, client_id: int) -> str:
    row = conn.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
    return str(row["name"] if row else f"Klant {client_id}")


def update_report_title(conn, client_id: int, report_id: int, title: str) -> dict[str, Any]:
    """Rename a report for list/detail display. No AI call."""
    ensure_report_tables(conn)
    clean = " ".join(str(title or "").split()).strip()
    if not clean:
        raise ValueError("Titel mag niet leeg zijn.")
    if len(clean) > 180:
        raise ValueError("Titel is te lang (max. 180 tekens).")
    row = conn.execute(
        "SELECT id FROM client_reports WHERE id = ? AND client_id = ?",
        (report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Rapport niet gevonden voor deze klant.")
    now = _now()
    conn.execute(
        "UPDATE client_reports SET title = ?, updated_at = ? WHERE id = ? AND client_id = ?",
        (clean, now, report_id, client_id),
    )
    return get_report(conn, client_id, report_id)


def _strategy_topics_summary(strategy: dict[str, Any]) -> dict[str, Any]:
    """Extract topic-relevant strategy snippets for trend context (not invented)."""
    answers = strategy.get("start_answers") or {}
    fields = strategy.get("strategy_fields") or {}
    picked = {}
    for key, value in {**fields, **answers}.items():
        kl = str(key).lower()
        if any(t in kl for t in TOPIC_ANSWER_KEYS) and value:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            picked[str(key)] = text[:800]
    # Always include a short list of answer keys so UI can show what was considered.
    return {
        "topic_fields": picked,
        "answer_keys_present": list(answers.keys())[:40],
        "targets_count": len(strategy.get("targets") or []),
        "has_strategy": bool(answers or fields),
    }

STATUSES = frozenset({"draft", "prepared", "running", "completed", "failed", "mock_completed"})


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def ensure_report_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS client_reports (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            period_year INTEGER NOT NULL,
            period_month INTEGER NOT NULL,
            planning_year INTEGER,
            planning_month INTEGER,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            supersedes_id INTEGER,
            prompt_version TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            prepared_at TEXT,
            executed_at TEXT,
            input_snapshot_json TEXT NOT NULL DEFAULT '{}',
            sources_json TEXT NOT NULL DEFAULT '[]',
            body_json TEXT NOT NULL DEFAULT '{}',
            estimate_json TEXT NOT NULL DEFAULT '{}',
            usage_json TEXT NOT NULL DEFAULT '{}',
            linked_trend_report_id INTEGER,
            error_text TEXT NOT NULL DEFAULT '',
            is_mock INTEGER NOT NULL DEFAULT 0,
            notes_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(supersedes_id) REFERENCES client_reports(id),
            FOREIGN KEY(linked_trend_report_id) REFERENCES client_reports(id)
        );

        CREATE TABLE IF NOT EXISTS client_report_sources (
            id INTEGER PRIMARY KEY,
            report_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            consulted_at TEXT NOT NULL,
            excerpt TEXT NOT NULL DEFAULT '',
            source_kind TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL,
            fetch_status TEXT NOT NULL DEFAULT '',
            content_fetched INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT,
            supported_finding TEXT NOT NULL DEFAULT '',
            certainty TEXT NOT NULL DEFAULT '',
            limitations TEXT NOT NULL DEFAULT '',
            historical_ok INTEGER,
            meta_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(report_id) REFERENCES client_reports(id)
        );

        CREATE INDEX IF NOT EXISTS idx_client_reports_client
            ON client_reports(client_id, report_type, period_year, period_month, version);
        """
    )
    # Upgrade older DBs
    src_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(client_report_sources)").fetchall()}
    for name, declaration in (
        ("fetch_status", "TEXT NOT NULL DEFAULT ''"),
        ("content_fetched", "INTEGER NOT NULL DEFAULT 0"),
        ("fetched_at", "TEXT"),
        ("supported_finding", "TEXT NOT NULL DEFAULT ''"),
        ("certainty", "TEXT NOT NULL DEFAULT ''"),
        ("limitations", "TEXT NOT NULL DEFAULT ''"),
        ("historical_ok", "INTEGER"),
        ("meta_json", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        if name not in src_cols:
            conn.execute(f"ALTER TABLE client_report_sources ADD COLUMN {name} {declaration}")


def _require_client(conn, client_id: int) -> None:
    row = conn.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
    if row is None:
        raise ValueError("Klant niet gevonden.")


def list_reports(conn, client_id: int, *, report_type: str | None = None) -> dict[str, Any]:
    ensure_report_tables(conn)
    _require_client(conn, client_id)
    q = """
        SELECT id, client_id, report_type, period_year, period_month, planning_year, planning_month,
               title, status, version, supersedes_id, prompt_version, provider, model,
               prepared_at, executed_at, linked_trend_report_id, error_text, is_mock,
               created_at, updated_at,
               CASE
                 WHEN json_extract(body_json, '$.partial') IN (1, '1', 'true', 'True') THEN 1
                 WHEN json_extract(body_json, '$.source_grounding.requires_human_review') IN (1, '1', 'true', 'True') THEN 1
                 ELSE 0
               END AS is_partial
        FROM client_reports
        WHERE client_id = ?
    """
    params: list[Any] = [client_id]
    if report_type:
        q += " AND report_type = ?"
        params.append(report_type)
    # Newest preparations first so a just-saved report is easy to reopen after reload.
    q += " ORDER BY COALESCE(updated_at, prepared_at, created_at) DESC, id DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    from maaike.report_review import review_summary_for_list

    for row in rows:
        summary = review_summary_for_list(conn, client_id, row)
        row["review_status"] = summary.get("review_status") or ""
        row["review_status_label"] = summary.get("review_status_label") or ""
        row["is_approved"] = bool(summary.get("is_approved"))
        row["can_review"] = bool(summary.get("can_review"))
        row["analysis_usable"] = bool(summary.get("analysis_usable"))
        row["review_execution_key"] = summary.get("execution_key") or ""
        row["is_partial"] = bool(row.get("is_partial"))
        # Voorbereiding zonder uitvoering mag nooit als goedgekeurd of AI-afgerond gelden.
        if not row.get("executed_at") or row.get("status") == "prepared":
            row["is_approved"] = False
            row["can_review"] = False
            if row.get("status") == "prepared":
                row["review_status_label"] = "No AI run"
    return {
        "client_id": client_id,
        "reports": rows,
        "internet_search": internet_search_capability(),
        "prompt_version": PROMPT_VERSION,
        "ai_status": public_ai_status(),
    }


def get_report(conn, client_id: int, report_id: int) -> dict[str, Any]:
    ensure_report_tables(conn)
    row = conn.execute(
        "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
        (report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Rapport niet gevonden voor deze klant.")
    snapshot = json.loads(row["input_snapshot_json"] or "{}")
    snap_sources = {
        str(s.get("url") or "").strip(): s
        for s in (snapshot.get("sources") or [])
        if isinstance(s, dict)
    }
    sources = []
    for r in conn.execute(
        "SELECT * FROM client_report_sources WHERE report_id = ? ORDER BY id",
        (report_id,),
    ).fetchall():
        item = dict(r)
        meta = {}
        try:
            meta = json.loads(item.get("meta_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            meta = {}
        snap_src = snap_sources.get(str(item.get("url") or "").strip()) or {}
        # Prefer snapshot/meta flags so URL-only vs gelezen bron zichtbaar blijft.
        for key in (
            "counted_as_read_source",
            "content_fetched",
            "fetch_status",
            "fetch_error",
            "supported_finding",
            "certainty",
            "limitations",
            "historical_ok",
            "content_chars",
        ):
            if item.get(key) in (None, "") and snap_src.get(key) is not None:
                item[key] = snap_src.get(key)
            if key in meta and (item.get(key) in (None, "") or key == "counted_as_read_source"):
                item[key] = meta.get(key, item.get(key))
        if item.get("content_fetched") is not None:
            item["content_fetched"] = bool(item["content_fetched"])
        if item.get("counted_as_read_source") is None:
            item["counted_as_read_source"] = bool(
                item.get("content_fetched") or (item.get("excerpt") and item.get("fetch_status") != "url_only_not_read")
            )
        sources.append(item)
    payload = {
        "report": {
            **dict(row),
            "input_snapshot": snapshot,
            "sources": sources or json.loads(row["sources_json"] or "[]"),
            "body": json.loads(row["body_json"] or "{}"),
            "estimate": json.loads(row["estimate_json"] or "{}"),
            "usage": json.loads(row["usage_json"] or "{}"),
            "notes": json.loads(row["notes_json"] or "[]"),
            "is_mock": bool(row["is_mock"]),
        },
        "internet_search": internet_search_capability(),
    }
    from maaike.client_report_view import attach_presentation_to_payload
    from maaike.report_review import attach_review_to_report_payload

    payload = attach_review_to_report_payload(conn, client_id, payload)
    return attach_presentation_to_payload(conn, client_id, payload)


def _next_version(conn, client_id: int, report_type: str, year: int, month: int) -> tuple[int, int | None]:
    row = conn.execute(
        """
        SELECT id, version FROM client_reports
        WHERE client_id = ? AND report_type = ? AND period_year = ? AND period_month = ?
        ORDER BY version DESC LIMIT 1
        """,
        (client_id, report_type, year, month),
    ).fetchone()
    if row is None:
        return 1, None
    return int(row["version"]) + 1, int(row["id"])


def _estimate_report(report_type: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Rough pre-execution estimate only; no paid call. Soft budget only — not a hard mid-flight limit."""
    # Large instruction + snapshot text; optional images not included for reports yet.
    base_in = 8000 if report_type == "trend" else 12000
    sources = len(snapshot.get("sources") or [])
    posts = int((snapshot.get("metrics") or {}).get("post_count") or 0)
    in_low = base_in + sources * 400 + posts * 80
    in_high = base_in + sources * 900 + posts * 180 + 4000
    out_low, out_high = 1500, 4000
    cost_low = (in_low / 1_000_000) * OFFICIAL_RATES["input_per_1m"] + (out_low / 1_000_000) * OFFICIAL_RATES["output_per_1m"]
    cost_high = (in_high / 1_000_000) * OFFICIAL_RATES["input_per_1m"] + (out_high / 1_000_000) * OFFICIAL_RATES["output_per_1m"]
    search = internet_search_capability()
    research_mode = (snapshot.get("research_mode") or "manual").strip()
    use_search = research_mode == "internet" and report_type == "trend" and search.get("available")
    search_estimate = estimate_search_cost_usd(2, 5) if use_search else None
    search_high = (
        float(search_estimate["estimated_search_cost_usd"]["high_if_fully_paid"]) if search_estimate else 0.0
    )
    return {
        "currency": "USD",
        "rate": OFFICIAL_RATES,
        "provider": search.get("provider") or OFFICIAL_RATES["provider"],
        "exact_model": search.get("exact_model_id") or OFFICIAL_RATES["model"],
        "status": "estimate_only_not_executed",
        "token_usage_known": False,
        "actual_cost_known": False,
        "hard_cost_limit_guaranteed": False,
        "research_mode": research_mode,
        "search_estimate": search_estimate,
        "search_tool_cost": None if not use_search else "band zie search_estimate",
        "search_tool_cost_known": False,
        "assumed_input_tokens": {"low": in_low, "high": in_high, "known": False},
        "assumed_output_tokens": {"low": out_low, "high": out_high, "known": False},
        "estimated_cost_usd": {"low": round(cost_low, 5), "high": round(cost_high, 5)},
        "combined_high_usd": round(cost_high + search_high, 5),
        "display_rule": "Onbekend verbruik of toolkosten worden niet als 0 getoond. Schatting ≠ harde limiet.",
        "failed_calls_may_still_cost": True,
        "note": (
            "No Google Search in this run (manual sources or client report)."
            if not use_search
            else (
                "Tokens + search queries: free search quota unknown → show $0 and paid band "
                f"(up to ~${search_high} at 5 queries × $0.014). No hard mid-flight limit."
            )
        ),
    }


def prepare_trend_report(
    conn,
    client_id: int,
    *,
    run_year: int,
    run_month: int,
    sources: list[dict[str, Any]] | None = None,
    research_mode: str = "manual",
    max_budget_usd: float | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    ensure_report_tables(conn)
    _require_client(conn, client_id)
    if not (1 <= run_month <= 12) or run_year < 2000:
        raise ValueError("Ongeldige runmaand.")
    mode = (research_mode or "manual").strip().lower()
    if mode not in {"manual", "internet"}:
        raise ValueError("research_mode moet 'manual' of 'internet' zijn.")
    bundle = load_report_instruction_bundle("trend")
    period = trend_lookback_bounds(run_year, run_month)
    search = internet_search_capability()
    strategy = get_strategy(conn, client_id)
    strategy_topics = _strategy_topics_summary(strategy)
    clean_sources = []
    for item in sources or []:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title and not url:
            continue
        clean_sources.append(
            {
                "title": title or (urlparse(url).netloc if url else "Bron"),
                "url": url,
                "published_at": str(item.get("published_at") or "").strip() or None,
                "consulted_at": str(item.get("consulted_at") or _now()[:10]),
                "excerpt": str(item.get("excerpt") or "").strip(),
                "source_kind": str(item.get("source_kind") or "manual"),
                # URL opslaan ≠ inhoud gelezen; handmatige excerpts tellen als gelezen tekst.
                "content_consulted": bool(str(item.get("excerpt") or "").strip()),
            }
        )

    missing = []
    if mode == "internet":
        if not search["available"]:
            missing.append(
                search.get("missing_setting")
                or "Internet research selected but AI_API_KEY/Gemini model is missing."
            )
        if not strategy_topics["has_strategy"]:
            missing.append("Client strategy largely empty — topic context limited.")
    else:
        if not clean_sources:
            missing.append("No manual sources added yet (title/URL/accessed date).")
        # Handmatige mode: zoektool niet vereist.
    if bundle["missing_instructions"]:
        missing.append("Ontbrekende instructiebestanden: " + ", ".join(bundle["missing_instructions"]))

    fully_researched_possible = (mode == "internet" and search["available"]) or bool(clean_sources)
    snapshot = {
        "report_type": "trend",
        "research_mode": mode,
        "max_budget_usd": max_budget_usd,
        "period": period,
        "instruction_bundle": {
            "prompt_version": bundle["prompt_version"],
            "primary_file": bundle["primary_file"],
            "chapters": bundle["chapters"],
            "required_sources": bundle["required_sources"],
            "system_chars": bundle["system_chars"],
            "internet_search": search,
        },
        "strategy_topics": strategy_topics,
        "context_preview": {
            "research_mode": mode,
            "enable_google_search": mode == "internet" and search["available"],
            "strategy_topic_fields": list((strategy_topics.get("topic_fields") or {}).keys()),
            "manual_source_count": len(clean_sources),
            "period_title": period.get("title_hint"),
            "web_pages_are_sources_not_instructions": True,
        },
        "sources": clean_sources,
        "missing": missing,
        "labels": {
            "facts_vs_trends_vs_suggestions": True,
            "no_future_info_as_historical": True,
            "not_standalone_web_research": not fully_researched_possible,
            "url_saved_is_not_content_read": True,
        },
        "partial": bool(missing) or not fully_researched_possible,
        "excel_or_meta_not_required": True,
    }
    estimate = _estimate_report("trend", snapshot)
    ai = public_ai_status()
    version, supersedes = _next_version(conn, client_id, "trend", run_year, run_month)
    now = _now()
    custom_title = " ".join(str(title or "").split()).strip()
    title = custom_title or suggested_trend_report_title(
        int(period["planning_year"]), int(period["planning_month"])
    )
    notes = [
        "Preparation only — no paid AI or search request.",
        "Opening/reloading does not start a request.",
        search.get("reason") or "",
        f"Onderzoeksmodus: {mode}.",
    ]
    if max_budget_usd is not None:
        notes.append(f"Maximumbudget (schattingspoort): USD {max_budget_usd} — géén harde mid-flight limiet.")
    if missing or not fully_researched_possible:
        notes.append(
            "Onvoldoende bronnen/zoekroute: resultaat mag niet als volledig onderzocht worden aangemerkt."
        )

    cur = conn.execute(
        """
        INSERT INTO client_reports (
            client_id, report_type, period_year, period_month, planning_year, planning_month,
            title, status, version, supersedes_id, prompt_version, provider, model,
            prepared_at, executed_at, input_snapshot_json, sources_json, body_json,
            estimate_json, usage_json, linked_trend_report_id, error_text, is_mock,
            notes_json, created_at, updated_at
        ) VALUES (?, 'trend', ?, ?, ?, ?, ?, 'prepared', ?, ?, ?, ?, ?, ?, NULL, ?, ?, '{}', ?, '{}', NULL, '', 0, ?, ?, ?)
        """,
        (
            client_id,
            run_year,
            run_month,
            period["planning_year"],
            period["planning_month"],
            title,
            version,
            supersedes,
            PROMPT_VERSION,
            "Google Gemini Developer API" if "generativelanguage" in (ai.get("base_host") or "") else (ai.get("base_host") or ""),
            ai.get("model") or "",
            now,
            json.dumps(snapshot, ensure_ascii=False),
            json.dumps(clean_sources, ensure_ascii=False),
            json.dumps(estimate, ensure_ascii=False),
            json.dumps(notes, ensure_ascii=False),
            now,
            now,
        ),
    )
    report_id = int(cur.lastrowid)
    for src in clean_sources:
        conn.execute(
            """
            INSERT INTO client_report_sources (
                report_id, title, url, published_at, consulted_at, excerpt, source_kind, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                src["title"],
                src["url"],
                src["published_at"],
                src["consulted_at"],
                src["excerpt"],
                src["source_kind"],
                now,
            ),
        )
    # usage event: prepared, tokens unknown
    conn.execute(
        """
        INSERT INTO ai_usage_events (
            client_id, post_id, trial_run_id, provider, model, prompt_version,
            started_at, finished_at, status,
            prompt_tokens, completion_tokens, total_tokens,
            extra_tool_cost, extra_media_cost, currency,
            estimated_cost, actual_cost, cost_known, rate_date, notes
        ) VALUES (?, NULL, NULL, ?, ?, ?, ?, NULL, 'prepared_not_executed',
                  NULL, NULL, NULL, NULL, NULL, ?, ?, NULL, 0, ?, ?)
        """,
        (
            client_id,
            ai.get("model") and "Google Gemini Developer API" or "onbekend",
            ai.get("model") or OFFICIAL_RATES["model"],
            PROMPT_VERSION,
            now,
            OFFICIAL_RATES["currency"],
            estimate["estimated_cost_usd"]["high"],
            OFFICIAL_RATES["rate_date"],
            f"Trend report v{version} prepared (id={report_id}); no request. Tokens unknown.",
        ),
    )
    return get_report(conn, client_id, report_id)


def _legend_payload(conn, client_id: int) -> dict[str, Any]:
    def rows(items) -> list[dict[str, Any]]:
        return [
            {"id": item.item_id, "name": item.name, "explanation": item.explanation}
            for item in items
        ]

    formats = []
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(content_formats)").fetchall()}
    extra = {"example_url", "status", "usage_count"} & cols
    if extra:
        select_extra = ", ".join(sorted(extra))
        for row in conn.execute(
            f"""
            SELECT id, name, explanation, {select_extra}
            FROM content_formats WHERE client_id = ?
            ORDER BY name COLLATE NOCASE, id
            """,
            (client_id,),
        ).fetchall():
            item = {
                "id": row["id"],
                "name": row["name"],
                "explanation": row["explanation"],
            }
            for key in sorted(extra):
                item[key] = row[key]
            formats.append(item)
    else:
        formats = rows(list_formats(conn, client_id))

    return {
        "formats": formats,
        "pillars": rows(list_pillars(conn, client_id)),
        "hooks": rows(list_hooks(conn, client_id)),
    }


def _available_stories(conn, client_id: int, *, year: int, month: int) -> dict[str, Any]:
    """Client-scoped stories from Figma planning + posts, for the period."""
    stories = []
    source_notes = []
    try:
        from maaike.figma_planning import ensure_figma_tables

        ensure_figma_tables(conn)
        rows = conn.execute(
            """
            SELECT id, code, content_kind, brief_excerpt, page_name, period_year, period_month,
                   format_raw, pillar_raw, hook_raw, source_url
            FROM figma_planning_items
            WHERE client_id = ? AND LOWER(content_kind) = 'story'
              AND (
                    (period_year = ? AND period_month = ?)
                    OR period_year IS NULL
                  )
            ORDER BY period_year DESC, period_month DESC, id
            """,
            (client_id, year, month),
        ).fetchall()
        for row in rows:
            stories.append(
                {
                    "source": "figma_planning_items",
                    "id": row["id"],
                    "code": row["code"],
                    "description": row["brief_excerpt"] or None,
                    "page_name": row["page_name"],
                    "period_year": row["period_year"],
                    "period_month": row["period_month"],
                    "format_raw": row["format_raw"] or None,
                    "pillar_raw": row["pillar_raw"] or None,
                    "hook_raw": row["hook_raw"] or None,
                    "source_url": row["source_url"] or None,
                }
            )
        source_notes.append("figma_planning_items")
    except Exception:
        source_notes.append("figma_planning_items_unavailable")

    post_rows = conn.execute(
        """
        SELECT id, published_at, platform, content_kind, caption, permalink
        FROM posts
        WHERE client_id = ?
          AND LOWER(COALESCE(content_kind, '')) LIKE '%story%'
          AND substr(published_at, 1, 7) = ?
        ORDER BY published_at, id
        """,
        (client_id, f"{year:04d}-{month:02d}"),
    ).fetchall()
    for row in post_rows:
        stories.append(
            {
                "source": "posts",
                "post_id": row["id"],
                "published_at": row["published_at"],
                "platform": row["platform"],
                "content_kind": row["content_kind"],
                "description": (row["caption"] or "")[:400] or None,
                "permalink": row["permalink"],
            }
        )
    if post_rows:
        source_notes.append("posts.content_kind")
    return {
        "present": bool(stories),
        "count": len(stories),
        "items": stories,
        "sources": source_notes,
        "missing_reason": None if stories else "Geen stories gevonden voor deze klant/periode.",
    }


def _trend_summary(conn, client_id: int, linked_trend_report_id: int | None) -> dict[str, Any] | None:
    if linked_trend_report_id is None:
        return None
    row = conn.execute(
        "SELECT * FROM client_reports WHERE id = ? AND client_id = ? AND report_type = 'trend'",
        (linked_trend_report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Gekozen trendrapport hoort niet bij deze klant.")
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "version": row["version"],
        "period_year": row["period_year"],
        "period_month": row["period_month"],
        "is_mock": bool(row["is_mock"]),
        "body_present": bool(str(row["body_json"] or "").strip() not in ("", "{}")),
    }


def _client_report_prompt_input(
    *,
    strategy: dict[str, Any],
    legend: dict[str, Any],
    period_bundle: dict[str, Any],
    trend: dict[str, Any] | None,
    bundle: dict[str, Any],
    analysis_context: dict[str, Any] | None = None,
    stories: dict[str, Any] | None = None,
    historical_performance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Control view of data that would go into Maaike's client-report prompt — no AI output."""
    from maaike.client_report_view import comparison_prompt_block

    metrics = period_bundle["metrics"]
    posts = period_bundle["posts"]
    ai_summary = summarize_attached_ai_analyses(posts)
    comparison_block = comparison_prompt_block(period_bundle)
    window = period_bundle["period"]
    analysis_period = {
        "year": window.get("year"),
        "month": window.get("month"),
        "start": window.get("start"),
        "end": window.get("end"),
        "label": window.get("label"),
        "role": "analyseperiode",
    }
    planning = None
    if analysis_context:
        planning = analysis_context.get("planning_period")
    return {
        "strategy": {
            "completed_at": strategy.get("completed_at"),
            "pending_questions": strategy.get("pending_questions"),
            "start_answers": strategy.get("start_answers") or {},
            "strategy_fields": {
                k: v
                for k, v in (strategy.get("strategy_fields") or {}).items()
                if k not in {"excel_month_contexts"}  # large; month_context resolved below
            },
            "excel_month_contexts_count": len(
                (strategy.get("strategy_fields") or {}).get("excel_month_contexts") or []
            ),
            "targets": strategy.get("targets") or [],
            "topic_summary": _strategy_topics_summary(strategy),
            "account_info": strategy.get("account_info") or {},
        },
        "format_legend": legend,
        "periods": {
            **window,
            "analysis_period": analysis_period,
            "planning_period": planning,
        },
        "analysis_context": analysis_context,
        "available_stories": stories,
        "historical_performance": historical_performance,
        "comparison_for_prompt": comparison_block,
        "post_data": {
            "count": metrics["post_count"],
            "posts": posts,
            "metrics": metrics,
            "previous_metrics": period_bundle["previous_metrics"],
            "comparison": period_bundle["comparison"],
            "comparison_for_prompt": comparison_block,
            "attached_ai_analyses": {
                "count": ai_summary["completed_post_ai_analyses"],
                "analysis_ids": ai_summary["completed_analysis_ids"],
                "post_ids": ai_summary["completed_post_ids"],
            },
            "existing_insights_actions": [
                {
                    "post_id": p.get("post_id"),
                    "excel_assessment": p.get("excel_assessment"),
                    "ai_analysis": p.get("ai_analysis"),
                    "human_feedback": p.get("human_feedback"),
                }
                for p in posts
                if p.get("excel_assessment") or p.get("ai_analysis") or p.get("human_feedback")
            ],
        },
        "linked_trend_report": trend,
        "instruction_bundle": {
            "prompt_version": bundle["prompt_version"],
            "primary_file": bundle["primary_file"],
            "chapters": bundle["chapters"],
            "required_sources": bundle["required_sources"],
            "system_chars": bundle["system_chars"],
            "workflow_prompts_local": True,
            "six_analysis_questions": [
                "Wat presteerde beter?",
                "Wat presteerde slechter?",
                "Welke formats, hooks, onderwerpen of timing verklaren dit?",
                "Welke succesvolle formats herhalen we?",
                "Welke formats of content laten we achterwege?",
                "Welke nieuwe ideeën testen we gecontroleerd?",
            ],
            "chapter_keys": bundle.get("chapter_keys") or [],
            "includes_action_plan": bool(bundle.get("includes_action_plan")),
            "actieplan_loaded": bool(
                ((bundle.get("supporting_files") or {}).get("actieplan") or {}).get("loaded")
            ),
            "source_honesty": {
                "missing_source_phrase": "Niet onderzocht / onvoldoende gegevens",
                "instructions_and_examples_are_not_sources": True,
                "no_invented_chapter_fillers": True,
                "source_link_counts_as_read_only_when_content_fetched": True,
            },
        },
        "ai_analysis_executed": ai_summary["ai_analysis_executed"],
        "ai_analysis_status": ai_summary["ai_analysis_status"],
        "attached_ai_analysis_ids": ai_summary["completed_analysis_ids"],
        "note": (
            "Dit is de controleweergave van invoer voor Maaikes klantrapportprompt. "
            "Figures come from Python. "
            + (
                f"Completed post AI analyses attached: {ai_summary['completed_analysis_ids']}. "
                if ai_summary["ai_analysis_executed"]
                else "No completed Claude/post AI analyses attached. "
            )
            + "Actieplan volgt na klantrapportinzichten; menselijke goedkeuring verplicht. "
            "Instructies/voorbeeldrapporten zijn geen onderzoeksbronnen. "
            "Klantgegevens zijn uitsluitend van de gekozen klant."
        ),
    }


def _enrich_client_report_context(
    conn,
    client_id: int,
    *,
    period_bundle: dict[str, Any],
    planning_year: int | None = None,
    planning_month: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from maaike.excel_analysis_context import build_client_analysis_context

    window = period_bundle["period"]
    analysis_year = int(window["year"])
    analysis_month = int(window["month"])
    analysis_context = build_client_analysis_context(
        conn,
        client_id,
        analysis_year=analysis_year,
        analysis_month=analysis_month,
        planning_year=planning_year,
        planning_month=planning_month,
    )
    plan = analysis_context["planning_period"]
    stories = _available_stories(
        conn, client_id, year=int(plan["year"]), month=int(plan["month"])
    )
    # Also include analysis-month stories
    stories_analysis = _available_stories(
        conn, client_id, year=analysis_year, month=analysis_month
    )
    if stories_analysis.get("items"):
        seen = {(s.get("id"), s.get("post_id"), s.get("source")) for s in stories.get("items") or []}
        for item in stories_analysis["items"]:
            key = (item.get("id"), item.get("post_id"), item.get("source"))
            if key not in seen:
                stories.setdefault("items", []).append(item)
        stories["count"] = len(stories.get("items") or [])
        stories["present"] = stories["count"] > 0
        if stories["present"]:
            stories["missing_reason"] = None
    historical = {
        "previous_metrics": period_bundle.get("previous_metrics"),
        "comparison": period_bundle.get("comparison"),
        "compare_label": window.get("compare_label"),
        "present": bool(period_bundle.get("previous_metrics")),
        "source": "report_metrics.previous_equal_length",
        "missing_reason": None
        if period_bundle.get("previous_metrics")
        else "Geen vergelijkbare vorige periode beschikbaar.",
    }
    return analysis_context, stories, historical


def inspect_client_report_data(
    conn,
    client_id: int,
    *,
    period_year: int | None = None,
    period_month: int | None = None,
    start: str | None = None,
    end: str | None = None,
    compare_start: str | None = None,
    compare_end: str | None = None,
    linked_trend_report_id: int | None = None,
) -> dict[str, Any]:
    """Inspectable client-report figures + prompt input. No AI call, nothing persisted."""
    ensure_report_tables(conn)
    _require_client(conn, client_id)
    bundle = load_report_instruction_bundle("client")
    period_bundle = build_period_metrics(
        conn,
        client_id,
        period_year=period_year,
        period_month=period_month,
        start=start,
        end=end,
        compare_start=compare_start,
        compare_end=compare_end,
        attach_enrichment=True,
    )
    strategy = get_strategy(conn, client_id)
    legend = _legend_payload(conn, client_id)
    trend = _trend_summary(conn, client_id, linked_trend_report_id)
    metrics = period_bundle["metrics"]
    posts = period_bundle["posts"]
    analysis_context, stories, historical = _enrich_client_report_context(
        conn, client_id, period_bundle=period_bundle
    )

    missing: list[str] = []
    if trend is None:
        missing.append("No matching trend report selected.")
    if metrics["post_count"] == 0:
        missing.append("No posts with a publication date in this period.")
    if not (strategy.get("start_answers") or {}):
        missing.append("Strategy/start answers largely empty.")
    if not strategy.get("targets"):
        missing.append("No targets recorded.")
    unclassified = metrics.get("unclassified") or {}
    for kind, label in (("format", "format"), ("pillar", "content pillar"), ("hook", "hook")):
        count = (unclassified.get(kind) or {}).get("count") or 0
        if count:
            missing.append(f"{count} post(s) zonder {label}.")
    if not (analysis_context.get("feedback_tov") or {}).get("present"):
        missing.append("Feedback TOV ontbreekt.")
    if not (analysis_context.get("month_context") or {}).get("present"):
        missing.append("Maandteksten (Analyse vorige planning / Bijzonderheden) niet gekoppeld.")

    ai_summary = summarize_attached_ai_analyses(posts)
    available = {
        "posts_in_period": metrics["post_count"],
        "formats_used": [f["name"] for f in metrics["by_format"] if not f.get("is_unclassified")],
        "pillars_used": [f["name"] for f in metrics["by_pillar"] if not f.get("is_unclassified")],
        "hooks_used": [f["name"] for f in metrics["by_hook"] if not f.get("is_unclassified")],
        "ai_analyses": ai_summary["ai_analyses"],
        "completed_post_ai_analyses": ai_summary["completed_post_ai_analyses"],
        "completed_analysis_ids": ai_summary["completed_analysis_ids"],
        "human_feedback": sum(1 for p in posts if p.get("human_feedback")),
        "confirmed_verdicts": sum(
            1 for p in posts if (p.get("human_feedback") or {}).get("final_verdict_confirmed")
        ),
        "strategy_present": bool(strategy.get("start_answers")),
        "targets_count": len(strategy.get("targets") or []),
        "trend_linked": trend is not None,
        "legend_formats": len(legend["formats"]),
        "legend_pillars": len(legend["pillars"]),
        "legend_hooks": len(legend["hooks"]),
        "feedback_tov": bool((analysis_context.get("feedback_tov") or {}).get("present")),
        "month_context": bool((analysis_context.get("month_context") or {}).get("present")),
        "stories": stories.get("count") or 0,
        "historical_performance": bool(historical.get("present")),
        "seo_sources_supplied": False,
        "competitor_sources_supplied": False,
        "ahrefs_sources_supplied": False,
    }
    prompt_input = _client_report_prompt_input(
        strategy=strategy,
        legend=legend,
        period_bundle=period_bundle,
        trend=trend,
        bundle=bundle,
        analysis_context=analysis_context,
        stories=stories,
        historical_performance=historical,
    )
    trend_options = [
        {
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "version": r["version"],
            "period_year": r["period_year"],
            "period_month": r["period_month"],
            "is_mock": bool(r["is_mock"]),
        }
        for r in conn.execute(
            """
            SELECT id, title, status, version, period_year, period_month, is_mock
            FROM client_reports
            WHERE client_id = ? AND report_type = 'trend'
            ORDER BY period_year DESC, period_month DESC, version DESC, id DESC
            """,
            (client_id,),
        ).fetchall()
    ]

    coverage = build_analysis_data_coverage(
        conn,
        client_id,
        period_bundle,
        stories=stories,
        missing=missing,
    )

    return {
        "client_id": client_id,
        "persisted": False,
        "ai_analysis_executed": ai_summary["ai_analysis_executed"],
        "ai_analysis_status": ai_summary["ai_analysis_status"],
        "ai_analysis_banner": ai_summary["ai_analysis_banner"],
        "attached_ai_analysis_ids": ai_summary["completed_analysis_ids"],
        "period": period_bundle["period"],
        "metrics": metrics,
        "previous_metrics": period_bundle["previous_metrics"],
        "comparison": period_bundle["comparison"],
        "posts": posts,
        "available": available,
        "missing": missing,
        "partial": bool(missing),
        "data_coverage": coverage,
        "prompt_input": prompt_input,
        "linked_trend": trend,
        "trend_options": trend_options,
        "calculation_engine": "python_report_metrics",
        "ai_must_not_invent_numbers": True,
        "prompt_version": PROMPT_VERSION,
        "ai_status": public_ai_status(),
    }


def prepare_client_report(
    conn,
    client_id: int,
    *,
    period_year: int,
    period_month: int,
    linked_trend_report_id: int | None = None,
    allow_partial_without_trend: bool = False,
    max_budget_usd: float | None = None,
    start: str | None = None,
    end: str | None = None,
    compare_start: str | None = None,
    compare_end: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    ensure_report_tables(conn)
    _require_client(conn, client_id)
    if not (1 <= period_month <= 12):
        raise ValueError("Ongeldige plannings-/rapportmaand.")
    bundle = load_report_instruction_bundle("client")
    period_bundle = build_period_metrics(
        conn,
        client_id,
        period_year=period_year if start is None else None,
        period_month=period_month if start is None else None,
        start=start,
        end=end,
        compare_start=compare_start,
        compare_end=compare_end,
        attach_enrichment=True,
    )
    # Keep calendar month on the report row even when custom dates override the window
    window = period_bundle["period"]
    if start and end:
        # Align stored year/month with resolved window when custom
        period_year = int(window["year"])
        period_month = int(window["month"])

    posts = period_bundle["posts"]
    metrics = period_bundle["metrics"]
    comparison = period_bundle["comparison"]
    strategy = get_strategy(conn, client_id)
    legend = _legend_payload(conn, client_id)
    trend = _trend_summary(conn, client_id, linked_trend_report_id)
    # period_year/month on the report = analysis period; planning defaults to next month
    if period_month == 12:
        default_plan_y, default_plan_m = period_year + 1, 1
    else:
        default_plan_y, default_plan_m = period_year, period_month + 1
    analysis_context, stories, historical = _enrich_client_report_context(
        conn,
        client_id,
        period_bundle=period_bundle,
        planning_year=default_plan_y,
        planning_month=default_plan_m,
    )
    plan_period = analysis_context["planning_period"]
    planning_year = int(plan_period["year"])
    planning_month = int(plan_period["month"])

    missing = []
    if trend is None:
        missing.append("No matching trend report selected.")
        if not allow_partial_without_trend:
            raise ValueError(
                "Select a trend report, or set allow_partial_without_trend to prepare a "
                "clearly marked partial client report."
            )
    if metrics["post_count"] == 0:
        missing.append("No posts with a publication date in this period.")
    if not (strategy.get("start_answers") or {}):
        missing.append("Strategy/start answers largely empty.")
    if not strategy.get("targets"):
        missing.append("No targets recorded.")
    unclassified = metrics.get("unclassified") or {}
    for kind, label in (("format", "format"), ("pillar", "content pillar"), ("hook", "hook")):
        count = (unclassified.get(kind) or {}).get("count") or 0
        if count:
            missing.append(f"{count} post(s) zonder {label}.")
    if not (analysis_context.get("feedback_tov") or {}).get("present"):
        missing.append("Feedback TOV ontbreekt.")
    if not (analysis_context.get("month_context") or {}).get("present"):
        missing.append("Maandteksten (Analyse vorige planning / Bijzonderheden) niet gekoppeld.")

    ai_summary = summarize_attached_ai_analyses(posts)
    available = {
        "posts_in_period": metrics["post_count"],
        "formats_used": [f["name"] for f in metrics["by_format"] if not f.get("is_unclassified")],
        "pillars_used": [f["name"] for f in metrics["by_pillar"] if not f.get("is_unclassified")],
        "hooks_used": [f["name"] for f in metrics["by_hook"] if not f.get("is_unclassified")],
        "ai_analyses": ai_summary["ai_analyses"],
        "completed_post_ai_analyses": ai_summary["completed_post_ai_analyses"],
        "completed_analysis_ids": ai_summary["completed_analysis_ids"],
        "human_feedback": sum(1 for p in posts if p.get("human_feedback")),
        "confirmed_verdicts": sum(
            1 for p in posts if (p.get("human_feedback") or {}).get("final_verdict_confirmed")
        ),
        "strategy_present": bool(strategy.get("start_answers")),
        "targets_count": len(strategy.get("targets") or []),
        "trend_linked": trend is not None,
        "legend_formats": len(legend["formats"]),
        "legend_pillars": len(legend["pillars"]),
        "legend_hooks": len(legend["hooks"]),
        "feedback_tov": bool((analysis_context.get("feedback_tov") or {}).get("present")),
        "month_context": bool((analysis_context.get("month_context") or {}).get("present")),
        "stories": stories.get("count") or 0,
        "historical_performance": bool(historical.get("present")),
        "seo_sources_supplied": False,
        "competitor_sources_supplied": False,
        "ahrefs_sources_supplied": False,
    }
    prompt_input = _client_report_prompt_input(
        strategy=strategy,
        legend=legend,
        period_bundle=period_bundle,
        trend=trend,
        bundle=bundle,
        analysis_context=analysis_context,
        stories=stories,
        historical_performance=historical,
    )

    snapshot = {
        "report_type": "client",
        "research_mode": "supplied_data",
        "max_budget_usd": max_budget_usd,
        "period": {
            "year": period_year,
            "month": period_month,
            **window,
            "analysis_period": {
                "year": period_year,
                "month": period_month,
                "role": "analyseperiode",
            },
            "planning_period": {
                "year": planning_year,
                "month": planning_month,
                "role": "planningsmaand",
            },
        },
        "instruction_bundle": prompt_input["instruction_bundle"],
        "available": available,
        "missing": missing,
        "partial": bool(missing) or trend is None,
        "partial_without_trend": trend is None,
        "metrics": metrics,
        "previous_metrics": period_bundle["previous_metrics"],
        "comparison": comparison,
        "posts": posts,
        "analysis_context": analysis_context,
        "available_stories": stories,
        "historical_performance": historical,
        "format_legend": legend,
        "strategy_summary": {
            "completed_at": strategy.get("completed_at"),
            "pending_questions": strategy.get("pending_questions"),
            "start_answer_keys": list((strategy.get("start_answers") or {}).keys()),
            "start_answers": strategy.get("start_answers") or {},
            "strategy_field_keys": list((strategy.get("strategy_fields") or {}).keys()),
            "targets": strategy.get("targets") or [],
            "account_info": strategy.get("account_info") or {},
            "tone_of_voice_present": bool(
                (strategy.get("start_answers") or {}).get("tone_of_voice")
            ),
        },
        "prompt_input": prompt_input,
        "context_preview": {
            "research_mode": "supplied_data",
            "enable_google_search": False,
            "posts_in_period": metrics["post_count"],
            "trend_linked": trend is not None,
            "ai_analyses": available["ai_analyses"],
            "completed_post_ai_analyses": available["completed_post_ai_analyses"],
            "completed_analysis_ids": available["completed_analysis_ids"],
            "human_feedback": available["human_feedback"],
            "targets_count": available["targets_count"],
            "feedback_tov": available["feedback_tov"],
            "month_context": available["month_context"],
            "stories": available["stories"],
            "python_metrics_only": True,
            "ai_must_not_invent_numbers": True,
            "preserve_ai_vs_human_disagreement": True,
            "ai_analysis_executed": ai_summary["ai_analysis_executed"],
            "period_label": window.get("label"),
            "compare_label": window.get("compare_label"),
            "analysis_period": f"{period_year}-{period_month:02d}",
            "planning_period": f"{planning_year}-{planning_month:02d}",
            "client_isolation": True,
            "workflow_prompts_local": True,
        },
        "linked_trend": trend,
        "calculation_engine": "python_report_metrics",
        "ai_must_not_invent_numbers": True,
        "ai_analysis_executed": ai_summary["ai_analysis_executed"],
        "ai_analysis_status": ai_summary["ai_analysis_status"],
        "ai_analysis_banner": ai_summary["ai_analysis_banner"],
        "attached_ai_analysis_ids": ai_summary["completed_analysis_ids"],
    }
    estimate = _estimate_report("client", snapshot)
    ai = public_ai_status()
    version, supersedes = _next_version(conn, client_id, "client", period_year, period_month)
    now = _now()
    custom_title = " ".join(str(title or "").split()).strip()
    title = custom_title or suggested_client_report_title(
        _client_name(conn, client_id), period_year, period_month
    )
    notes = [
        "Preparation only — no paid AI request.",
        "Figures calculated in Python; AI must not invent totals.",
        "Opening/reloading does not start a request.",
        f"Analyseperiode {period_year}-{period_month:02d}; planningsmaand {planning_year}-{planning_month:02d}.",
    ]
    if trend is None:
        notes.append("Partial report: explicitly marked as without a matching trend report.")

    cur = conn.execute(
        """
        INSERT INTO client_reports (
            client_id, report_type, period_year, period_month, planning_year, planning_month,
            title, status, version, supersedes_id, prompt_version, provider, model,
            prepared_at, executed_at, input_snapshot_json, sources_json, body_json,
            estimate_json, usage_json, linked_trend_report_id, error_text, is_mock,
            notes_json, created_at, updated_at
        ) VALUES (?, 'client', ?, ?, ?, ?, ?, 'prepared', ?, ?, ?, ?, ?, ?, NULL, ?, '[]', '{}', ?, '{}', ?, '', 0, ?, ?, ?)
        """,
        (
            client_id,
            period_year,
            period_month,
            planning_year,
            planning_month,
            title,
            version,
            supersedes,
            PROMPT_VERSION,
            "Google Gemini Developer API" if "generativelanguage" in (ai.get("base_host") or "") else (ai.get("base_host") or ""),
            ai.get("model") or "",
            now,
            json.dumps(snapshot, ensure_ascii=False),
            json.dumps(estimate, ensure_ascii=False),
            linked_trend_report_id,
            json.dumps(notes, ensure_ascii=False),
            now,
            now,
        ),
    )
    report_id = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO ai_usage_events (
            client_id, post_id, trial_run_id, provider, model, prompt_version,
            started_at, finished_at, status,
            prompt_tokens, completion_tokens, total_tokens,
            extra_tool_cost, extra_media_cost, currency,
            estimated_cost, actual_cost, cost_known, rate_date, notes
        ) VALUES (?, NULL, NULL, ?, ?, ?, ?, NULL, 'prepared_not_executed',
                  NULL, NULL, NULL, NULL, NULL, ?, ?, NULL, 0, ?, ?)
        """,
        (
            client_id,
            "Google Gemini Developer API",
            ai.get("model") or OFFICIAL_RATES["model"],
            PROMPT_VERSION,
            now,
            OFFICIAL_RATES["currency"],
            estimate["estimated_cost_usd"]["high"],
            OFFICIAL_RATES["rate_date"],
            f"Client report v{version} prepared (id={report_id}); no request. Tokens unknown.",
        ),
    )
    return get_report(conn, client_id, report_id)


def begin_report_execution_guard(conn, client_id: int, report_id: int) -> dict[str, Any]:
    ensure_report_tables(conn)
    row = conn.execute(
        "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
        (report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Rapport niet gevonden voor deze klant.")
    if row["status"] == "running":
        raise ValueError("Uitvoering loopt al. Voorkom dubbelklikken; herlaad voor status.")
    if row["status"] in {"completed", "mock_completed"} and row["executed_at"]:
        raise ValueError(
            "Er bestaat al een opgeslagen resultaat voor deze versie. "
            "Open het opgeslagen rapport of bereid een nieuwe versie voor."
        )
    conn.execute(
        "UPDATE client_reports SET status = 'running', updated_at = ? WHERE id = ?",
        (_now(), report_id),
    )
    return get_report(conn, client_id, report_id)


def apply_mock_report(conn, client_id: int, report_id: int) -> dict[str, Any]:
    """Store a clearly labeled mock report body. Never calls a paid API."""
    ensure_report_tables(conn)
    row = conn.execute(
        "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
        (report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Rapport niet gevonden voor deze klant.")
    if row["status"] == "running":
        pass
    elif row["status"] in {"completed", "mock_completed"} and row["executed_at"]:
        raise ValueError("Deze versie heeft al een resultaat. Bereid een nieuwe versie voor.")

    from maaike.ai_response_validate import failed_body_envelope, validate_report_body

    snapshot = json.loads(row["input_snapshot_json"] or "{}")
    now = _now()
    test_label = "LOCAL_TEST / MOCK — no real Claude or search output"
    if row["report_type"] == "trend":
        candidate = {
            "label": "MOCK — no real AI or search output",
            "chapters": {
                "positionering": "Mock: ontbrekende internetbronnen voorkomen een echt trendrapport.",
                "managementsamenvatting": "Dit is testdata, niet opnemen als klantadvies.",
                "belangrijkste_trends": "Mock-trendlijst alleen voor UI/validatietest.",
                "platform_verschuivingen": "Mock: platformshifts niet geverifieerd.",
                "contentkansen": "Mock: contentkansen placeholder voor test.",
                "zoekclusters": "Mock: zoekclusters niet opgehaald.",
                "conclusie": "Mockconclusie — handmatige bronnen en echte uitvoering nog nodig.",
            },
            "distinctions": {
                "facts": [],
                "trends": [],
                "suggestions": ["Mock-suggestie alleen voor UI-test."],
            },
            "fully_researched": False,
            "not_web_research": True,
            "missing": snapshot.get("missing") or [],
        }
    else:
        metrics = snapshot.get("metrics") or {}
        candidate = {
            "label": "MOCK — no real AI output",
            "six_answers": {
                "beter": "Mock: see Python aggregation by_format/by_pillar; no AI claim.",
                "slechter": "Mock: ontbrekende metingen niet als 0 gelezen.",
                "verklaring": "Mock: no proven cause without visual/source evidence.",
                "herhalen": "Mock: formats met herhaald sterke Excel-rating + bereik (indien bekend).",
                "stoppen": "Mock: volg instructie — 3× slecht ⇒ stoppen als standaardconclusie (nog te bevestigen).",
                "testen": "Mock: gecontroleerde tests alleen met hypothese en meetplan.",
            },
            "chapters": {
                "input_brainstorm": "LOCAL_TEST mock: brainstorm-input alleen voor structuurtest.",
                "per_kanaal": "LOCAL_TEST mock: kanaalvertaling placeholder, geen klantadvies.",
                "seo_serp": "Niet onderzocht / onvoldoende gegevens — LOCAL_TEST mock zonder SEO/SERP-bronnen.",
                "concurrenten": "Niet onderzocht / onvoldoende gegevens — LOCAL_TEST mock zonder concurrentbronnen.",
                "hooks_formats_testen": "LOCAL_TEST mock: hooks/formats om te testen (testdata).",
                "laten_liggen_aanscherpen": "LOCAL_TEST mock: wat laten liggen — alleen UI/validatie.",
            },
            "action_plan": {
                "planning_note": "LOCAL_TEST mock: planningsnoot — menselijke goedkeuring vereist.",
                "hoofdfocus": "LOCAL_TEST mock: hoofdfocus uit Python-metrics, geen Claude.",
                "waarom_nu": "LOCAL_TEST mock: waarom-nu alleen ter validatie van actieplanblok.",
                "actions": [
                    "LOCAL_TEST: herhaal sterk format na menselijke check.",
                    "LOCAL_TEST: plan één gecontroleerde test met meetplan.",
                    "LOCAL_TEST: markeer zwakke format voor stop/test-besluit.",
                ],
                "stop_or_test_decisions": [
                    "LOCAL_TEST: stoppen of één optimalisatietest — nog te bevestigen."
                ],
                "watch_outs": ["LOCAL_TEST: ontbrekende metrics niet als 0 lezen."],
            },
            "python_metrics_echo": {
                "post_count": metrics.get("post_count"),
                "by_format_top": (metrics.get("by_format") or [])[:5],
                "comparison": snapshot.get("comparison"),
            },
            "partial": snapshot.get("partial"),
            "partial_without_trend": snapshot.get("partial_without_trend"),
            "fully_researched": not bool(snapshot.get("partial")),
        }

    from maaike.ai_response_validate import available_sources_from_snapshot

    validation = validate_report_body(
        str(row["report_type"]),
        candidate,
        raw_text=json.dumps(candidate, ensure_ascii=False),
        test_label=test_label,
        available_sources=available_sources_from_snapshot(snapshot),
    )
    if validation.usable and validation.normalized:
        body = {
            **validation.normalized,
            "label": candidate.get("label") or validation.normalized.get("label") or test_label,
            "test_label": test_label,
            "analysis_usable": True,
            "validation": {
                "ok": True,
                "usable": True,
                "user_message": validation.user_message,
                "test_label": test_label,
            },
        }
        # Keep echo fields from candidate
        for key in ("python_metrics_echo", "partial", "partial_without_trend", "missing", "not_web_research"):
            if key in candidate:
                body[key] = candidate[key]
        status = "mock_completed"
        error_text = ""
    else:
        body = failed_body_envelope(
            label=test_label + " — onbruikbaar",
            raw_text=json.dumps(candidate, ensure_ascii=False),
            raw_parsed=candidate,
            validation=validation,
            extra={"test_label": test_label},
        )
        status = "failed"
        error_text = validation.user_message

    usage = {
        "status": status,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "actual_cost_usd": None,
        "cost_known": False,
        "search_tool_cost": None,
        "search_tool_cost_known": False,
        "notes": "Mock/LOCAL_TEST; tokens and costs unknown (not as 0). No Claude evidence.",
    }
    notes = json.loads(row["notes_json"] or "[]")
    notes.append("Mock gegenereerd — niet tussen echte klantadviezen plaatsen. LOCAL_TEST.")
    conn.execute(
        """
        UPDATE client_reports SET
            status = ?,
            executed_at = ?,
            body_json = ?,
            usage_json = ?,
            is_mock = 1,
            error_text = ?,
            notes_json = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            now,
            json.dumps(body, ensure_ascii=False),
            json.dumps(usage, ensure_ascii=False),
            error_text,
            json.dumps(notes, ensure_ascii=False),
            now,
            report_id,
        ),
    )
    conn.execute(
        """
        UPDATE ai_usage_events SET
            finished_at = ?,
            status = ?,
            cost_known = 0,
            actual_cost = NULL,
            notes = ?
        WHERE client_id = ? AND prompt_version = ? AND status = 'prepared_not_executed'
          AND notes LIKE ?
        """,
        (
            now,
            status,
            f"Mock/LOCAL_TEST report id={report_id}; no paid call; usable={bool(validation.usable)}.",
            client_id,
            PROMPT_VERSION,
            f"%id={report_id}%",
        ),
    )
    return get_report(conn, client_id, report_id)


def add_trend_sources(
    conn,
    client_id: int,
    report_id: int,
    sources: list[dict[str, Any]],
    *,
    fetch_content: bool = True,
) -> dict[str, Any]:
    """Append sources to a prepared trend report; optionally HTTP-fetch page text (no AI)."""
    from maaike.report_source_fetch import enrich_source_record

    ensure_report_tables(conn)
    row = conn.execute(
        "SELECT * FROM client_reports WHERE id = ? AND client_id = ? AND report_type = 'trend'",
        (report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Trend report not found for this client.")
    if row["status"] in {"completed", "mock_completed", "running"}:
        raise ValueError("Bronnen niet meer wijzigen op een uitgevoerde/lopende versie; maak een nieuwe versie.")
    now = _now()
    snapshot = json.loads(row["input_snapshot_json"] or "{}")
    existing = list(snapshot.get("sources") or [])
    for item in sources or []:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not title and not url:
            continue
        do_fetch = bool(item.get("fetch", fetch_content))
        src = enrich_source_record({**item, "title": title, "url": url}, fetch=do_fetch)
        existing.append(src)
        meta = {
            k: src.get(k)
            for k in (
                "supported_finding",
                "certainty",
                "limitations",
                "historical_ok",
                "fetch_status",
                "content_fetched",
                "fetched_at",
                "counted_as_read_source",
                "http_status",
                "fetch_error",
                "content_chars",
                "manual_excerpt_note",
            )
            if src.get(k) is not None
        }
        conn.execute(
            """
            INSERT INTO client_report_sources (
                report_id, title, url, published_at, consulted_at, excerpt, source_kind, created_at,
                fetch_status, content_fetched, fetched_at, supported_finding, certainty,
                limitations, historical_ok, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                src["title"],
                src["url"],
                src["published_at"],
                src["consulted_at"],
                src["excerpt"],
                src["source_kind"],
                now,
                src.get("fetch_status") or "",
                1 if src.get("content_fetched") else 0,
                src.get("fetched_at"),
                src.get("supported_finding") or "",
                src.get("certainty") or "",
                src.get("limitations") or "",
                None if src.get("historical_ok") is None else (1 if src.get("historical_ok") else 0),
                json.dumps(meta, ensure_ascii=False),
            ),
        )
    snapshot["sources"] = existing
    read_n = sum(1 for s in existing if s.get("counted_as_read_source") or s.get("content_fetched"))
    unread_n = sum(1 for s in existing if s.get("url") and not (s.get("counted_as_read_source") or s.get("content_fetched")))
    drop_markers = (
        "handmatige bronnen",
        "geen gelezen",
        "no manual sources",
        "bron(nen) zonder opgehaalde",
        "sources added yet",
    )
    missing = [
        m
        for m in (snapshot.get("missing") or [])
        if not any(marker in m.lower() for marker in drop_markers)
    ]
    if not existing:
        missing.append("No manual sources added yet (title/URL/accessed date).")
    elif read_n == 0:
        missing.append("Geen gelezen broninhoud — URL's alleen opgeslagen tellen niet als gelezen bron.")
    if unread_n:
        missing.append(f"{unread_n} bron(nen) zonder opgehaalde inhoud.")
    snapshot["missing"] = missing
    snapshot["partial"] = bool(missing)
    snapshot["labels"]["not_standalone_web_research"] = True
    snapshot["labels"]["url_saved_is_not_content_read"] = True
    snapshot["source_read_summary"] = {
        "total": len(existing),
        "read": read_n,
        "url_only_unread": unread_n,
    }
    snapshot["context_preview"] = {
        **(snapshot.get("context_preview") or {}),
        "manual_source_count": len(existing),
        "sources_read": read_n,
    }
    estimate = _estimate_report("trend", snapshot)
    conn.execute(
        """
        UPDATE client_reports SET
            input_snapshot_json = ?,
            sources_json = ?,
            estimate_json = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(snapshot, ensure_ascii=False),
            json.dumps(existing, ensure_ascii=False),
            json.dumps(estimate, ensure_ascii=False),
            now,
            report_id,
        ),
    )
    return get_report(conn, client_id, report_id)

def annotate_client_report_source_grounding(
    conn,
    client_id: int,
    report_id: int,
    *,
    preserve_snapshot: bool = True,
) -> dict[str, Any]:
    """Mark stored client report for unfounded source claims without rewriting AI chapters.

    Keeps original six_answers/chapters/action_plan/raw_response. Does not approve.
    Does not regenerate AI. Leaves input_snapshot_json untouched when preserve_snapshot=True.
    """
    from maaike.ai_response_validate import (
        NOT_RESEARCHED_PHRASE,
        audit_unfounded_source_claims,
        available_sources_from_snapshot,
    )

    ensure_report_tables(conn)
    row = conn.execute(
        "SELECT * FROM client_reports WHERE id = ? AND client_id = ? AND report_type = 'client'",
        (report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Client report not found for this client.")

    body = json.loads(row["body_json"] or "{}")
    if not isinstance(body, dict):
        raise ValueError("Report body is not a JSON object.")
    snapshot = json.loads(row["input_snapshot_json"] or "{}")
    sources = available_sources_from_snapshot(snapshot)
    findings = audit_unfounded_source_claims(body, available_sources=sources)
    now = _now()
    notes = json.loads(row["notes_json"] or "[]")
    if not isinstance(notes, list):
        notes = []

    original_ai = {
        "six_answers": body.get("six_answers"),
        "chapters": body.get("chapters"),
        "action_plan": body.get("action_plan"),
        "raw_response": body.get("raw_response"),
        "label": body.get("label"),
    }
    body["original_ai_output_preserved"] = True
    body["original_ai_output"] = body.get("original_ai_output") or original_ai
    body["partial"] = True
    body["requires_human_approval"] = True
    body["analysis_usable"] = False if findings else body.get("analysis_usable", False)
    body["source_grounding"] = {
        "ok": not findings,
        "status": "unfounded_claims_require_human_review" if findings else "ok",
        "requires_human_review": True,
        "approved": False,
        "unfounded_claims": findings,
        "missing_source_phrase": NOT_RESEARCHED_PHRASE,
        "instructions_and_examples_are_not_sources": True,
        "available_sources": sources,
        "annotated_at": now,
        "note": (
            "Partieel rapport: oorspronkelijke AI-uitvoer bewaard. "
            "Ongefundeerde bronclaims vereisen menselijke controle; niet goedgekeurd."
        ),
    }
    validation = body.get("validation") if isinstance(body.get("validation"), dict) else {}
    validation = {
        **validation,
        "source_grounding_ok": not findings,
        "requires_human_review_for_sources": bool(findings),
        "annotated_at": now,
    }
    if findings:
        validation["usable"] = False
        validation["ok"] = False
        validation["user_message"] = (
            "Rapport partieel: ongefundeerde Ahrefs/SEO/concurrent-/trendclaims. "
            "Oorspronkelijke AI-uitvoer bewaard; niet goedgekeurd."
        )
    body["validation"] = validation

    marker = (
        "PARTIEEL — ongefundeerde bronclaims (Ahrefs/SEO/SERP/concurrenten/trends) "
        "vereisen menselijke controle. Niet goedgekeurd. Oorspronkelijke AI-uitvoer bewaard."
    )
    if marker not in notes:
        notes.append(marker)

    conn.execute(
        """
        UPDATE client_reports SET
            body_json = ?,
            notes_json = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(body, ensure_ascii=False),
            json.dumps(notes, ensure_ascii=False),
            now,
            report_id,
        ),
    )
    _ = preserve_snapshot  # snapshot intentionally unchanged by default
    return get_report(conn, client_id, report_id)


def recover_client_report_json_syntax(
    conn,
    client_id: int,
    source_report_id: int,
) -> dict[str, Any]:
    """Create a new version from a failed report's raw_response via mechanical JSON repair only.

    No AI call. Does not rewrite answers/numbers. Stops if repair is ambiguous.
    Result stays a partial concept requiring human review — never auto-approved.
    """
    from maaike.ai_response_validate import (
        available_sources_from_snapshot,
        validate_client_report_body,
    )
    from maaike.json_syntax_repair import repair_unambiguous_json_syntax

    ensure_report_tables(conn)
    row = conn.execute(
        """
        SELECT * FROM client_reports
        WHERE id = ? AND client_id = ? AND report_type = 'client'
        """,
        (source_report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Bronrapport niet gevonden voor deze klant.")

    source_body = json.loads(row["body_json"] or "{}")
    if not isinstance(source_body, dict):
        raise ValueError("Bronrapport-body is geen JSON-object.")
    raw = str(source_body.get("raw_response") or "")
    if not raw.strip():
        raise ValueError("Bronrapport heeft geen raw_response om te herstellen.")

    repair = repair_unambiguous_json_syntax(raw)
    if not repair.get("ok") or not repair.get("parsed"):
        raise ValueError(repair.get("error") or "JSON-herstel niet eenduidig mogelijk; gestopt.")

    snapshot = json.loads(row["input_snapshot_json"] or "{}")
    sources = available_sources_from_snapshot(snapshot)
    candidate = {
        **repair["parsed"],
        "label": (
            f"JSON-syntaxherstel van rapport #{source_report_id} "
            "(geen nieuwe AI-aanroep; inhoud ongewijzigd)"
        ),
        "raw_text": repair["repaired_text"],
        "partial": True,
        "fully_researched": bool(repair["parsed"].get("fully_researched"))
        if "fully_researched" in repair["parsed"]
        else False,
    }
    validation = validate_client_report_body(
        candidate,
        raw_text=repair["repaired_text"] or raw,
        test_label=f"JSON_SYNTAX_RECOVERY from report #{source_report_id}",
        available_sources=sources,
        require_source_honesty=True,
    )
    now = _now()
    version, _prev = _next_version(
        conn, client_id, "client", int(row["period_year"]), int(row["period_month"])
    )
    # Always point supersedes at the source failed report for audit trail.
    supersedes = int(source_report_id)

    if validation.usable and validation.normalized:
        body = {
            **validation.normalized,
            "label": candidate["label"],
            "analysis_usable": True,
            "partial": True,
            "requires_human_approval": True,
            "raw_response": raw,
            "repaired_json_text": repair["repaired_text"],
            "json_syntax_recovery": {
                "source_report_id": source_report_id,
                "edits": repair["edits"],
                "original_raw_preserved": True,
                "content_rewritten": False,
                "auto_approved": False,
                "recovered_at": now,
            },
            "validation": {
                "ok": True,
                "usable": True,
                "user_message": validation.user_message,
                "warnings": validation.warnings
                + [
                    "Geslaagde parse/structuurvalidatie ≠ inhoudelijke goedkeuring.",
                    "Concept voor menselijke controle; niet automatisch goedgekeurd.",
                ],
                "test_label": validation.test_label,
            },
        }
        # Successful structure still stays a review concept — not an approved delivery.
        status = "completed"
        error_text = ""
    else:
        from maaike.ai_response_validate import failed_body_envelope

        body = failed_body_envelope(
            label=candidate["label"],
            raw_text=raw,
            raw_parsed=repair["parsed"],
            validation=validation,
            extra={
                "partial": True,
                "repaired_json_text": repair["repaired_text"],
                "json_syntax_recovery": {
                    "source_report_id": source_report_id,
                    "edits": repair["edits"],
                    "original_raw_preserved": True,
                    "content_rewritten": False,
                    "auto_approved": False,
                    "recovered_at": now,
                },
            },
        )
        status = "failed"
        error_text = validation.user_message or "Herstelparse structureel onbruikbaar."

    notes = [
        f"JSON-syntaxherstel van rapport #{source_report_id} — geen nieuwe AI-aanroep.",
        "Oorspronkelijke raw_response bewaard; alleen geregistreerde syntax-edits toegepast.",
        "Geslaagde parse betekent niet dat de inhoud is goedgekeurd.",
        "Partieel concept voor menselijke controle; niet automatisch goedgekeurd.",
    ]
    for edit in repair["edits"]:
        notes.append(f"Syntax-edit: {edit.get('description')}")

    usage = json.loads(row["usage_json"] or "{}")
    usage = {
        **usage,
        "status": f"json_syntax_recovery_from_{source_report_id}",
        "recovery": {
            "source_report_id": source_report_id,
            "edits": repair["edits"],
            "paid_call": False,
        },
        "notes": (
            f"No paid call. Mechanical JSON repair from report #{source_report_id}. "
            + (usage.get("notes") or "")
        ).strip(),
    }
    title = str(row["title"] or "")
    if "JSON-syntaxherstel" not in title:
        title = f"{title} — JSON-syntaxherstel van #{source_report_id}".strip(" —")

    cur = conn.execute(
        """
        INSERT INTO client_reports (
            client_id, report_type, period_year, period_month, planning_year, planning_month,
            title, status, version, supersedes_id, prompt_version, provider, model,
            prepared_at, executed_at, input_snapshot_json, sources_json, body_json,
            estimate_json, usage_json, linked_trend_report_id, error_text, is_mock,
            notes_json, created_at, updated_at
        ) VALUES (
            ?, 'client', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?
        )
        """,
        (
            client_id,
            row["period_year"],
            row["period_month"],
            row["planning_year"],
            row["planning_month"],
            title,
            status,
            version,
            supersedes,
            row["prompt_version"] or PROMPT_VERSION,
            row["provider"] or "",
            row["model"] or "",
            row["prepared_at"] or now,
            now,
            row["input_snapshot_json"] or "{}",
            row["sources_json"] or "[]",
            json.dumps(body, ensure_ascii=False),
            row["estimate_json"] or "{}",
            json.dumps(usage, ensure_ascii=False),
            row["linked_trend_report_id"],
            error_text,
            json.dumps(notes, ensure_ascii=False),
            now,
            now,
        ),
    )
    new_id = int(cur.lastrowid)
    return get_report(conn, client_id, new_id)

