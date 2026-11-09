"""Client-owned media uploads for posts — works without Meta."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any

from maaike.ai_trial import _now

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_ROOT = PROJECT_ROOT / "data" / "uploads"
MAX_BYTES = 80_000_000  # 80 MB hard cap per file
ALLOWED_IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_VIDEO = {".mp4", ".mov", ".m4v", ".webm"}


def ensure_upload_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS post_media_assets (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            kind TEXT NOT NULL,
            original_name TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT '',
            byte_size INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'upload',
            created_at TEXT NOT NULL,
            UNIQUE(client_id, post_id, position),
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_post_media_assets_post
            ON post_media_assets(client_id, post_id, position);
        """
    )


def _safe_name(name: str) -> str:
    base = Path(name or "file").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "file"
    return cleaned[:120]


def _kind_for(suffix: str, mime: str) -> str | None:
    s = suffix.lower()
    m = (mime or "").lower()
    if s in ALLOWED_IMAGE or m.startswith("image/"):
        return "image"
    if s in ALLOWED_VIDEO or m.startswith("video/"):
        return "video"
    return None


def list_post_media(conn, client_id: int, post_id: int) -> list[dict[str, Any]]:
    ensure_upload_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM post_media_assets
        WHERE client_id = ? AND post_id = ?
        ORDER BY position, id
        """,
        (client_id, post_id),
    ).fetchall()
    out = []
    for row in rows:
        path = PROJECT_ROOT / row["stored_path"]
        out.append(
            {
                "id": row["id"],
                "position": row["position"],
                "kind": row["kind"],
                "original_name": row["original_name"],
                "stored_path": row["stored_path"],
                "mime_type": row["mime_type"],
                "byte_size": row["byte_size"],
                "source": row["source"],
                "created_at": row["created_at"],
                "exists": path.is_file(),
            }
        )
    return out


def reorder_post_media(conn, client_id: int, post_id: int, ordered_ids: list[int]) -> list[dict[str, Any]]:
    ensure_upload_tables(conn)
    owned = conn.execute(
        "SELECT id FROM posts WHERE id = ? AND client_id = ?",
        (post_id, client_id),
    ).fetchone()
    if owned is None:
        raise ValueError("Post hoort niet bij deze klant.")
    current = {
        int(r["id"]): r
        for r in conn.execute(
            "SELECT * FROM post_media_assets WHERE client_id = ? AND post_id = ?",
            (client_id, post_id),
        ).fetchall()
    }
    if set(ordered_ids) != set(current.keys()):
        raise ValueError("Volgorde moet precies alle mediabestanden van deze post bevatten.")
    # Two-phase update to avoid UNIQUE(position) collisions.
    for idx, asset_id in enumerate(ordered_ids, start=1):
        conn.execute(
            "UPDATE post_media_assets SET position = ? WHERE id = ?",
            (-idx, asset_id),
        )
    for idx, asset_id in enumerate(ordered_ids, start=1):
        conn.execute(
            "UPDATE post_media_assets SET position = ? WHERE id = ?",
            (idx, asset_id),
        )
    return list_post_media(conn, client_id, post_id)


def save_uploaded_files(
    conn,
    client_id: int,
    post_id: int,
    files: list[dict[str, Any]],
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """
    Store uploaded files for a post.

    files: list of {filename, content: bytes, content_type?}
    """
    ensure_upload_tables(conn)
    owned = conn.execute(
        "SELECT id, media_urls FROM posts WHERE id = ? AND client_id = ?",
        (post_id, client_id),
    ).fetchone()
    if owned is None:
        raise ValueError("Post hoort niet bij deze klant.")
    if not files:
        raise ValueError("No files received.")

    if replace:
        old = list_post_media(conn, client_id, post_id)
        conn.execute(
            "DELETE FROM post_media_assets WHERE client_id = ? AND post_id = ?",
            (client_id, post_id),
        )
        for item in old:
            path = PROJECT_ROOT / item["stored_path"]
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
        start_pos = 1
    else:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), 0) AS m FROM post_media_assets WHERE client_id = ? AND post_id = ?",
            (client_id, post_id),
        ).fetchone()
        start_pos = int(row["m"]) + 1

    dest_dir = UPLOAD_ROOT / f"client_{client_id}" / f"post_{post_id}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    errors: list[str] = []
    now = _now()
    position = start_pos

    for item in files:
        name = _safe_name(str(item.get("filename") or "file"))
        data = item.get("content")
        if not isinstance(data, (bytes, bytearray)) or not data:
            errors.append(f"{name}: empty file.")
            continue
        if len(data) > MAX_BYTES:
            errors.append(f"{name}: groter dan {MAX_BYTES // 1_000_000} MB.")
            continue
        suffix = Path(name).suffix.lower()
        mime = str(item.get("content_type") or mimetypes.guess_type(name)[0] or "")
        kind = _kind_for(suffix, mime)
        if kind is None:
            errors.append(f"{name}: type niet toegestaan (afbeelding of video).")
            continue
        if not suffix:
            suffix = ".jpg" if kind == "image" else ".mp4"
            name = name + suffix
        target = dest_dir / f"{position:02d}_{name}"
        target.write_bytes(bytes(data))
        rel = target.relative_to(PROJECT_ROOT).as_posix()
        conn.execute(
            """
            INSERT INTO post_media_assets (
                client_id, post_id, position, kind, original_name,
                stored_path, mime_type, byte_size, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'upload', ?)
            """,
            (
                client_id,
                post_id,
                position,
                kind,
                name,
                rel,
                mime or ("image/jpeg" if kind == "image" else "video/mp4"),
                len(data),
                now,
            ),
        )
        saved.append(
            {
                "position": position,
                "kind": kind,
                "original_name": name,
                "stored_path": rel,
                "byte_size": len(data),
                "source": "upload",
            }
        )
        position += 1

    assets = list_post_media(conn, client_id, post_id)
    return {
        "post_id": post_id,
        "saved": saved,
        "errors": errors,
        "assets": assets,
        "meta_urls_present": bool(str(owned["media_urls"] or "").strip()),
        "note": (
            "Uploads horen bij deze klant/post en werken zonder Meta. "
            "Bestaande Meta-media-URL’s blijven staan; uploads hebben voorrang in de AI-proef wanneer aanwezig."
        ),
    }


def local_paths_for_analysis(conn, client_id: int, post_id: int) -> list[dict[str, Any]]:
    """Ordered local media for AI prep (uploads first source of truth when present)."""
    assets = list_post_media(conn, client_id, post_id)
    out = []
    for item in assets:
        path = PROJECT_ROOT / item["stored_path"]
        if not path.is_file():
            continue
        out.append(
            {
                "index": item["position"],
                "kind": item["kind"],
                "path": item["stored_path"],
                "bytes": item["byte_size"],
                "source": item["source"],
                "mime_type": item["mime_type"],
                "ok": True,
            }
        )
    return out
