"""Private per-client strategy PDF storage.

Stored inside SQLite (``client_strategy_files``) so ``maaike.data_transfer`` and
``maaike.persist_remote`` carry the PDF bytes in the private ``hamster-persist``
backup package across restarts and Render Free deploys without introducing public
URLs or extra hosting infrastructure.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_STRATEGY_PDF_BYTES = 15 * 1024 * 1024  # 15 MiB cap (fits GitHub Contents download_url + persist)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_pdf_filename(name: str) -> str:
    base = Path(name or "strategie.pdf").name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" ._") or "strategie.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:120]


def ensure_strategy_file_table(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS client_strategy_files (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            file_ref TEXT NOT NULL,
            filename TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT 'application/pdf',
            byte_size INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'staged',
            content BLOB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(client_id, file_ref),
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );
        CREATE INDEX IF NOT EXISTS idx_client_strategy_files_client
            ON client_strategy_files(client_id, status, updated_at);
        """
    )


def save_strategy_pdf(
    conn,
    client_id: int,
    file_bytes: bytes,
    *,
    filename: str = "",
    status: str = "staged",
) -> dict[str, Any]:
    """Store a strategy PDF privately for ``client_id`` and prune old transient copies."""
    if not file_bytes:
        raise ValueError("Leeg PDF-bestand.")
    if len(file_bytes) > MAX_STRATEGY_PDF_BYTES:
        raise ValueError("PDF is groter dan 15 MB. Exporteer een kleinere PDF.")
    if not bytes(file_bytes[:1024]).lstrip().startswith(b"%PDF"):
        raise ValueError("Dit bestand is geen geldige PDF.")

    ensure_strategy_file_table(conn)
    clean_name = _safe_pdf_filename(filename)
    digest = hashlib.sha256(file_bytes).hexdigest()
    now = _now()

    # Reuse identical file already stored for this client when present.
    existing = conn.execute(
        """
        SELECT file_ref, filename, mime_type, byte_size, sha256, status, created_at
        FROM client_strategy_files
        WHERE client_id = ? AND sha256 = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (client_id, digest),
    ).fetchone()
    if existing is not None:
        file_ref = str(existing["file_ref"])
        next_status = "active" if (status == "active" or existing["status"] == "active") else status
        conn.execute(
            """
            UPDATE client_strategy_files
            SET filename = ?, status = ?, updated_at = ?
            WHERE client_id = ? AND file_ref = ?
            """,
            (clean_name, next_status, now, client_id, file_ref),
        )
    else:
        file_ref = f"spdf_{secrets.token_hex(12)}"
        next_status = "active" if status == "active" else "staged"
        conn.execute(
            """
            INSERT INTO client_strategy_files (
                client_id, file_ref, filename, mime_type, byte_size,
                sha256, status, content, created_at, updated_at
            ) VALUES (?, ?, ?, 'application/pdf', ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                file_ref,
                clean_name,
                len(file_bytes),
                digest,
                next_status,
                bytes(file_bytes),
                now,
                now,
            ),
        )

    if next_status == "active":
        activate_strategy_pdf(conn, client_id, file_ref, filename=clean_name)
    else:
        # Keep only the newest staged upload alongside any active file so canceled previews don't pile up.
        conn.execute(
            """
            DELETE FROM client_strategy_files
            WHERE client_id = ? AND status = 'staged' AND file_ref != ?
            """,
            (client_id, file_ref),
        )

    return {
        "file_ref": file_ref,
        "filename": clean_name,
        "mime_type": "application/pdf",
        "byte_size": len(file_bytes),
        "sha256": digest,
        "status": next_status,
        "available": True,
    }


