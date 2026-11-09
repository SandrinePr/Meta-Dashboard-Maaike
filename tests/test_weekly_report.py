"""Weekly report math and saved snapshots. No Meta and no live AI calls."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ai.analyze import can_request_analysis, parse_analysis_text, run_analysis
from ai.config import AiConfig, public_ai_status
from analytics.weekly_report import (
    INSUFFICIENT,
    NOT_AVAILABLE,
    RANKING_BASIS,
    STAND_LABEL,
    build_weekly_snapshot,
    previous_complete_week,
    week_containing,
)
from db.comparison_repository import (
    ROLE_COMPETITOR,
    ROLE_OWN,
    start_fetch_run,
    upsert_account_measurement,
    upsert_comparison_account,
    upsert_comparison_post,
    upsert_post_measurement,
)
from db.database import get_connection, initialize_database
from db.weekly_report_repository import get_weekly_report, save_analysis, save_weekly_report
from reports.weekly_html import build_weekly_report_html

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
WEEK_START = date(2026, 10, 12)
WEEK_END = date(2026, 10, 18)


def _setup(tmp_path: Path, monkeypatch) -> Path:
    db_path = tmp_path / "weekly.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setattr("db.database.ensure_seed_database", lambda *args, **kwargs: False)
    initialize_database(db_path)
    return db_path


def _at(day: date, hour: int = 12) -> str:
    local = datetime(day.year, day.month, day.day, hour, 0, tzinfo=AMSTERDAM)
    return local.astimezone(timezone.utc).isoformat()


def _account(conn, external_id: str, username: str, role: str) -> int:
    return upsert_comparison_account(
        conn,
        external_id=external_id,
        username=username,
        name=username,
        comparison_role=role,
    )


def _post(
    conn,
    account_id: int,
    external_id: str,
    published: str,
    *,
    text: str | None = None,
    media_type: str | None = "IMAGE",
    media_product_type: str | None = None,
) -> int:
    result = upsert_comparison_post(
        conn,
        account_id=account_id,
        external_id=external_id,
        text=text,
        permalink=f"https://instagram.example/{external_id}",
        media_type=media_type,
        media_product_type=media_product_type,
        published_at=published,
        raw_json=None,
    )
    return result.row_id


def _measure_post(conn, post_id: int, when: str, likes: int | None, comments: int | None) -> None:
    run_id = start_fetch_run(
        conn,
        trigger_source="test",
        measured_at=when,
        period_start=when,
        period_end=when,
    )
    upsert_post_measurement(
        conn,
        post_id=post_id,
        fetch_run_id=run_id,
        measured_at=when,
        like_count=likes,
        comments_count=comments,
    )


def _measure_followers(conn, account_id: int, when: str, followers: int) -> None:
    run_id = start_fetch_run(
        conn,
        trigger_source="test",
        measured_at=when,
        period_start=when,
        period_end=when,
    )
    upsert_account_measurement(
        conn,
        account_id=account_id,
        fetch_run_id=run_id,
        measured_at=when,
        followers_count=followers,
        media_count=None,
    )


def _snapshot(own_id: int, competitors: list[str] | None = None) -> dict:
    return build_weekly_snapshot(
        period_start=WEEK_START,
        period_end=WEEK_END,
        own_account_id=own_id,
        competitor_usernames=competitors or [],
    )


def test_previous_complete_week() -> None:
    assert previous_complete_week(date(2026, 10, 20)) == (WEEK_START, WEEK_END)
    assert previous_complete_week(date(2026, 10, 19)) == (WEEK_START, WEEK_END)
    assert week_containing(date(2026, 10, 14)) == (WEEK_START, WEEK_END)


def test_single_measurement_is_not_a_week_result(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-1", "own.account", ROLE_OWN)
        post_id = _post(conn, own, "post-1", _at(date(2026, 9, 1)))
        _measure_post(conn, post_id, _at(date(2026, 10, 16)), 500, 20)
        _measure_followers(conn, own, _at(date(2026, 10, 16)), 900)
        conn.commit()

    snapshot = _snapshot(own)
    own_block = snapshot["own"]
    assert own_block["likes_delta"] is None
    assert own_block["comments_delta"] is None
    assert own_block["interaction_status"] == "insufficient"
    assert own_block["followers_stand"] == 900
    assert own_block["followers_delta"] is None
    assert own_block["followers_delta_status"] == "insufficient"
    assert snapshot["ranked_posts"] == []
    assert "500" not in snapshot["summary"]
    assert "900" in snapshot["summary"]
    assert "onvoldoende meetgegevens" in snapshot["summary"]


def test_delta_between_close_measurements(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-2", "own.delta", ROLE_OWN)
        post_id = _post(conn, own, "post-2", _at(date(2026, 9, 2)), text="Kijk hier")
        _measure_post(conn, post_id, _at(date(2026, 10, 11), 13), 10, 1)
        _measure_post(conn, post_id, _at(date(2026, 10, 16), 13), 25, 4)
        _measure_followers(conn, own, _at(date(2026, 10, 11), 13), 1000)
        _measure_followers(conn, own, _at(date(2026, 10, 16), 13), 1012)
        conn.commit()

    snapshot = _snapshot(own)
    own_block = snapshot["own"]
    assert own_block["likes_delta"] == 15
    assert own_block["comments_delta"] == 3
    assert own_block["followers_delta"] == 12
    assert "vlak vóór de week" in own_block["followers_note"]
    assert snapshot["ranked_posts"][0]["interaction_delta"] == 18
    assert snapshot["ranked_posts"][0]["basis"] == "voor_de_week"
    assert "+15" in snapshot["summary"]
    assert "+3" in snapshot["summary"]


def test_old_baseline_is_not_called_a_week_result(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-3", "own.old", ROLE_OWN)
        post_id = _post(conn, own, "post-3", _at(date(2026, 8, 1)))
        _measure_post(conn, post_id, _at(date(2026, 10, 1)), 10, 0)
        _measure_post(conn, post_id, _at(date(2026, 10, 16)), 400, 8)
        conn.commit()

    snapshot = _snapshot(own)
    assert snapshot["own"]["likes_delta"] is None
    assert snapshot["ranked_posts"] == []
    assert "400" not in snapshot["summary"]


def test_two_measurements_inside_the_week(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-4", "own.partial", ROLE_OWN)
        post_id = _post(conn, own, "post-4", _at(date(2026, 9, 3)))
        _measure_post(conn, post_id, _at(date(2026, 10, 14), 10), 10, 1)
        _measure_post(conn, post_id, _at(date(2026, 10, 16), 10), 18, 3)
        conn.commit()

    snapshot = _snapshot(own)
    ranked = snapshot["ranked_posts"][0]
    assert ranked["likes_delta"] == 8
    assert ranked["comments_delta"] == 2
    assert ranked["basis"] == "binnen_de_week"
    assert "binnen de week" in ranked["basis_label"]
    assert "niet over de volledige week" in snapshot["measurement_window_notice"]
    assert "14-10-2026" in snapshot["measurement_window_notice"]
    assert "16-10-2026" in snapshot["measurement_window_notice"]
    assert snapshot["summary"].startswith(snapshot["measurement_window_notice"])


def test_published_post_stand_is_separate_from_week_delta(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-5", "own.new", ROLE_OWN)
        post_id = _post(
            conn,
            own,
            "post-5",
            _at(date(2026, 10, 14), 9),
            text="Eerste zin\nmeer tekst",
        )
        _measure_post(conn, post_id, _at(date(2026, 10, 16)), 40, 2)
        conn.commit()

    snapshot = _snapshot(own)
    assert snapshot["own"]["posts_published"] == 1
    assert snapshot["ranked_posts"] == []
    published = snapshot["published_posts"][0]
    assert published["opening_line"] == "Eerste zin"
    assert published["stand_likes"] == 40
    assert published["stand_label"] == STAND_LABEL
    assert "40" not in snapshot["summary"]


def test_competitor_without_measurements_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-6", "own.cmp", ROLE_OWN)
        _account(conn, "comp-6", "comp.empty", ROLE_COMPETITOR)
        post_id = _post(conn, own, "post-6", _at(date(2026, 9, 4)))
        _measure_post(conn, post_id, _at(date(2026, 10, 11)), 1, 1)
        _measure_post(conn, post_id, _at(date(2026, 10, 16)), 3, 2)
        conn.commit()

    snapshot = _snapshot(own, ["comp.empty"])
    competitor = snapshot["competitors"][0]
    assert competitor["display_name"] == "@comp.empty"
    assert competitor["interaction_status"] == "unavailable"
    assert competitor["likes_delta"] is None
    assert competitor["posts_published"] is None
    assert competitor["posts_published_coverage"] == "unavailable"
    assert competitor["followers_delta"] != 0


def test_ranking_uses_interaction_sum(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-7", "own.rank", ROLE_OWN)
        low = _post(conn, own, "low", _at(date(2026, 9, 5)))
        high = _post(conn, own, "high", _at(date(2026, 9, 6)))
        for post_id, start_likes, end_likes in ((low, 1, 4), (high, 2, 20)):
            _measure_post(conn, post_id, _at(date(2026, 10, 11)), start_likes, 0)
            _measure_post(conn, post_id, _at(date(2026, 10, 16)), end_likes, 0)
        conn.commit()

    snapshot = _snapshot(own)
    assert snapshot["ranked_posts"][0]["post_id"] == high
    assert [row["interaction_delta"] for row in snapshot["ranked_posts"]] == [18, 3]
    assert snapshot["ranking_basis"] == RANKING_BASIS


def test_content_type_average_uses_only_measured_deltas(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-8", "own.types", ROLE_OWN)
        reel_a = _post(
            conn, own, "reel-a", _at(date(2026, 9, 7)),
            media_type="VIDEO", media_product_type="REELS",
        )
        reel_b = _post(
            conn, own, "reel-b", _at(date(2026, 9, 8)),
            media_type="VIDEO", media_product_type="REELS",
        )
        image = _post(conn, own, "image-a", _at(date(2026, 10, 14), 8), media_type="IMAGE")
        _measure_post(conn, reel_a, _at(date(2026, 10, 11)), 0, 0)
        _measure_post(conn, reel_a, _at(date(2026, 10, 16)), 10, 0)
        _measure_post(conn, reel_b, _at(date(2026, 10, 11)), 0, 0)
        _measure_post(conn, reel_b, _at(date(2026, 10, 16)), 30, 0)
        _measure_post(conn, image, _at(date(2026, 10, 16)), 99, 9)
        conn.commit()

    snapshot = _snapshot(own)
    by_type = {row["type"]: row for row in snapshot["content_types"]}
    assert by_type["reel"]["interaction_avg"] == 20
    assert by_type["reel"]["comparable_posts"] == 2
    assert by_type["image"]["performance_status"] == "insufficient"
    assert by_type["image"]["interaction_avg"] is None
    assert by_type["image"]["published_count"] == 1
    assert "altijd beter werkt" in snapshot["summary"]
    assert "99" not in snapshot["summary"]


def test_save_and_reopen_does_not_call_ai(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    def _forbid_network(*_args, **_kwargs):
        raise AssertionError("AI of netwerk aangeroepen")

    monkeypatch.setattr("ai.analyze.requests.post", _forbid_network)
    with get_connection() as conn:
        own = _account(conn, "own-9", "own.save", ROLE_OWN)
        post_id = _post(conn, own, "post-9", _at(date(2026, 9, 9)))
        _measure_post(conn, post_id, _at(date(2026, 10, 11)), 5, 1)
        _measure_post(conn, post_id, _at(date(2026, 10, 16)), 8, 1)
        conn.commit()

    snapshot = _snapshot(own)
    with get_connection() as conn:
        report_id = save_weekly_report(
            conn,
            period_start=snapshot["period_start"],
            period_end=snapshot["period_end"],
            own_account_id=own,
            account_label=snapshot["account_label"],
            snapshot=snapshot,
        )
        stored = get_weekly_report(conn, report_id)
        conn.commit()

    assert stored is not None
    assert stored.ai_status == "not_configured"
    assert stored.ai_advice == []
    assert stored.snapshot["own"]["likes_delta"] == 3
    assert stored.period_start == "2026-10-12"
    assert stored.created_at


def test_html_export_labels_missing_data(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-10", "own.html", ROLE_OWN)
        post_id = _post(conn, own, "post-10", _at(date(2026, 10, 15), 11), text="Hallo <b>wereld")
        _measure_post(conn, post_id, _at(date(2026, 10, 16)), 7, 1)
        conn.commit()

    snapshot = _snapshot(own)
    document = build_weekly_report_html(snapshot)
    assert STAND_LABEL in document
    assert RANKING_BASIS in document
    assert INSUFFICIENT in document
    assert "AI is nog niet ingesteld" in document
    assert "volledige week" in document
    assert "<b>wereld" not in document
    assert "Hallo" in document
    assert NOT_AVAILABLE in document


def test_public_ai_status_hides_the_key() -> None:
    status = public_ai_status(
        AiConfig(
            base_url="https://api.example.com/v1?api_key=super-secret",
            api_key="super-secret",
            model="example-model",
        )
    )
    assert "super-secret" not in json.dumps(status)
    assert status["base_host"] == "api.example.com"
    assert status["has_api_key"] is True
    assert status["model"] == "example-model"
    assert status["configured"] is True


def test_analysis_not_configured_makes_no_request(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("ai.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("AI_BASE_URL", "")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("AI_MODEL", "")

    def _forbid_network(*_args, **_kwargs):
        raise AssertionError("netwerk aangeroepen")

    monkeypatch.setattr("ai.analyze.requests.post", _forbid_network)
    result = run_analysis({}, system_prompt="x", user_prompt="{snapshot_json}")
    assert result.status == "not_configured"
    assert result.advice == []
    assert can_request_analysis("not_configured", configured=False) is False
    assert can_request_analysis("stored", configured=True) is False


def test_analysis_parses_only_complete_advice(monkeypatch) -> None:
    parsed = parse_analysis_text(
        '```json\n{"summary":"Kort","advice":["een","twee","drie"]}\n```'
    )
    assert parsed == ("Kort", ["een", "twee", "drie"])
    assert parse_analysis_text('{"summary":"Kort","advice":["een","twee"]}') is None

    monkeypatch.setattr("ai.config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("AI_MODEL", "test-model")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"summary": "Alleen toelichting", "advice": ["a", "b", "c"]}
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr("ai.analyze.requests.post", lambda *args, **kwargs: _Response())
    result = run_analysis({"likes_delta": 1}, system_prompt="sys", user_prompt="{snapshot_json}")
    assert result.status == "stored"
    assert result.advice == ["a", "b", "c"]
    assert result.model == "test-model"

    class _BadResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "geen json"}}]}

    monkeypatch.setattr("ai.analyze.requests.post", lambda *args, **kwargs: _BadResponse())
    failed = run_analysis({}, system_prompt="sys", user_prompt="tekst")
    assert failed.status == "error"
    assert failed.advice == []
    assert failed.summary is None


def test_stored_analysis_roundtrip(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        report_id = save_weekly_report(
            conn,
            period_start="2026-10-12",
            period_end="2026-10-18",
            own_account_id=None,
            account_label="@own.save",
            snapshot={"version": 1, "summary": "Berekend"},
        )
        save_analysis(
            conn,
            report_id,
            status="stored",
            summary="Toelichting",
            advice=["een", "twee", "drie"],
            model="test-model",
        )
        stored = get_weekly_report(conn, report_id)
        conn.commit()
    assert stored is not None
    assert stored.ai_status == "stored"
    assert stored.ai_advice == ["een", "twee", "drie"]
    assert stored.snapshot["summary"] == "Berekend"


def test_negative_delta_is_kept(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = _account(conn, "own-11", "own.drop", ROLE_OWN)
        post_id = _post(conn, own, "drop", _at(date(2026, 9, 11)))
        _measure_post(conn, post_id, _at(date(2026, 10, 11)), 20, 5)
        _measure_post(conn, post_id, _at(date(2026, 10, 16)), 15, 5)
        conn.commit()

    snapshot = _snapshot(own)
    assert snapshot["own"]["likes_delta"] == -5
    assert snapshot["ranked_posts"][0]["likes_delta"] == -5
