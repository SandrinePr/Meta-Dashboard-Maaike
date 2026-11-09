"""Prepare the stored photo and two-slide carousel. No Meta and no AI call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.content_describe import _download_image
from db.content_repository import get_description, list_media_parts, mark_local_file
from db.database import get_connection

OWN_USERNAME = "theartofliving.online"


def _candidate(conn, media_type: str, role: str, expected_parts: int) -> int | None:
    rows = conn.execute(
        """
        SELECT posts.id AS post_id
        FROM posts
        JOIN accounts ON accounts.id = posts.account_id
        WHERE accounts.username = ?
          AND posts.media_type = ?
          AND (
              SELECT COUNT(*)
              FROM post_media_items
              WHERE post_media_items.post_id = posts.id
                AND post_media_items.role = ?
                AND post_media_items.available = 1
          ) = ?
        ORDER BY posts.published_at DESC, posts.id DESC
        LIMIT 1
        """,
        (OWN_USERNAME, media_type, role, expected_parts),
    ).fetchone()
    if rows is None:
        return None
    return int(rows["post_id"])


def image_test_post_ids(conn) -> list[int]:
    """The stored single photo, then the carousel that has two available slides."""
    image_id = _candidate(conn, "IMAGE", "image", 1)
    carousel_id = _candidate(conn, "CAROUSEL_ALBUM", "carousel_slide", 2)
    return [post_id for post_id in (image_id, carousel_id) if post_id is not None]


def load_image_test_posts(conn) -> list[dict[str, Any]]:
    posts = []
    for post_id in image_test_post_ids(conn):
        row = conn.execute(
            """
            SELECT id, text, media_type, published_at
            FROM posts
            WHERE id = ?
            """,
            (post_id,),
        ).fetchone()
        if row is None:
            continue
        parts = []
        for part in list_media_parts(conn, post_id):
            if part["role"] not in {"image", "carousel_slide"}:
                continue
            local = part["local_path"]
            ready = bool(local and Path(local).is_file())
            parts.append(
                {
                    "id": int(part["id"]),
                    "position": int(part["position"]),
                    "role": part["role"],
                    "available": bool(part["available"]),
                    "local_path": local if ready else None,
                    "ready": ready,
                    "reason": part["unavailable_reason"],
                }
            )
        description = get_description(conn, post_id)
        posts.append(
            {
                "post_id": post_id,
                "media_type": row["media_type"],
                "published_at": row["published_at"],
                "caption": row["text"] if isinstance(row["text"], str) else "",
                "parts": parts,
                "description": None if description is None else description.description,
                "coverage": None if description is None else description.coverage,
                "coverage_note": None if description is None else description.coverage_note,
                "model": None if description is None else description.model,
                "prompt_version": None if description is None else description.prompt_version,
                "analyzed_at": None if description is None else description.analyzed_at,
                "files_processed": [] if description is None else description.files_processed,
            }
        )
    return posts


def cache_image_test_files() -> list[dict[str, Any]]:
    """Save already stored image URLs to local files. Does not call Meta or AI."""
    report: list[dict[str, Any]] = []
    with get_connection() as conn:
        for post_id in image_test_post_ids(conn):
            for part in list_media_parts(conn, post_id):
                if part["role"] not in {"image", "carousel_slide"} or not part["available"]:
                    continue
                entry = {
                    "post_id": post_id,
                    "position": int(part["position"]),
                    "role": part["role"],
                    "ready": False,
                    "bytes": 0,
                    "error": None,
                }
                local = part["local_path"]
                if local and Path(local).is_file():
                    entry["ready"] = True
                    entry["bytes"] = Path(local).stat().st_size
                    report.append(entry)
                    continue
                source = part["source_url"] if isinstance(part["source_url"], str) else ""
                stem = Path("data") / "media" / "content" / f"post_{post_id}_{part['role']}_{part['position']}"
                target, error = _download_image(source, stem)
                if target is None:
                    entry["error"] = error
                    report.append(entry)
                    continue
                mark_local_file(conn, int(part["id"]), str(target))
                entry["ready"] = True
                entry["bytes"] = target.stat().st_size
                report.append(entry)
        conn.commit()
    return report
