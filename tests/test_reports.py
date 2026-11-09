"""Reports preparation, execution mocks, versioning, isolation — no paid AI/search."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from maaike.db import initialize_database, transaction
from maaike.gemini_native import SEARCH_RATE, search_capability
from maaike.report_execute import apply_execution_mock, execute_report, execution_preview
from maaike.report_metrics import (
    aggregate_posts,
    compare_periods,
    previous_equal_length,
    resolve_period_window,
)
from maaike.report_prompts import internet_search_capability, load_report_instruction_bundle
from maaike.reports import (
    add_trend_sources,
    apply_mock_report,
    begin_report_execution_guard,
    get_report,
    inspect_client_report_data,
    list_reports,
    prepare_client_report,
    prepare_trend_report,
)
from datetime import date


def test_instructions_and_search_capability_shape():
    trend = load_report_instruction_bundle("trend")
    client = load_report_instruction_bundle("client")
    assert trend["primary_loaded"] is True
    assert client["primary_loaded"] is True
    assert trend["prompt_version"] == client["prompt_version"]
    assert client["includes_action_plan"] is True
    assert trend["includes_action_plan"] is False
    assert (client.get("supporting_files") or {}).get("actieplan", {}).get("loaded") is True
    assert (client.get("supporting_files") or {}).get("style_notes", {}).get("loaded") is True
    assert (client.get("supporting_files") or {}).get("client_example_pdf", {}).get("loaded") is True
    assert (trend.get("supporting_files") or {}).get("trend_example_pdf", {}).get("loaded") is True
    assert "action_plan" in client["system_text"] or "Actieplan" in client["system_text"]
    search = internet_search_capability()
    assert "available" in search
    assert "openai_compat_supports_grounding" in search
    assert search["openai_compat_supports_grounding"] is False
    assert search["manual_sources_supported"] is True
    assert SEARCH_RATE["paid_per_1000_queries"] == 14.0
    # Capability must match native helper
    assert search["route"] == search_capability()["route"]


def test_missing_metrics_not_zero():
    posts = [
        {"metrics": {"reach": 10, "likes": None}},
        {"metrics": {"reach": None, "likes": 2}},
    ]
    agg = aggregate_posts(
        [
            {
                "platform": "instagram",
                "format_name": "C05",
                "pillar_name": "BTS",
                "hook": "vraag",
                "metrics": p["metrics"],
            }
            for p in posts
        ]
    )
    assert agg["totals"]["reach"]["sum"] == 10
    assert agg["totals"]["reach"]["missing_count"] == 1
    assert agg["totals"]["likes"]["sum"] == 2
    assert agg["averages"]["reach"] == 10
    assert any(g["name"] == "vraag" for g in agg["by_hook"])
    cmp_out = compare_periods(
        [{"metrics": {"reach": 10}}],
        [{"metrics": {"reach": None}}],
        metric="reach",
    )
    assert cmp_out["comparable"] is False
    assert cmp_out["claim_significant_difference"] is False
    assert cmp_out["delta_pct_vs_previous_sum"] is None


def test_equal_length_period_and_safe_pct():
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    prev_start, prev_end = previous_equal_length(start, end)
    assert (end - start).days == (prev_end - prev_start).days
    assert prev_end == date(2026, 8, 31)
    assert prev_start == date(2026, 8, 2)

    window = resolve_period_window(period_year=2026, period_month=9)
    assert window["start"] == "2026-09-01"
    assert window["end"] == "2026-09-30"
    assert window["previous_start"] == "2026-08-02"
    assert window["previous_end"] == "2026-08-31"
    assert window["compare_mode"] == "previous_equal_length"
    assert window["lengths_equal"] is True

    custom = resolve_period_window(
        start="2026-09-01",
        end="2026-09-15",
        compare_start="2026-08-01",
        compare_end="2026-08-10",
    )
    assert custom["compare_mode"] == "custom"
    assert custom["lengths_equal"] is False

    zero_prev = compare_periods(
        [{"metrics": {"reach": 50}}],
        [{"metrics": {"reach": 0}}],
        metric="reach",
    )
    assert zero_prev["comparable"] is True
    assert zero_prev["delta_sum"] == 50
    assert zero_prev["delta_pct_vs_previous_sum"] is None
    assert zero_prev["deltas"]["sum"]["pct_available"] is False
    assert zero_prev["deltas"]["sum"]["direction_label"] == "higher"

    up = compare_periods(
        [{"metrics": {"reach": 120}}],
        [{"metrics": {"reach": 100}}],
        metric="reach",
    )
    assert up["deltas"]["sum"]["direction_label"] == "higher"
    assert up["delta_pct_vs_previous_sum"] == 20.0


def test_hooks_and_unclassified_in_aggregate():
    agg = aggregate_posts(
        [
            {
                "post_id": 1,
                "platform": "instagram",
                "format_name": "C05",
                "pillar_name": "",
                "hook": "",
                "caption_preview": "a",
                "metrics": {"reach": 10, "likes": 1, "views": None, "comments": 0},
            },
            {
                "post_id": 2,
                "platform": "instagram",
                "format_name": "",
                "pillar_name": "BTS",
                "hook": "cta",
                "caption_preview": "b",
                "metrics": {"reach": 20, "likes": None, "views": 5, "comments": None},
            },
        ]
    )
    assert agg["unclassified"]["format"]["count"] == 1
    assert agg["unclassified"]["pillar"]["count"] == 1
    assert agg["unclassified"]["hook"]["count"] == 1
    assert any(g["is_unclassified"] for g in agg["by_format"])
    assert any(g["name"] == "cta" for g in agg["by_hook"])
    assert agg["averages"]["reach"] == 15.0
    assert agg["totals"]["reach"]["sum"] == 30


def _seed_posts(conn, client_id: int) -> None:
    conn.execute(
        """
        INSERT INTO posts (
            id, client_id, platform, external_id, published_at, content_kind,
            permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
        ) VALUES (901, ?, 'instagram', 'r1', '2026-09-15T12:00:00+00:00', 'image',
                  'https://ig/1', 'cap', '', 100, 5, 0, 0, 0, 0, 80)
        """,
        (client_id,),
    )
    conn.execute(
        """
        INSERT INTO posts (
            id, client_id, platform, external_id, published_at, content_kind,
            permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
        ) VALUES (902, ?, 'instagram', 'r2', '2026-09-18T12:00:00+00:00', 'carousel_album',
                  'https://ig/2', 'cap2', '', NULL, 3, 0, 0, 0, 0, NULL)
        """,
        (client_id,),
    )


def test_reports_flow_versions_isolation_mock(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "reports.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    now = datetime.now(tz=timezone.utc).isoformat()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        other = int(
            conn.execute(
                "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('OtherR', ?, ?, 'not_connected')",
                (now, now),
            ).lastrowid
        )
        _seed_posts(conn, client_id)

        trend = prepare_trend_report(
            conn, client_id, run_year=2026, run_month=10, sources=[], research_mode="manual"
        )
        assert trend["report"]["status"] == "prepared"
        assert trend["report"]["version"] == 1
        assert trend["report"]["input_snapshot"]["research_mode"] == "manual"
        assert any("manual sources" in m.lower() for m in trend["report"]["input_snapshot"]["missing"])

        trend = add_trend_sources(
            conn,
            client_id,
            trend["report"]["id"],
            [
                {
                    "title": "Testbron Frankwatching",
                    "url": "https://example.com/trend",
                    "published_at": "2026-09-01",
                    "consulted_at": "2026-10-30",
                    "excerpt": "Handmatige bron voor mock.",
                }
            ],
            fetch_content=False,
        )
        assert len(trend["report"]["sources"]) == 1
        assert trend["report"]["sources"][0].get("counted_as_read_source") is True
        assert trend["report"]["sources"][0].get("fetch_status") == "manual_excerpt_only"

        trend2 = prepare_trend_report(
            conn, client_id, run_year=2026, run_month=10, sources=[], research_mode="manual"
        )
        assert trend2["report"]["version"] == 2
        assert trend2["report"]["supersedes_id"] == trend["report"]["id"]

        try:
            prepare_client_report(conn, client_id, period_year=2026, period_month=9)
            raised = False
        except ValueError:
            raised = True
        assert raised

        client_rep = prepare_client_report(
            conn,
            client_id,
            period_year=2026,
            period_month=9,
            linked_trend_report_id=trend["report"]["id"],
        )
        snap = client_rep["report"]["input_snapshot"]
        assert snap["metrics"]["post_count"] == 2
        assert snap["metrics"]["totals"]["reach"]["missing_count"] == 1
        assert snap["metrics"]["totals"]["reach"]["sum"] == 80
        assert snap["comparison"]["claim_significant_difference"] is False
        assert snap["period"]["previous_start"] == "2026-08-02"
        assert snap["period"]["previous_end"] == "2026-08-31"
        assert snap["ai_analysis_executed"] is False
        assert snap["prompt_input"]["ai_analysis_status"] == "not_executed"
        assert "formats" in snap["prompt_input"]["format_legend"]
        assert "by_hook" in snap["metrics"]
        assert client_rep["report"]["prompt_version"]

        mocked = apply_mock_report(conn, client_id, client_rep["report"]["id"])
        assert mocked["report"]["is_mock"] is True
        assert mocked["report"]["status"] == "mock_completed"
        assert "MOCK" in (mocked["report"]["body"].get("label") or "")
        body = mocked["report"]["body"]
        assert set(body["six_answers"]) >= {"beter", "slechter", "verklaring", "herhalen", "stoppen", "testen"}
        assert body.get("chapters", {}).get("input_brainstorm")
        assert body.get("action_plan", {}).get("actions")
        assert body.get("requires_human_approval") is True
        assert snap["prompt_input"]["instruction_bundle"].get("includes_action_plan") is True

        try:
            begin_report_execution_guard(conn, client_id, client_rep["report"]["id"])
            blocked = False
        except ValueError:
            blocked = True
        assert blocked

        assert list_reports(conn, other)["reports"] == []
        try:
            get_report(conn, other, client_rep["report"]["id"])
            iso = False
        except ValueError:
            iso = True
        assert iso

        again = get_report(conn, client_id, client_rep["report"]["id"])
        assert again["report"]["executed_at"] == mocked["report"]["executed_at"]


def test_execution_mocks_and_dry_run(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "reports_exec.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    monkeypatch.setenv("AI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("AI_MODEL", "gemini-3.5-flash-lite")
    initialize_database()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        _seed_posts(conn, client_id)

        # Internet prepare with budget
        internet = prepare_trend_report(
            conn,
            client_id,
            run_year=2026,
            run_month=10,
            research_mode="internet",
            max_budget_usd=0.15,
            sources=[],
        )
        assert internet["report"]["input_snapshot"]["research_mode"] == "internet"
        assert internet["report"]["input_snapshot"]["context_preview"]["enable_google_search"] is True
        assert "combined_high_usd" in internet["report"]["estimate"]
        assert internet["report"]["estimate"]["hard_cost_limit_guaranteed"] is False

        preview = execution_preview(conn, client_id, internet["report"]["id"], max_budget_usd=0.15)
        assert preview["provider"]
        assert preview["model"] == "gemini-3.5-flash-lite"
        assert preview["paid_call"] is False
        assert preview["hard_cost_limit_guaranteed"] is False
        assert "google_search" in " ".join(preview["context_sent_summary"]).lower() or preview[
            "enable_google_search"
        ]

        # Dry-run paid blocks
        try:
            execute_report(conn, client_id, internet["report"]["id"], dry_run_paid=True)
            blocked_dry = False
        except ValueError as exc:
            blocked_dry = "dry_run" in str(exc).lower() or "geblokkeerd" in str(exc).lower()
        assert blocked_dry

        # Budget too low
        try:
            execute_report(
                conn,
                client_id,
                internet["report"]["id"],
                max_budget_usd=0.00001,
                dry_run_paid=True,
            )
            budget_blocked = False
        except ValueError:
            budget_blocked = True
        assert budget_blocked

        ok = apply_execution_mock(
            conn, client_id, internet["report"]["id"], scenario="success_with_sources"
        )
        assert ok["report"]["status"] == "mock_completed"
        assert ok["report"]["is_mock"] is True
        assert ok["report"]["body"].get("fully_researched") is True
        assert ok["report"]["body"].get("sources_used")
        assert ok["report"]["sources"]

        # Reload does not re-run
        again = get_report(conn, client_id, internet["report"]["id"])
        assert again["report"]["executed_at"] == ok["report"]["executed_at"]
        try:
            apply_execution_mock(conn, client_id, internet["report"]["id"], scenario="success_with_sources")
            double = True
        except ValueError:
            double = False
        assert double is False

        # Missing sources scenario on a new version
        v2 = prepare_trend_report(
            conn, client_id, run_year=2026, run_month=10, research_mode="internet", max_budget_usd=1.0
        )
        missing = apply_execution_mock(
            conn, client_id, v2["report"]["id"], scenario="sources_missing"
        )
        assert missing["report"]["status"] == "failed"
        assert missing["report"]["body"].get("analysis_usable") is False
        assert missing["report"]["body"].get("fully_researched") is False
        assert missing["report"]["body"].get("not_web_research_complete") is True
        assert missing["review"]["can_review"] is False

        v3 = prepare_trend_report(
            conn, client_id, run_year=2026, run_month=10, research_mode="internet"
        )
        uncfg = apply_execution_mock(
            conn, client_id, v3["report"]["id"], scenario="search_not_configured"
        )
        assert uncfg["report"]["status"] == "failed"
        assert uncfg["report"]["error_text"]

        v4 = prepare_trend_report(
            conn, client_id, run_year=2026, run_month=10, research_mode="internet"
        )
        bud = apply_execution_mock(
            conn, client_id, v4["report"]["id"], scenario="insufficient_budget"
        )
        assert bud["report"]["status"] == "failed"
        assert bud["report"]["usage"].get("status") == "blocked_budget"

        v5 = prepare_trend_report(
            conn, client_id, run_year=2026, run_month=10, research_mode="internet"
        )
        fail = apply_execution_mock(
            conn, client_id, v5["report"]["id"], scenario="generation_failed"
        )
        assert fail["report"]["status"] == "failed"
        assert fail["report"]["usage"].get("status") == "failed_may_still_cost"
        assert fail["report"]["usage"].get("cost_known") is False

        # Client report mock with trend link + isolation of mock label
        client_rep = prepare_client_report(
            conn,
            client_id,
            period_year=2026,
            period_month=9,
            linked_trend_report_id=ok["report"]["id"],
            max_budget_usd=0.10,
        )
        assert client_rep["report"]["input_snapshot"]["research_mode"] == "supplied_data"
        client_mock = apply_execution_mock(
            conn, client_id, client_rep["report"]["id"], scenario="success_with_sources"
        )
        assert "MOCK" in (client_mock["report"]["body"].get("label") or "")
        assert client_mock["report"]["is_mock"] is True


def test_inspect_client_report_no_persist_isolation(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "reports_inspect.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    now = datetime.now(tz=timezone.utc).isoformat()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        other = int(
            conn.execute(
                "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('OtherInspect', ?, ?, 'not_connected')",
                (now, now),
            ).lastrowid
        )
        _seed_posts(conn, client_id)
        # Editorial on one post so format/hook classified
        conn.execute(
            """
            INSERT INTO content_formats (client_id, name, explanation, created_at, updated_at)
            VALUES (?, 'C05', 'test', ?, ?)
            """,
            (client_id, now, now),
        )
        fmt_id = int(conn.execute("SELECT id FROM content_formats WHERE client_id = ?", (client_id,)).fetchone()[0])
        conn.execute(
            """
            INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at)
            VALUES (901, ?, NULL, 'vraaghaak', ?)
            """,
            (fmt_id, now),
        )

        before = conn.execute(
            "SELECT COUNT(*) AS n FROM client_reports WHERE client_id = ?", (client_id,)
        ).fetchone()["n"]

        inspected = inspect_client_report_data(
            conn, client_id, period_year=2026, period_month=9
        )
        assert inspected["persisted"] is False
        assert inspected["ai_analysis_executed"] is False
        assert inspected["metrics"]["post_count"] == 2
        assert inspected["period"]["label"] == "2026-09-01 to 2026-09-30"
        assert inspected["period"]["compare_label"] == "2026-08-02 to 2026-08-31"
        assert any(g["name"] == "vraaghaak" for g in inspected["metrics"]["by_hook"])
        assert inspected["metrics"]["unclassified"]["format"]["count"] >= 1
        assert inspected["prompt_input"]["periods"]["start"] == "2026-09-01"
        assert "format_legend" in inspected["prompt_input"]
        assert inspected["prompt_input"]["format_legend"]["formats"]

        after = conn.execute(
            "SELECT COUNT(*) AS n FROM client_reports WHERE client_id = ?", (client_id,)
        ).fetchone()["n"]
        assert after == before

        other_view = inspect_client_report_data(
            conn, other, period_year=2026, period_month=9
        )
        assert other_view["metrics"]["post_count"] == 0
        assert other_view["prompt_input"]["format_legend"]["formats"] == []

        # Custom compare dates accepted
        custom = inspect_client_report_data(
            conn,
            client_id,
            start="2026-09-01",
            end="2026-09-30",
            compare_start="2026-07-01",
            compare_end="2026-07-31",
        )
        assert custom["period"]["compare_mode"] == "custom"
        assert custom["period"]["previous_start"] == "2026-07-01"


def test_trend_x2_period_for_november_planning():
    from maaike.report_metrics import trend_lookback_bounds

    period = trend_lookback_bounds(2026, 9)
    assert period["run_year"] == 2026
    assert period["run_month"] == 9
    assert period["lookback_start"] == "2026-08-21"
    assert period["lookback_end"] == "2026-09-20"
    assert period["planning_year"] == 2026
    assert period["planning_month"] == 11
    assert "2026-09" in period["title_hint"] and "2026-11" in period["title_hint"]


def test_url_only_source_not_counted_as_read(tmp_path: Path, monkeypatch) -> None:
    from maaike.report_source_fetch import enrich_source_record

    url_only = enrich_source_record(
        {"title": "Link only", "url": "https://example.com/x"}, fetch=False
    )
    assert url_only["counted_as_read_source"] is False
    assert url_only["fetch_status"] == "url_only_not_read"

    with_excerpt = enrich_source_record(
        {
            "title": "With text",
            "url": "https://example.com/y",
            "excerpt": "Gelezen fragment.",
        },
        fetch=False,
    )
    assert with_excerpt["counted_as_read_source"] is True
    assert with_excerpt["fetch_status"] == "manual_excerpt_only"


def test_trend_execution_preview_has_prompt_package_no_paid(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "trend_preview.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    monkeypatch.setenv("AI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("AI_MODEL", "gemini-3.5-flash-lite")
    initialize_database()
    now = datetime.now(tz=timezone.utc).isoformat()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        prepared = prepare_trend_report(
            conn, client_id, run_year=2026, run_month=9, research_mode="manual", max_budget_usd=2.0
        )
        rid = prepared["report"]["id"]
        add_trend_sources(
            conn,
            client_id,
            rid,
            [
                {
                    "title": "Mock gelezen bron",
                    "url": "https://example.com/mock-trend",
                    "published_at": "2026-09-01",
                    "excerpt": "MOCK — fragment voor technische test, geen live research.",
                    "supported_finding": "Mock finding",
                    "certainty": "mock",
                }
            ],
            fetch_content=False,
        )
        preview = execution_preview(conn, client_id, rid, max_budget_usd=2.0)
        assert preview["paid_call"] is False
        assert preview["prompt_package"] is not None
        assert preview["prompt_package"]["primary_loaded"] is True
        assert preview["prompt_package"]["system_chars"] > 1000
        assert "Ahrefs" in " ".join(preview["prompt_package"]["missing_source_layers"])
        assert any(s.get("counted_as_read_source") for s in preview["sources_read"])
        try:
            execute_report(conn, client_id, rid, dry_run_paid=True)
            blocked = False
        except ValueError as exc:
            blocked = "dry_run_paid" in str(exc)
        assert blocked is True


def test_search_not_configured_marked_in_prepare(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "reports_nokey.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("AI_MODEL", "gemini-3.5-flash-lite")
    initialize_database()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        trend = prepare_trend_report(
            conn, client_id, run_year=2026, run_month=10, research_mode="internet"
        )
        missing = " ".join(trend["report"]["input_snapshot"]["missing"]).lower()
        assert "ai_api_key" in missing or "ontbreekt" in missing or "niet" in missing
        assert trend["report"]["input_snapshot"]["partial"] is True
        assert trend["internet_search"]["available"] is False
