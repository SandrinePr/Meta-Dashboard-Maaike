"""Remote JSON backup for Render Free (no persistent disk).

Reuses ``maaike.data_transfer`` export/import. Uploads are skipped when the
SHA-256 of the package bytes is unchanged. Secrets (Meta tokens, API keys)
are never included in the package.

Required env (all server-side):
  MAAIKE_PERSIST_ENABLED=1
  MAAIKE_PERSIST_BACKUP_URL   HTTPS URL that accepts GET (download) and PUT (upload)
  MAAIKE_PERSIST_TOKEN       optional Bearer token for Authorization
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from maaike.config import database_path, project_root
from maaike.data_transfer import apply_import, export_package_json_bytes, validate_package


def _state_path() -> Path:
    """Keep digest next to the SQLite file so Free /tmp and local data/ both work."""
    db = database_path()
    root = db.parent
    root.mkdir(parents=True, exist_ok=True)
    return root / ".maaike_persist_state.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def persist_config() -> dict[str, Any]:
    load_dotenv(override=False)
    enabled = os.getenv("MAAIKE_PERSIST_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    url = os.getenv("MAAIKE_PERSIST_BACKUP_URL", "").strip()
    token = os.getenv("MAAIKE_PERSIST_TOKEN", "").strip()
    return {
        "enabled": enabled and bool(url),
        "has_url": bool(url),
        "has_token": bool(token),
        "url_host": url.split("/")[2] if url.startswith("http") and "/" in url[8:] else "",
        "missing": (
            []
            if (enabled and url)
            else (
                (["MAAIKE_PERSIST_ENABLED=1"] if not enabled else [])
                + (["MAAIKE_PERSIST_BACKUP_URL"] if not url else [])
            )
        ),
        "note": (
            "Render Free has no disk. Set MAAIKE_PERSIST_ENABLED=1 and "
            "MAAIKE_PERSIST_BACKUP_URL to a HTTPS endpoint that supports GET+PUT. "
            "Optional MAAIKE_PERSIST_TOKEN as Bearer. Packages exclude secrets."
        ),
    }


def _headers() -> dict[str, str]:
    cfg = persist_config()
    load_dotenv(override=False)
    token = os.getenv("MAAIKE_PERSIST_TOKEN", "").strip()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def content_fingerprint(payload: bytes) -> str:
    """Hash package bytes with volatile timestamps removed so re-exports can skip."""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return hashlib.sha256(payload).hexdigest()
    if isinstance(data, dict):
        data = dict(data)
        data.pop("exported_at", None)
        # Activity "occurred_at" stays — real content. Only export stamp is volatile.
        stable = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(stable).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def push_if_changed(conn) -> dict[str, Any]:
    """Export and PUT only when content hash differs from last successful push."""
    cfg = persist_config()
    if not cfg["enabled"]:
        return {"pushed": False, "reason": "disabled", "config": {k: cfg[k] for k in ("enabled", "missing", "note")}}
    load_dotenv(override=False)
    url = os.getenv("MAAIKE_PERSIST_BACKUP_URL", "").strip()
    payload = export_package_json_bytes(conn)
    digest = content_fingerprint(payload)
    state = _load_state()
    if state.get("last_pushed_sha256") == digest:
        return {
            "pushed": False,
            "reason": "unchanged",
            "sha256": digest,
            "bytes": len(payload),
        }
    try:
        response = requests.put(url, data=payload, headers=_headers(), timeout=120)
    except requests.RequestException as exc:
        return {
            "pushed": False,
            "reason": "network_error",
            "error": exc.__class__.__name__,
            "sha256": digest,
        }
    if response.status_code not in {200, 201, 204}:
        return {
            "pushed": False,
            "reason": "http_error",
            "http_status": response.status_code,
            "sha256": digest,
        }
    state["last_pushed_sha256"] = digest
    state["last_pushed_at"] = __import__("datetime").datetime.now(
        tz=__import__("datetime").timezone.utc
    ).isoformat()
    state["last_pushed_bytes"] = len(payload)
    _save_state(state)
    return {
        "pushed": True,
        "reason": "uploaded",
        "sha256": digest,
        "bytes": len(payload),
        "http_status": response.status_code,
    }


def restore_from_remote_if_needed(conn) -> dict[str, Any]:
    """On empty local DB, download remote package and apply (overwrite)."""
    cfg = persist_config()
    if not cfg["enabled"]:
        return {"restored": False, "reason": "disabled"}
    client_count = int(conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0])
    force = os.getenv("MAAIKE_PERSIST_RESTORE_ALWAYS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if client_count > 0 and not force:
        return {"restored": False, "reason": "local_has_clients", "clients": client_count}

    load_dotenv(override=False)
    url = os.getenv("MAAIKE_PERSIST_BACKUP_URL", "").strip()
    try:
        response = requests.get(url, headers=_headers(), timeout=120)
    except requests.RequestException as exc:
        return {"restored": False, "reason": "network_error", "error": exc.__class__.__name__}
    if response.status_code == 404:
        return {"restored": False, "reason": "remote_empty"}
    if response.status_code != 200:
        return {
            "restored": False,
            "reason": "http_error",
            "http_status": response.status_code,
        }
    try:
        data = response.json()
    except ValueError:
        return {"restored": False, "reason": "invalid_json"}
    try:
        validate_package(data)
    except ValueError as exc:
        return {"restored": False, "reason": "invalid_package", "error": str(exc)}

    result = apply_import(conn, data, overwrite=True)
    digest = content_fingerprint(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    state = _load_state()
    state["last_restored_sha256"] = digest
    state["last_restored_at"] = __import__("datetime").datetime.now(
        tz=__import__("datetime").timezone.utc
    ).isoformat()
    # Align push fingerprint so the next push is skipped until real changes.
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    state["last_pushed_sha256"] = content_fingerprint(raw)
    _save_state(state)
    return {
        "restored": True,
        "reason": "applied",
        "stats": result.get("stats") if isinstance(result, dict) else result,
        "clients_before": client_count,
    }


def public_persist_status() -> dict[str, Any]:
    cfg = persist_config()
    state = _load_state()
    db = database_path()
    return {
        **cfg,
        "database_path_name": db.name,
        "database_exists": db.is_file(),
        "last_pushed_sha256": state.get("last_pushed_sha256"),
        "last_pushed_at": state.get("last_pushed_at"),
        "last_restored_at": state.get("last_restored_at"),
        "free_tier_note": (
            "Without a Render disk, SQLite is ephemeral. Enable remote persist so "
            "prompts, posts, Figma links and reports survive restarts."
        ),
    }
