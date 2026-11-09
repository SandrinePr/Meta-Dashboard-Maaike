"""LOCAL_TEST: post analysis snapshot includes period + format context (no paid AI)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from maaike.claude_analysis import PROMPT_VERSION, build_post_input_snapshot, load_analysis_prompt_bundle
from maaike.db import initialize_database, transaction
from maaike.repository import add_format


def test_post_snapshot_includes_period_and_format(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "post_snap.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    now = datetime.now(tz=timezone.utc).isoformat()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        add_format(conn, client_id, "R02", "LOCAL_TEST reel met projectdetail")
        fmt_id = int(
            conn.execute(
                "SELECT id FROM content_formats WHERE client_id = ? AND name = 'R02'",
                (client_id,),
            ).fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO posts (
                id, client_id, platform, external_id, published_at, content_kind,
                permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
            ) VALUES (101, ?, 'instagram', 'ext-101', '2026-09-10T12:00:00+00:00', 'reel',
                      'https://example.com/p/101', 'LOCAL_TEST caption', '', 100, 5, 1, 0, 2, NULL, 80)
            """,
            (client_id,),
        )
        conn.execute(
            """
            INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at)
            VALUES (101, ?, NULL, 'vraag', ?)
            """,
            (fmt_id, now),
        )
        conn.execute(
            """
            INSERT INTO posts (
                id, client_id, platform, external_id, published_at, content_kind,
                permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
            ) VALUES (102, ?, 'instagram', 'ext-102', '2026-09-15T09:00:00+00:00', 'image',
                      'https://example.com/p/102', 'LOCAL_TEST peer', '', 50, 2, 0, 0, 0, NULL, 40)
            """,
            (client_id,),
        )

        snap = build_post_input_snapshot(conn, client_id, 101)
        assert snap["post_id"] == 101
        assert snap["format_name"] == "R02"
        assert snap["format_tab_entry"]["explanation"]
        assert snap["context_present"]["format_catalog"] is True
        assert snap["context_present"]["period_overview"] is True
        assert snap["period_overview"]["post_count"] >= 2
        assert any(p["is_focus_post"] for p in snap["period_overview"]["peer_posts"])
        assert snap["performance_lookback"]["window_mode"] == "performance_lookback_21_to_20"
        assert snap["single_post_plus_period_context"] is True

    bundle = load_analysis_prompt_bundle()
    assert bundle["ready"] is True
    assert PROMPT_VERSION == "maaike-performance-analyse-v2"
    assert bundle["data_expectations"]["prefers_period_post_set"] is True
    assert bundle["data_expectations"]["prefers_format_catalog"] is True
