"""LOCAL_TEST: Logs CSV export respects UI filters including missing classification."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from maaike.db import initialize_database, transaction
from maaike.logs_export import filter_posts, filtered_export_posts
from maaike.repository import list_posts, save_editorial


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def test_missing_filter_matches_export(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "logs_export.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    with transaction() as conn:
        qa = conn.execute(
            "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('QA Controle', ?, ?, 'not_connected')",
            (_now(), _now()),
        ).lastrowid
        now = _now()
        for i, (fmt, pillar, hook) in enumerate(
            (
                (True, True, "hook-a"),
                (False, True, "hook-b"),
                (True, False, ""),
            ),
            start=1,
        ):
            pid = conn.execute(
                """
                INSERT INTO posts (
                    client_id, platform, external_id, published_at, content_kind,
                    permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
                ) VALUES (?, 'instagram', ?, ?, 'image', ?, 'c', '', 1, 1, 0, 0, 0, 0, 1)
                """,
                (qa, f"ext-{i}", f"2026-09-0{i}T12:00:00+00:00", f"https://ig/{i}"),
            ).lastrowid
            fid = None
            pid_leg = None
            if fmt:
                fid = conn.execute(
                    "INSERT INTO content_formats (client_id, name, explanation, created_at, updated_at) VALUES (?, ?, '', ?, ?)",
                    (qa, f"F{i}", now, now),
                ).lastrowid
            if pillar:
                pid_leg = conn.execute(
                    "INSERT INTO content_pillars (client_id, name, explanation, created_at, updated_at) VALUES (?, ?, '', ?, ?)",
                    (qa, f"P{i}", now, now),
                ).lastrowid
            save_editorial(conn, qa, post_id=pid, format_id=fid, pillar_id=pid_leg, hook=hook)

        posts = list_posts(conn, qa)
        assert len(posts) == 3
        missing_any = filter_posts(posts, missing="any")
        assert len(missing_any) == 2
        missing_format = filter_posts(posts, missing="format")
        assert len(missing_format) == 1
        missing_hook = filter_posts(posts, missing="hook")
        assert len(missing_hook) == 1

        exported = filtered_export_posts(conn, qa, {"missing": "format"})
        assert len(exported) == 1
        exported_all = filtered_export_posts(conn, qa, {})
        assert len(exported_all) == 3
