"""SQLite access for Maaike's Red Rock database only."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from maaike.config import assert_separate_from_taol, database_path


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open Maaike's database. Raises before touching a TAOL database file."""
    path = assert_separate_from_taol(db_path or database_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def transaction(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Commit on success. Close always. Do not call st.rerun() inside this block."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(db_path: Path | None = None) -> Path:
    """Create Maaike's tables when missing. Does not seed TAOL posts."""
    path = assert_separate_from_taol(db_path or database_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with transaction(path) as conn:
        from maaike.migrate import apply_migrations

        apply_migrations(conn)
    return path
