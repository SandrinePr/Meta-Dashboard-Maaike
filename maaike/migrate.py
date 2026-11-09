"""Upgrade an older single-client Maaike database without touching TAOL."""

from __future__ import annotations

import sqlite3

RED_ROCK_NAME = "Red Rock"
# Created during the first local check of this entry. Reel B1 was stored as a
# content format, but it is a planning code. Remove only this exact unused pair.
_TEST_FORMAT = (
    "Reel B1",
    "Korte video die opent met een eerste zin. Aanvulling na herstart.",
)
_TEST_PILLAR = (
    "Bewijs",
    "Resultaat dat de klant kan laten zien.",
)


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Create client tables and move existing rows to Red Rock."""
    conn.execute("PRAGMA foreign_keys = OFF;")
    if _table_exists(conn, "content_formats") and not _has_column(conn, "content_formats", "client_id"):
        _rebuild_legacy_tables(conn)
    from pathlib import Path

    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    _add_missing_columns(conn)
    _ensure_red_rock(conn)
    _once(conn, "drop_unused_agent_test_legend_20261027", _remove_known_test_items)
    _once(conn, "seed_content_hooks_from_editorial_20261102", _seed_hooks_from_editorial)
    conn.execute("PRAGMA foreign_keys = ON;")


def _rebuild_legacy_tables(conn: sqlite3.Connection) -> None:
    for name in ("post_editorial", "posts", "content_formats", "content_pillars"):
        if _table_exists(conn, name):
            conn.execute(f"ALTER TABLE {name} RENAME TO {name}_legacy")


def _ensure_red_rock(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM clients WHERE name = ? COLLATE NOCASE",
        (RED_ROCK_NAME,),
    ).fetchone()
    if row is not None:
        client_id = int(row[0])
    else:
        from datetime import datetime, timezone

        now = datetime.now(tz=timezone.utc).isoformat()
        cursor = conn.execute(
            """
            INSERT INTO clients (name, created_at, updated_at, meta_status)
            VALUES (?, ?, ?, 'not_connected')
            """,
            (RED_ROCK_NAME, now, now),
        )
        client_id = int(cursor.lastrowid)
    if _table_exists(conn, "content_formats_legacy"):
        _copy_legacy(conn, client_id)
    return client_id


def _copy_legacy(conn: sqlite3.Connection, client_id: int) -> None:
    if _is_empty(conn, "content_formats") and _table_exists(conn, "content_formats_legacy"):
        conn.execute(
            """
            INSERT INTO content_formats (id, client_id, name, explanation, created_at, updated_at)
            SELECT id, ?, name, explanation, created_at, updated_at
            FROM content_formats_legacy
            """,
            (client_id,),
        )
    if _is_empty(conn, "content_pillars") and _table_exists(conn, "content_pillars_legacy"):
        conn.execute(
            """
            INSERT INTO content_pillars (id, client_id, name, explanation, created_at, updated_at)
            SELECT id, ?, name, explanation, created_at, updated_at
            FROM content_pillars_legacy
            """,
            (client_id,),
        )
    if _is_empty(conn, "posts") and _table_exists(conn, "posts_legacy"):
        conn.execute(
            """
            INSERT INTO posts (
                id, client_id, platform, external_id, published_at, content_kind, permalink,
                views, likes, comments, shares, saves, clicks, last_synced_at
            )
            SELECT
                id, ?, platform, external_id, published_at, content_kind, permalink,
                views, likes, comments, shares, saves, clicks, last_synced_at
            FROM posts_legacy
            """,
            (client_id,),
        )
    if _is_empty(conn, "post_editorial") and _table_exists(conn, "post_editorial_legacy"):
        conn.execute(
            """
            INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at)
            SELECT post_id, format_id, pillar_id, hook, updated_at
            FROM post_editorial_legacy
            """
        )
    for name in ("post_editorial_legacy", "posts_legacy", "content_formats_legacy", "content_pillars_legacy"):
        if _table_exists(conn, name):
            conn.execute(f"DROP TABLE {name}")


def _once(conn: sqlite3.Connection, name: str, action) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS maaike_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    seen = conn.execute(
        "SELECT 1 FROM maaike_migrations WHERE name = ?",
        (name,),
    ).fetchone()
    if seen is not None:
        return
    action(conn)
    from datetime import datetime, timezone

    conn.execute(
        "INSERT INTO maaike_migrations (name, applied_at) VALUES (?, ?)",
        (name, datetime.now(tz=timezone.utc).isoformat()),
    )


def _remove_known_test_items(conn: sqlite3.Connection) -> None:
    _remove_unused_item(conn, "content_formats", "format_id", *_TEST_FORMAT)
    _remove_unused_item(conn, "content_pillars", "pillar_id", *_TEST_PILLAR)


def _seed_hooks_from_editorial(conn: sqlite3.Connection) -> None:
    """One-time: copy distinct existing post hooks into the per-client hook legend."""
    if not _table_exists(conn, "content_hooks") or not _table_exists(conn, "post_editorial"):
        return
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc).isoformat()
    rows = conn.execute(
        """
        SELECT p.client_id AS client_id, TRIM(e.hook) AS hook
        FROM post_editorial e
        JOIN posts p ON p.id = e.post_id
        WHERE e.hook IS NOT NULL AND TRIM(e.hook) != ''
        GROUP BY p.client_id, TRIM(e.hook) COLLATE NOCASE
        """
    ).fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        hook = str(row["hook"] or "").strip()
        if not hook:
            continue
        exists = conn.execute(
            """
            SELECT 1 FROM content_hooks
            WHERE client_id = ? AND name = ? COLLATE NOCASE
            """,
            (client_id, hook),
        ).fetchone()
        if exists is not None:
            continue
        conn.execute(
            """
            INSERT INTO content_hooks (client_id, name, explanation, created_at, updated_at)
            VALUES (?, ?, '', ?, ?)
            """,
            (client_id, hook, now, now),
        )


def _remove_unused_item(
    conn: sqlite3.Connection,
    table: str,
    editorial_column: str,
    name: str,
    explanation: str,
) -> None:
    rows = conn.execute(
        f"SELECT id, explanation FROM {table} WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchall()
    for row in rows:
        if str(row[1] or "") != explanation:
            continue
        item_id = int(row[0])
        used = conn.execute(
            f"SELECT 1 FROM post_editorial WHERE {editorial_column} = ? LIMIT 1",
            (item_id,),
        ).fetchone()
        if used is not None:
            continue
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))


def _is_empty(conn: sqlite3.Connection, table: str) -> bool:
    if not _table_exists(conn, table):
        return False
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(count[0]) == 0


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Add fetch columns to a database created before post sync existed."""
    if not _table_exists(conn, "posts"):
        return
    for name, declaration in (
        ("reach", "INTEGER"),
        ("account_name", "TEXT"),
        ("caption", "TEXT"),
        ("media_urls", "TEXT"),
        ("platform_label", "TEXT"),
        ("source_origin", "TEXT"),
    ):
        if not _has_column(conn, "posts", name):
            conn.execute(f"ALTER TABLE posts ADD COLUMN {name} {declaration}")
    if _table_exists(conn, "post_editorial"):
        for name, declaration in (
            ("content_soort_raw", "TEXT"),
            ("format_code_raw", "TEXT"),
        ):
            if not _has_column(conn, "post_editorial", name):
                conn.execute(f"ALTER TABLE post_editorial ADD COLUMN {name} {declaration}")
    if _table_exists(conn, "post_import_links"):
        if not _has_column(conn, "post_import_links", "excel_published_at"):
            conn.execute("ALTER TABLE post_import_links ADD COLUMN excel_published_at TEXT")
    if _table_exists(conn, "post_assessments"):
        for name, declaration in (
            ("score_value", "REAL"),
            ("rating_origin", "TEXT"),
            ("score_origin", "TEXT"),
            ("rating_missing_reason", "TEXT"),
            ("score_missing_reason", "TEXT"),
        ):
            if not _has_column(conn, "post_assessments", name):
                conn.execute(f"ALTER TABLE post_assessments ADD COLUMN {name} {declaration}")
    if _table_exists(conn, "content_formats"):
        for name, declaration in (
            ("example_url", "TEXT"),
            ("status", "TEXT"),
            ("usage_count", "INTEGER"),
        ):
            if not _has_column(conn, "content_formats", name):
                conn.execute(f"ALTER TABLE content_formats ADD COLUMN {name} {declaration}")
    if not _table_exists(conn, "clients"):
        return
    for name, declaration in (
        ("last_fetch_status", "TEXT"),
        ("last_fetch_detail", "TEXT"),
        ("last_fetch_at", "TEXT"),
        ("last_fetch_from", "TEXT"),
        ("last_fetch_until", "TEXT"),
        ("last_fetch_instagram", "INTEGER"),
        ("last_fetch_facebook", "INTEGER"),
    ):
        if not _has_column(conn, "clients", name):
            conn.execute(f"ALTER TABLE clients ADD COLUMN {name} {declaration}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in _columns(conn, table)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