def activate_strategy_pdf(
    conn,
    client_id: int,
    file_ref: str,
    *,
    filename: str = "",
) -> dict[str, Any] | None:
    """Mark ``file_ref`` as the active PDF for ``client_id`` and drop older files for this client."""
    ref = str(file_ref or "").strip()
    if not ref:
        return None
    ensure_strategy_file_table(conn)
    row = conn.execute(
        """
        SELECT file_ref, filename, mime_type, byte_size, sha256, updated_at
        FROM client_strategy_files
        WHERE client_id = ? AND file_ref = ?
        """,
        (client_id, ref),
    ).fetchone()
    if row is None:
        return None
    clean_name = _safe_pdf_filename(filename or str(row["filename"] or "strategie.pdf"))
    now = _now()
    conn.execute(
        """
        UPDATE client_strategy_files
        SET status = 'active', filename = ?, updated_at = ?
        WHERE client_id = ? AND file_ref = ?
        """,
        (clean_name, now, client_id, ref),
    )
    conn.execute(
        """
        DELETE FROM client_strategy_files
        WHERE client_id = ? AND file_ref != ?
        """,
        (client_id, ref),
    )
    return {
        "file_ref": ref,
        "filename": clean_name,
        "mime_type": str(row["mime_type"] or "application/pdf"),
        "byte_size": int(row["byte_size"] or 0),
        "sha256": str(row["sha256"] or ""),
        "updated_at": now,
        "available": True,
    }


def get_strategy_pdf(
    conn,
    client_id: int,
    *,
    file_ref: str = "",
) -> dict[str, Any] | None:
    """Fetch stored PDF bytes strictly scoped to ``client_id``."""
    ensure_strategy_file_table(conn)
    ref = str(file_ref or "").strip()
    if ref:
        row = conn.execute(
            """
            SELECT file_ref, filename, mime_type, byte_size, sha256, status, content, updated_at
            FROM client_strategy_files
            WHERE client_id = ? AND file_ref = ?
            """,
            (client_id, ref),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT file_ref, filename, mime_type, byte_size, sha256, status, content, updated_at
            FROM client_strategy_files
            WHERE client_id = ? AND status = 'active'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (client_id,),
        ).fetchone()
    if row is None or not row["content"]:
        return None
    return {
        "file_ref": str(row["file_ref"]),
        "filename": _safe_pdf_filename(str(row["filename"] or "strategie.pdf")),
        "mime_type": str(row["mime_type"] or "application/pdf"),
        "byte_size": int(row["byte_size"] or len(row["content"])),
        "sha256": str(row["sha256"] or ""),
        "status": str(row["status"] or "active"),
        "updated_at": row["updated_at"],
        "content": bytes(row["content"]),
    }


def resolve_strategy_pdf_status(
    conn,
    client_id: int,
    fields: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build UI-ready PDF availability metadata (stored file vs legacy filename-only vs none)."""
    ensure_strategy_file_table(conn)
    meta = dict((fields or {}).get("last_pdf_meta") or {})
    ref = str(meta.get("file_ref") or (fields or {}).get("strategy_pdf_ref") or "").strip()

    row = None
    if ref:
        row = conn.execute(
            """
            SELECT file_ref, filename, mime_type, byte_size, sha256, updated_at
            FROM client_strategy_files
            WHERE client_id = ? AND file_ref = ?
            """,
            (client_id, ref),
        ).fetchone()
    if row is None:
        row = conn.execute(
            """
            SELECT file_ref, filename, mime_type, byte_size, sha256, updated_at
            FROM client_strategy_files
            WHERE client_id = ? AND status = 'active'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (client_id,),
        ).fetchone()

    if row is not None:
        filename = _safe_pdf_filename(str(meta.get("filename") or row["filename"] or "strategie.pdf"))
        resolved_ref = str(row["file_ref"])
        return {
            "available": True,
            "needs_reupload": False,
            "file_ref": resolved_ref,
            "filename": filename,
            "byte_size": int(row["byte_size"] or 0),
            "updated_at": row["updated_at"],
            "view_url": f"/api/clients/{client_id}/strategy/pdf?disposition=inline&ref={resolved_ref}",
            "download_url": f"/api/clients/{client_id}/strategy/pdf?disposition=attachment&ref={resolved_ref}",
        }

    legacy_name = str(meta.get("filename") or "").strip()
    if legacy_name:
        return {
            "available": False,
            "needs_reupload": True,
            "file_ref": "",
            "filename": legacy_name,
            "byte_size": 0,
            "updated_at": None,
            "view_url": "",
            "download_url": "",
        }

    return {
        "available": False,
        "needs_reupload": False,
        "file_ref": "",
        "filename": "",
        "byte_size": 0,
        "updated_at": None,
        "view_url": "",
        "download_url": "",
    }
