from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from maaike.db import connect, initialize_database
from maaike.monthly_trend_scheduler import ensure_monthly_trend_report
from maaike.report_metrics import build_period_metrics, resolve_period_window, trend_month_meta
from maaike.reports import inspect_client_report_data, prepare_client_report, prepare_trend_report


def _seed_temp_client(conn, *, with_figma: bool = True, with_post_ai: bool = True) -> int:
    cur = conn.execute(
        """
        INSERT INTO clients(name, created_at, updated_at)
        VALUES (?, '2026-01-02T09:00:00Z', '2026-01-02T09:00:00Z')
        """,
        ("Tijdelijke Testklant Bakkerij",),
    )
    cid = int(cur.lastrowid)

    from maaike.strategy import save_strategy

    save_strategy(
        conn,
        cid,
        start_answers={
            "website": "https://bakkerij-voorbeeld.nl",
            "bedrijfsomschrijving": "Ambachtelijk zuurdesembrood en patisserie",
            "sectoren": "Retail & horeca",
            "geografische_regio": "Regio Utrecht",
        },
        strategy_fields={"tone_of_voice": "Warm, ambachtelijk en dichtbij."},
    )

    if with_figma:
        from maaike.figma_planning import ensure_figma_tables

        ensure_figma_tables(conn)
        conn.execute(
            """
            INSERT INTO client_figma_files(
                client_id, file_key, file_name, source_url, last_synced_at, updated_at
            ) VALUES (?, 'abc123', 'Contentplanning Q4', 'https://www.figma.com/design/abc123/Contentplanning', '2026-11-01T08:00:00Z', '2026-11-01T08:00:00Z')
            """,
            (cid,),
        )
        conn.execute(
            """
            INSERT INTO figma_planning_items(
                client_id, node_id, source_url, page_name, period_year, period_month,
                code, content_kind, format_raw, format_usable, pillar_raw, pillar_usable,
                hook_raw, hook_usable, brief_excerpt, updated_at
            ) VALUES (?, '1:10', 'https://www.figma.com/design/abc123/Contentplanning',
                      'November 2026', 2026, 11, 'C05', 'Reel',
                      'Korte Reel', 1, 'Vakmanschap', 1, 'Kijkje in de oven', 1,
                      'Zuurdesem uit de steenoven', '2026-11-01T08:00:00Z')
            """,
            (cid,),
        )

    sample_posts = [
        ("ig-mar-1", "2026-03-14T10:00:00+00:00", "reel", "Voorjaarsbrood uit de oven", 1200, 80),
        ("ig-jun-1", "2026-06-18T11:00:00+00:00", "carousel", "5 tips voor krokante korst", 1450, 95),
        ("ig-sep-25", "2026-09-25T09:30:00+00:00", "image", "Herfstspecial pompoenbrood", 980, 52),
        ("ig-oct-28", "2026-10-28T12:00:00+00:00", "reel", "Kijkje achter de schermen om 05:00", 2100, 140),
        ("ig-nov-12", "2026-11-12T15:00:00+00:00", "carousel", "Sinterklaas speculaasbrood", 1890, 125),
    ]
    last_post_id = None
    for ext_id, published_at, kind, caption, reach, likes in sample_posts:
        c = conn.execute(
            """
            INSERT INTO posts(
                client_id, platform, external_id, published_at, content_kind,
                permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
            ) VALUES (?, 'instagram', ?, ?, ?, 'https://instagram.com/p/x', ?, '', ?, ?, 12, 3, 18, 0, ?)
            """,
            (cid, ext_id, published_at, kind, caption, reach + 200, likes, reach),
        )
        last_post_id = int(c.lastrowid)

    if with_post_ai and last_post_id:
        from maaike.claude_analysis import ensure_analysis_tables

        ensure_analysis_tables(conn)
        conn.execute(
            """
            INSERT INTO post_ai_analyses(
                client_id, post_id, provider, model, prompt_version, status,
                started_at, finished_at, insight_text, action_text, rating_text, raw_response_json
            ) VALUES (?, ?, 'mock', 'mock-v1', 'v2', 'completed',
                      '2026-11-15T10:00:00Z', '2026-11-15T10:00:05Z',
                      'Sterke visuele opening in de bakkerij.', 'Herhaal dit format in december.', 'goed',
                      '{"hook_quality":"sterk","summary":"Sterke visuele opening in de bakkerij."}')
            """,
            (cid, last_post_id),
        )

    conn.commit()
    return cid


