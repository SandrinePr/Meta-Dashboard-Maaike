"""Store ordered media parts and one content description per post."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from meta.content_media import MediaPart


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class StoredDescription:
    post_id: int
    fingerprint: str
    coverage: str
    coverage_note: str | None
    description: dict[str, Any] | None
    files_processed: list[str]
    model: str | None
    prompt_version: str | None
    analyzed_at: str | None


def replace_media_parts(conn: sqlite3.Connection, post_id: int, parts: list[MediaPart]) -> None:
    """Replace the stored parts for one post. Positions stay in the given order."""
    conn.execute("DELETE FROM post_media_items WHERE post_id = ?", (post_id,))
    fetched_at = _now()
    for part in parts:
        conn.execute(
            """
            INSERT INTO post_media_items (
                post_id, position, role, external_id, media_type, source_url,
                local_path, available, unavailable_reason, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                post_id,
                part.position,
                part.role,
                part.external_id,
                part.media_type,
                part.source_url,
                1 if part.available else 0,
                part.unavailable_reason,
                fetched_at,
            ),
        )


def list_media_parts(conn: sqlite3.Connection, post_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, post_id, position, role, external_id, media_type, source_url,
                   local_path, available, unavailable_reason, fetched_at
            FROM post_media_items
            WHERE post_id = ?
            ORDER BY position ASC, CASE role
                WHEN 'carousel_slide' THEN 0
                WHEN 'image' THEN 1
                WHEN 'video' THEN 2
                WHEN 'thumbnail' THEN 3
                ELSE 4
            END, id ASC
            """,
            (post_id,),
        ).fetchall()
    )


def mark_local_file(conn: sqlite3.Connection, item_id: int, local_path: str | None) -> None:
    conn.execute(
        "UPDATE post_media_items SET local_path = ? WHERE id = ?",
        (local_path, item_id),
    )


def get_description(conn: sqlite3.Connection, post_id: int) -> StoredDescription | None:
    row = conn.execute(
        """
        SELECT post_id, fingerprint, coverage, coverage_note, description_json,
               files_processed_json, model, prompt_version, analyzed_at
        FROM content_descriptions
        WHERE post_id = ?
        """,
        (post_id,),
    ).fetchone()
    if row is None:
        return None
    description = None
    if row["description_json"]:
        try:
            parsed = json.loads(row["description_json"])
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            description = parsed
    files: list[str] = []
    if row["files_processed_json"]:
        try:
            parsed_files = json.loads(row["files_processed_json"])
        except json.JSONDecodeError:
            parsed_files = []
        if isinstance(parsed_files, list):
            files = [str(item) for item in parsed_files]
    return StoredDescription(
        post_id=int(row["post_id"]),
        fingerprint=str(row["fingerprint"]),
        coverage=str(row["coverage"]),
        coverage_note=row["coverage_note"],
        description=description,
        files_processed=files,
        model=row["model"],
        prompt_version=row["prompt_version"],
        analyzed_at=row["analyzed_at"],
    )


def save_description(
    conn: sqlite3.Connection,
    *,
    post_id: int,
    fingerprint: str,
    coverage: str,
    coverage_note: str | None,
    description: dict[str, Any] | None,
    files_processed: list[str],
    model: str | None,
    prompt_version: str | None,
    analyzed_at: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO content_descriptions (
            post_id, fingerprint, coverage, coverage_note, description_json,
            files_processed_json, model, prompt_version, analyzed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            fingerprint = excluded.fingerprint,
            coverage = excluded.coverage,
            coverage_note = excluded.coverage_note,
            description_json = excluded.description_json,
            files_processed_json = excluded.files_processed_json,
            model = excluded.model,
            prompt_version = excluded.prompt_version,
            analyzed_at = excluded.analyzed_at
        """,
        (
            post_id,
            fingerprint,
            coverage,
            coverage_note,
            json.dumps(description, ensure_ascii=False) if description is not None else None,
            json.dumps(files_processed, ensure_ascii=False),
            model,
            prompt_version,
            analyzed_at,
        ),
    )


def descriptions_for_posts(conn: sqlite3.Connection, post_ids: list[int]) -> dict[int, StoredDescription]:
    if not post_ids:
        return {}
    placeholders = ",".join("?" for _ in post_ids)
    rows = conn.execute(
        f"""
        SELECT post_id FROM content_descriptions
        WHERE post_id IN ({placeholders})
        """,
        post_ids,
    ).fetchall()
    found = {}
    for row in rows:
        item = get_description(conn, int(row["post_id"]))
        if item is not None:
            found[item.post_id] = item
    return found
