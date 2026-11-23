"""HAMSTER-only seed restore for Render Free when the SQLite file is empty.

Uses the tracked package at ``maaike/seed/hamster_redrock.json.gz`` (no Meta
tokens). Separate from optional remote persist (``MAAIKE_PERSIST_*``).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from maaike.config import project_root

SEED_REL = Path("maaike") / "seed" / "hamster_redrock.json.gz"


def seed_path() -> Path:
    return project_root() / SEED_REL


def load_seed_package() -> dict[str, Any] | None:
    path = seed_path()
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if path.suffix == ".gz" or path.name.endswith(".json.gz"):
        raw = gzip.decompress(raw)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        return None
    return data


def restore_hamster_seed_if_empty(conn) -> dict[str, Any]:
    """If there are no posts yet, import the tracked HAMSTER Red Rock seed.

    Never runs after a successful remote persist restore that already left posts
    (or any non-empty post table). Remote persist is applied first on boot.
    """
    thumbs_info: dict[str, Any] = {}
    try:
        from maaike.thumbnails import ensure_seed_thumbs_extracted

        thumbs_info = ensure_seed_thumbs_extracted()
    except Exception as exc:
        thumbs_info = {"extracted": False, "reason": f"thumbs_error:{exc.__class__.__name__}"}

    post_count = int(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
    if post_count > 0:
        return {
            "restored": False,
            "reason": "local_has_posts",
            "posts": post_count,
            "thumbs": thumbs_info,
            "note": "Seed skipped so existing/restored posts and edits stay intact.",
        }

    package = load_seed_package()
    if package is None:
        return {
            "restored": False,
            "reason": "seed_missing",
            "path": str(SEED_REL).replace("\\", "/"),
            "thumbs": thumbs_info,
        }

    from maaike.data_transfer import apply_import, validate_package

    validate_package(package)
    result = apply_import(conn, package, overwrite=True)
    return {
        "restored": True,
        "reason": "hamster_seed_applied",
        "path": str(SEED_REL).replace("\\", "/"),
        "stats": result.get("stats") if isinstance(result, dict) else result,
        "posts_before": post_count,
        "thumbs": thumbs_info,
    }