def test_point_27_standalone_trend_report_has_no_client_period_or_x_plus_2(tmp_path: Path) -> None:
    db_path = tmp_path / "p27.db"
    initialize_database(db_path)
    conn = connect(db_path)
    cid = _seed_temp_client(conn)

    meta = trend_month_meta(2026, 11)
    assert meta["scope"] == "algemeen_per_kanaal"
    assert "lookback_start" not in meta
    assert "planning_year" not in meta
    assert "planning_month" not in meta
    assert len(meta["channels"]) >= 5

    prep = prepare_trend_report(conn, cid, run_year=2026, run_month=11)
    rep = prep["report"]
    assert rep["title"] == "Algemeen trendrapport – november 2026"
    assert rep.get("planning_year") is None
    assert rep.get("planning_month") is None

    row = conn.execute("SELECT * FROM client_reports WHERE id = ?", (rep["id"],)).fetchone()
    assert row["planning_year"] is None
    assert row["planning_month"] is None
    snap = rep["input_snapshot"]
    assert snap["scope"] == "algemeen_per_kanaal"
    assert "client_strategy" not in snap
    assert "lookback_start" not in snap.get("period", {})
    conn.close()


def test_point_28_first_of_month_amsterdam_schedule_and_idempotency(tmp_path: Path) -> None:
    db_path = tmp_path / "p28.db"
    initialize_database(db_path)
    conn = connect(db_path)
    _seed_temp_client(conn)

    # 31 okt 2026 om 23:30 UTC == 1 nov 2026 om 00:30 Europe/Amsterdam -> dag 1 in Amsterdam!
    utc_edge = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
    first = ensure_monthly_trend_report(
        conn,
        now_amsterdam=utc_edge,
        simulate_without_paid_ai=True,
        only_on_first_of_month=True,
    )
    assert first["skipped"] is False
    assert first["created"] is True
    assert first["period_year"] == 2026
    assert first["period_month"] == 11
    assert first["timezone"] == "Europe/Amsterdam"
    assert first["title"] == "Algemeen trendrapport – november 2026"
    assert first["paid_ai_called"] is False

    # Herstart / nieuwe poging op dezelfde 1e van de maand mag GEEN duplicaat maken
    retry = ensure_monthly_trend_report(
        conn,
        now_amsterdam=datetime(2026, 11, 1, 9, 15, tzinfo=ZoneInfo("Europe/Amsterdam")),
        simulate_without_paid_ai=True,
        only_on_first_of_month=True,
    )
    assert retry["created"] is False
    assert retry["deduped"] is True
    assert retry["report_id"] == first["report_id"]
    assert retry["paid_ai_called"] is False

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM client_reports WHERE report_type = 'trend' AND period_year = 2026 AND period_month = 11"
    ).fetchone()["n"]
    assert count == 1

    # Op de 2e van de maand met only_on_first_of_month=True doet de primaire tick niets
    non_first = ensure_monthly_trend_report(
        conn,
        now_amsterdam=datetime(2026, 12, 2, 6, 0, tzinfo=ZoneInfo("Europe/Amsterdam")),
        simulate_without_paid_ai=True,
        only_on_first_of_month=True,
    )
    assert non_first["skipped"] is True

    # Inhaalrun na de 1e (zonder only_on_first) mag een gemiste maand alsnog aanmaken
    catchup = ensure_monthly_trend_report(
        conn,
        now_amsterdam=datetime(2026, 12, 2, 7, 0, tzinfo=ZoneInfo("Europe/Amsterdam")),
        simulate_without_paid_ai=True,
        only_on_first_of_month=False,
        allow_catchup_after_first=True,
        enforce_due_time=True,
    )
    assert catchup["skipped"] is False
    assert catchup["created"] is True
    assert catchup["caught_up"] is True
    assert catchup["period_year"] == 2026
    assert catchup["period_month"] == 12
    assert catchup["paid_ai_called"] is False
    conn.close()


