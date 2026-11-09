"""Export/import package without secrets — no paid calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from maaike.activity_log import list_activity_events, record_activity
from maaike.data_transfer import (
    FORMAT_ID,
    apply_import,
    export_package,
    preview_import,
    validate_package,
)
from maaike.db import initialize_database, transaction


def test_export_import_roundtrip_no_secrets(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "xfer.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    now = datetime.now(tz=timezone.utc).isoformat()

    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        conn.execute(
            """
            INSERT INTO content_formats (client_id, name, explanation, created_at, updated_at)
            VALUES (?, 'FmtX', 'uitleg', ?, ?)
            """,
            (client_id, now, now),
        )
        fmt_id = int(conn.execute("SELECT id FROM content_formats WHERE name='FmtX'").fetchone()[0])
        conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, content_kind, permalink,
                views, likes, comments, shares, saves, clicks, reach
            ) VALUES (?, 'instagram', 'xfer1', '2026-09-01T12:00:00+00:00', 'image', 'https://ig/x',
                      1, 1, 0, 0, 0, 0, 10)
            """,
            (client_id,),
        )
        post_id = int(conn.execute("SELECT id FROM posts WHERE external_id='xfer1'").fetchone()[0])
        conn.execute(
            """
            INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at)
            VALUES (?, ?, NULL, 'hook-x', ?)
            """,
            (post_id, fmt_id, now),
        )
        record_activity(
            conn,
            client_id=client_id,
            activity_type="meta_sync",
            status="ok",
            title="Test sync",
            details="unit test",
        )

        package = export_package(conn, client_id=client_id)
        assert package["format"] == FORMAT_ID
        assert package["secrets_excluded"] is True
        blob = json.dumps(package)
        assert "user_access_token" not in blob
        assert "page_access_token" not in blob
        assert "AI_API_KEY" not in blob

        validate_package(package)
        preview = preview_import(conn, package)
        assert preview["validation"]["ok"] is True

    # Fresh DB import
    db2 = tmp_path / "xfer2.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db2))
    initialize_database()
    with transaction() as conn:
        # Rename Red Rock so import adds as update path differently — keep Red Rock, import with overwrite false
        result = apply_import(conn, package, overwrite=False)
        assert result["ok"] is True
        # Format should exist (added if missing name collision with Red Rock client)
        assert conn.execute("SELECT COUNT(*) n FROM content_formats WHERE name='FmtX'").fetchone()["n"] >= 1
        posts = conn.execute("SELECT COUNT(*) n FROM posts WHERE external_id='xfer1'").fetchone()["n"]
        assert posts >= 1
        activity = list_activity_events(conn, client_id=None, limit=50)
        assert activity["count"] >= 1


def test_validate_rejects_secrets() -> None:
    bad = {
        "format": FORMAT_ID,
        "version": 1,
        "secrets_excluded": True,
        "clients": [{"id": 1, "name": "X", "user_access_token": "secret"}],
    }
    try:
        validate_package(bad)
        raised = False
    except ValueError:
        raised = True
    assert raised
