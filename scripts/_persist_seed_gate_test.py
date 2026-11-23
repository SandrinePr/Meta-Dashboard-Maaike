"""Ensure failed remote restore does not fall back to Red Rock seed."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from maaike.db import initialize_database, transaction
    from maaike.hamster_seed import restore_hamster_seed_if_empty
    from maaike.persist_remote import restore_from_remote_if_needed, should_run_hamster_seed

    os.environ["MAAIKE_PERSIST_ENABLED"] = "1"
    os.environ["MAAIKE_PERSIST_BACKUP_URL"] = "http://127.0.0.1:9/missing-backup.json"
    os.environ["MAAIKE_PERSIST_PROVIDER"] = "http"
    os.environ.pop("MAAIKE_PERSIST_RESTORE_ALWAYS", None)

    db = Path(tempfile.mkdtemp(prefix="hamster-seed-gate-")) / "empty.db"
    os.environ["MAAIKE_DATABASE_PATH"] = str(db)
    initialize_database(db)

    with transaction(db) as conn:
        restore = restore_from_remote_if_needed(conn)
        allowed = should_run_hamster_seed(restore)
        seed = {"reason": "not_run"}
        if allowed:
            seed = restore_hamster_seed_if_empty(conn)
        posts = int(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
        clients = [r[0] for r in conn.execute("SELECT name FROM clients ORDER BY id").fetchall()]

    print(
        {
            "restore_reason": restore.get("reason"),
            "seed_should_skip": restore.get("seed_should_skip"),
            "seed_allowed": allowed,
            "seed_reason": seed.get("reason"),
            "posts": posts,
            "clients": clients,
        }
    )
    # Failed download must block seed (no silent Red Rock fallback).
    if allowed or posts > 0:
        print("SEED_GATE_FAIL")
        return 1
    print("SEED_GATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