def _mark_trend_as_real_completed(conn, report_id: int) -> None:
    """Promote a simulated trend row into a real completed report for client-report tests."""
    import json

    row = conn.execute("SELECT body_json FROM client_reports WHERE id = ?", (report_id,)).fetchone()
    body = json.loads(row["body_json"] or "{}")
    body.pop("simulation_without_paid_ai", None)
    body.pop("test_label", None)
    body["label"] = "Echt trendrapport (testdata zonder simulatievlag)"
    conn.execute(
        """
        UPDATE client_reports
        SET status = 'completed', is_mock = 0, body_json = ?,
            usage_json = '{"status":"completed","paid_ai_called":true}',
            updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(body, ensure_ascii=False), datetime.now(tz=timezone.utc).isoformat(), report_id),
    )


def test_point_29_automatic_21_to_20_periods_and_year_rollover() -> None:
    # November 2026: 21 okt t/m 20 nov vs 21 sep t/m 20 okt
    nov = resolve_period_window(period_year=2026, period_month=11)
    assert nov["start"] == "2026-10-21"
    assert nov["end"] == "2026-11-20"
    assert nov["previous_start"] == "2026-09-21"
    assert nov["previous_end"] == "2026-10-20"
    assert "21 oktober" in nov["label_nl"] and "20 november" in nov["label_nl"]
    assert "21 september" in nov["compare_label_nl"] and "20 oktober" in nov["compare_label_nl"]

    # Jaarwisseling januari 2027: 21 dec 2026 t/m 20 jan 2027 vs 21 nov 2026 t/m 20 dec 2026
    jan = resolve_period_window(period_year=2027, period_month=1)
    assert jan["start"] == "2026-12-21"
    assert jan["end"] == "2027-01-20"
    assert jan["previous_start"] == "2026-11-21"
    assert jan["previous_end"] == "2026-12-20"
    assert jan["crosses_year_boundary"] is True
    assert jan["label_nl"] == "21 december 2026 t/m 20 januari 2027"
    assert jan["compare_label_nl"] == "21 november 2026 t/m 20 december 2026"

    # Jaarwisseling in vergelijkingsperiode februari 2027:
    # analyse 21 jan 2027 t/m 20 feb 2027 vs vergelijking 21 dec 2026 t/m 20 jan 2027
    feb = resolve_period_window(period_year=2027, period_month=2)
    assert feb["start"] == "2027-01-21"
    assert feb["end"] == "2027-02-20"
    assert feb["previous_start"] == "2026-12-21"
    assert feb["previous_end"] == "2027-01-20"
    assert feb["compare_label_nl"] == "21 december 2026 t/m 20 januari 2027"


def test_points_30_31_32_33_calendar_year_formats_mandatory_trend_and_sources(tmp_path: Path) -> None:
    db_path = tmp_path / "p30_33.db"
    initialize_database(db_path)
    conn = connect(db_path)
    cid = _seed_temp_client(conn, with_figma=False, with_post_ai=True)

    # Punt 30: kalenderjaar 1 jan 2026 t/m 20 nov 2026 telt alle 5 eigen berichten uit 2026 mee
    bundle = build_period_metrics(conn, cid, period_year=2026, period_month=11)
    assert bundle["metrics"]["post_count"] == 2  # 28 okt + 12 nov
    assert bundle["previous_metrics"]["post_count"] == 1  # 25 sep
    fmt_win = bundle["format_pattern_window"]
    assert fmt_win["start"] == "2026-01-01"
    assert fmt_win["end"] == "2026-11-20"
    assert fmt_win["label_nl"] == "1 januari 2026 t/m 20 november 2026"
    assert fmt_win["post_count"] == 5

    # Punt 31, 32, 33: vóórdat trendrapport nov 2026 bestaat -> can_start_analysis == False en prepare blokkeert
    insp_missing = inspect_client_report_data(conn, cid, period_year=2026, period_month=11)
    assert insp_missing["can_start_analysis"] is False
    sources_by_id = {s["id"]: s for s in insp_missing["sources_overview"]["sources"]}
    assert set(sources_by_id.keys()) == {"strategy", "posts", "post_insights", "figma", "trend"}
    assert sources_by_id["trend"]["required"] is True
    assert sources_by_id["trend"]["ready"] is False
    assert sources_by_id["trend"]["user_action_needed"] is True
    assert sources_by_id["figma"]["required"] is False
    assert sources_by_id["figma"]["requirement_label"] == "Later aan te vullen"

    with pytest.raises(ValueError, match="trendrapport"):
        prepare_client_report(conn, cid, period_year=2026, period_month=11)

    # Gesimuleerd trendrapport mag NIET als bron voor een echt klantrapport dienen
    trend_sim = ensure_monthly_trend_report(conn, year=2026, month=11, simulate_without_paid_ai=True)
    assert trend_sim["report_id"] > 0
    insp_sim = inspect_client_report_data(conn, cid, period_year=2026, period_month=11)
    assert insp_sim["can_start_analysis"] is False
    sim_sources = {s["id"]: s for s in insp_sim["sources_overview"]["sources"]}
    assert sim_sources["trend"]["ready"] is False
    assert sim_sources["trend"]["status"] == "simulated_not_usable"
    with pytest.raises(ValueError, match="gesimuleerd"):
        prepare_client_report(conn, cid, period_year=2026, period_month=11)

    # Echt (niet-gesimuleerd) trendrapport voor november 2026 -> starten toegestaan
    _mark_trend_as_real_completed(conn, trend_sim["report_id"])
    insp_ready = inspect_client_report_data(conn, cid, period_year=2026, period_month=11)
    assert insp_ready["can_start_analysis"] is True
    assert insp_ready["linked_trend"]["id"] == trend_sim["report_id"]
    ready_sources = {s["id"]: s for s in insp_ready["sources_overview"]["sources"]}
    assert ready_sources["trend"]["ready"] is True
    assert ready_sources["figma"]["ready"] is False
    assert ready_sources["figma"]["required"] is False

    prep_client = prepare_client_report(conn, cid, period_year=2026, period_month=11)
    snap = prep_client["report"]["input_snapshot"]
    assert snap["linked_trend"]["id"] == trend_sim["report_id"]
    assert snap["format_pattern_window"]["label_nl"] == "1 januari 2026 t/m 20 november 2026"
    conn.close()


def test_api_monthly_trend_simulation_and_report_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "api_reports.db"
    initialize_database(db_path)
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MAAIKE_PERSIST_ENABLED", "0")
    monkeypatch.setenv("MAAIKE_CRON_SECRET", "test-cron-secret-point-28")

    from maaike_web.app import create_app

    app = create_app()
    with TestClient(app) as http:
        conn = connect(db_path)
        cid = _seed_temp_client(conn, with_figma=True, with_post_ai=True)
        conn.close()

        sim = http.post(
            "/api/report-planning/monthly-trend/simulate",
            json={"year": 2026, "month": 11, "simulate_without_paid_ai": True},
        )
        assert sim.status_code == 200
        sim_data = sim.json()
        assert sim_data["created"] is True
        assert sim_data["paid_ai_called"] is False

        sim_dup = http.post(
            "/api/report-planning/monthly-trend/simulate",
            json={"year": 2026, "month": 11, "simulate_without_paid_ai": True},
        )
        assert sim_dup.status_code == 200
        assert sim_dup.json()["created"] is False
        assert sim_dup.json()["deduped"] is True
        assert sim_dup.json()["paid_ai_called"] is False

        # Gesimuleerd trendrapport blokkeert klantrapport-prepare
        blocked = http.post(
            f"/api/clients/{cid}/reports/client/prepare",
            json={"period_year": 2026, "period_month": 11},
        )
        assert blocked.status_code == 400
        assert "gesimuleerd" in blocked.json()["detail"].lower()

        # Externe wake-up trigger: catch-up na de 1e in simulatiestand, daarna dedupe
        catchup = http.post(
            "/api/report-planning/monthly-trend/trigger",
            headers={"X-Cron-Secret": "test-cron-secret-point-28"},
            json={
                "mode": "simulation",
                "simulated_datetime": "2027-02-03T07:15:00+01:00",
                "trigger_source": "unit_test_catchup",
            },
        )
        assert catchup.status_code == 200
        catch_body = catchup.json()
        assert catch_body["paid_ai_called"] is False
        assert catch_body["created"] is True
        assert catch_body["caught_up"] is True
        assert catch_body["period_year"] == 2027
        assert catch_body["period_month"] == 2

        catchup_dup = http.post(
            "/api/report-planning/monthly-trend/trigger",
            headers={"X-Cron-Secret": "test-cron-secret-point-28"},
            json={
                "mode": "simulation",
                "simulated_datetime": "2027-02-03T08:00:00+01:00",
                "trigger_source": "unit_test_catchup_retry",
            },
        )
        assert catchup_dup.status_code == 200
        assert catchup_dup.json()["created"] is False
        assert catchup_dup.json()["deduped"] is True
        assert catchup_dup.json()["paid_ai_called"] is False

        bad_auth = http.post(
            "/api/report-planning/monthly-trend/trigger",
            headers={"X-Cron-Secret": "wrong"},
            json={"mode": "simulation", "year": 2027, "month": 3},
        )
        assert bad_auth.status_code == 401

        status = http.get("/api/report-planning/monthly-trend")
        assert status.status_code == 200
        st = status.json()
        assert st["external_trigger_configured"] is True
        assert st["external_trigger_endpoint"] == "/api/report-planning/monthly-trend/trigger"
        assert st["catchup_after_first_enabled"] is True
        assert st["timezone"] == "Europe/Amsterdam"

        listing = http.get(f"/api/clients/{cid}/reports")
        assert listing.status_code == 200
        ids = {r["id"] for r in listing.json()["reports"]}
        assert sim_data["report_id"] in ids
        assert catch_body["report_id"] in ids
