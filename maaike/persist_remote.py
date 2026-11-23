"""Remote JSON backup for Render Free (no persistent disk).

Reuses ``maaike.data_transfer`` export/import. Uploads are skipped when the
SHA-256 of the package bytes is unchanged. Secrets (Meta tokens, API keys)
are never included in the package.

Required env (all server-side):
  MAAIKE_PERSIST_ENABLED=1
  MAAIKE_PERSIST_BACKUP_URL
    - Plain HTTPS URL that accepts GET + PUT of the JSON body, OR
    - GitHub Contents URL for a private HAMSTER-only repo, e.g.
      https://api.github.com/repos/OWNER/hamster-persist/contents/hamster-maaike-backup.json
  MAAIKE_PERSIST_TOKEN
    - Optional Bearer for plain HTTPS
    - Required for GitHub Contents (classic/fine-grained PAT with Contents write)

Optional:
  MAAIKE_PERSIST_BACKUP_GET_URL  separate GET URL when it differs from PUT
  MAAIKE_PERSIST_PROVIDER        auto | github | http
  MAAIKE_PERSIST_RESTORE_ALWAYS  force restore even when local clients exist
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from maaike.config import database_path, project_root


def _data_transfer():
    """Lazy import so status works even if optional Excel deps are missing."""
    from maaike import data_transfer as mod

    return mod


def _state_path() -> Path:
    """Keep digest next to the SQLite file so Free /tmp and local data/ both work."""
    candidates = [database_path().parent, Path("/tmp"), project_root() / "data"]
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".maaike_persist_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return root / ".maaike_persist_state.json"
        except OSError:
            continue
    return Path("/tmp") / ".maaike_persist_state.json"


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


def _provider_for_url(url: str) -> str:
    explicit = (os.getenv("MAAIKE_PERSIST_PROVIDER") or "").strip().lower()
    if explicit in {"github", "http", "https"}:
        return "github" if explicit == "github" else "http"
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path or ""
    if host == "api.github.com" and "/repos/" in path and "/contents/" in path:
        return "github"
    return "http"


def persist_config() -> dict[str, Any]:
    load_dotenv(override=False)
    enabled = os.getenv("MAAIKE_PERSIST_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    url = os.getenv("MAAIKE_PERSIST_BACKUP_URL", "").strip()
    get_url = os.getenv("MAAIKE_PERSIST_BACKUP_GET_URL", "").strip()
    token = os.getenv("MAAIKE_PERSIST_TOKEN", "").strip()
    provider = _provider_for_url(url) if url else "http"
    missing: list[str] = []
    if not enabled:
        missing.append("MAAIKE_PERSIST_ENABLED=1")
    if not url:
        missing.append("MAAIKE_PERSIST_BACKUP_URL")
    if provider == "github" and not token:
        missing.append("MAAIKE_PERSIST_TOKEN (GitHub PAT with Contents: write on hamster-persist)")
    return {
        "enabled": enabled and bool(url) and not (provider == "github" and not token),
        "has_url": bool(url),
        "has_get_url": bool(get_url),
        "has_token": bool(token),
        "provider": provider,
        "url_host": url.split("/")[2] if url.startswith("http") and "/" in url[8:] else "",
        "missing": missing,
        "note": (
            "Render Free has no disk. Use a HAMSTER-only GitHub Contents URL "
            "(private repo SandrinePr/hamster-persist) or any HTTPS GET+PUT endpoint. "
            "Packages exclude Meta tokens and API keys."
        ),
    }


def _headers(*, for_github: bool = False) -> dict[str, str]:
    load_dotenv(override=False)
    token = os.getenv("MAAIKE_PERSIST_TOKEN", "").strip()
    if for_github:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers
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
        stable = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(stable).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def _put_http(url: str, payload: bytes) -> dict[str, Any]:
    try:
        response = requests.put(url, data=payload, headers=_headers(), timeout=120)
    except requests.RequestException as exc:
        return {"ok": False, "reason": "network_error", "error": exc.__class__.__name__}
    if response.status_code not in {200, 201, 204}:
        return {
            "ok": False,
            "reason": "http_error",
            "http_status": response.status_code,
            "body_preview": (response.text or "")[:240],
        }
    return {"ok": True, "http_status": response.status_code}


def _get_http(url: str) -> dict[str, Any]:
    get_url = os.getenv("MAAIKE_PERSIST_BACKUP_GET_URL", "").strip() or url
    try:
        response = requests.get(get_url, headers=_headers(), timeout=120)
    except requests.RequestException as exc:
        return {"ok": False, "reason": "network_error", "error": exc.__class__.__name__}
    if response.status_code == 404:
        return {"ok": False, "reason": "remote_empty", "http_status": 404}
    if response.status_code != 200:
        return {
            "ok": False,
            "reason": "http_error",
            "http_status": response.status_code,
            "body_preview": (response.text or "")[:240],
        }
    try:
        return {"ok": True, "data": response.json(), "http_status": 200}
    except ValueError:
        return {"ok": False, "reason": "invalid_json"}


def _github_contents_url(url: str) -> str:
    """Normalize to API contents URL without query (ref added per request)."""
    parsed = urlparse(url.strip())
    return f"https://api.github.com{parsed.path}"


def _put_github(url: str, payload: bytes) -> dict[str, Any]:
    api_url = _github_contents_url(url)
    headers = _headers(for_github=True)
    sha = None
    try:
        existing = requests.get(api_url, headers=headers, params={"ref": "main"}, timeout=60)
    except requests.RequestException as exc:
        return {"ok": False, "reason": "network_error", "error": exc.__class__.__name__}
    if existing.status_code == 200:
        try:
            sha = existing.json().get("sha")
        except ValueError:
            sha = None
    elif existing.status_code not in {404, 200}:
        return {
            "ok": False,
            "reason": "http_error",
            "http_status": existing.status_code,
            "body_preview": (existing.text or "")[:240],
            "phase": "get_sha",
        }
    body: dict[str, Any] = {
        "message": "HAMSTER persist: update maaike backup (no secrets)",
        "content": base64.b64encode(payload).decode("ascii"),
        "branch": "main",
    }
    if sha:
        body["sha"] = sha
    try:
        response = requests.put(api_url, headers=headers, json=body, timeout=120)
    except requests.RequestException as exc:
        return {"ok": False, "reason": "network_error", "error": exc.__class__.__name__}
    if response.status_code not in {200, 201}:
        return {
            "ok": False,
            "reason": "http_error",
            "http_status": response.status_code,
            "body_preview": (response.text or "")[:240],
            "phase": "put",
        }
    return {"ok": True, "http_status": response.status_code, "provider": "github"}


def _get_github(url: str) -> dict[str, Any]:
    api_url = _github_contents_url(url)
    headers = _headers(for_github=True)
    try:
        response = requests.get(api_url, headers=headers, params={"ref": "main"}, timeout=120)
    except requests.RequestException as exc:
        return {"ok": False, "reason": "network_error", "error": exc.__class__.__name__}
    if response.status_code == 404:
        return {"ok": False, "reason": "remote_empty", "http_status": 404}
    if response.status_code != 200:
        return {
            "ok": False,
            "reason": "http_error",
            "http_status": response.status_code,
            "body_preview": (response.text or "")[:240],
        }
    try:
        meta = response.json()
    except ValueError:
        return {"ok": False, "reason": "invalid_json"}
    raw: bytes | None = None
    encoded = meta.get("content")
    # GitHub omits inline base64 content for files > ~1 MiB; use download_url.
    if isinstance(encoded, str) and encoded.strip() and meta.get("encoding") == "base64":
        try:
            raw = base64.b64decode(encoded)
        except (ValueError, TypeError):
            raw = None
    if raw is None:
        download_url = meta.get("download_url")
        if isinstance(download_url, str) and download_url.strip():
            try:
                dl = requests.get(download_url, headers=_headers(for_github=True), timeout=180)
            except requests.RequestException as exc:
                return {"ok": False, "reason": "network_error", "error": exc.__class__.__name__}
            if dl.status_code != 200:
                return {
                    "ok": False,
                    "reason": "http_error",
                    "http_status": dl.status_code,
                    "body_preview": (dl.text or "")[:240],
                    "phase": "download_url",
                }
            raw = dl.content
    if raw is None or not raw.strip():
        return {"ok": False, "reason": "remote_empty"}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "reason": "invalid_json"}
    if not isinstance(data, dict):
        return {"ok": False, "reason": "invalid_json"}
    # Placeholder init file from repo bootstrap
    if "placeholder" in str(data.get("note") or "").lower() and not data.get("clients"):
        return {"ok": False, "reason": "remote_empty"}
    return {"ok": True, "data": data, "http_status": 200, "provider": "github", "sha": meta.get("sha")}


def push_if_changed(conn) -> dict[str, Any]:
    """Export and upload only when content hash differs from last successful push."""
    cfg = persist_config()
    if not cfg["enabled"]:
        return {"pushed": False, "reason": "disabled", "config": {k: cfg[k] for k in ("enabled", "missing", "note", "provider")}}
    load_dotenv(override=False)
    url = os.getenv("MAAIKE_PERSIST_BACKUP_URL", "").strip()
    payload = _data_transfer().export_package_json_bytes(conn)
    digest = content_fingerprint(payload)
    state = _load_state()
    if state.get("last_pushed_sha256") == digest:
        return {
            "pushed": False,
            "reason": "unchanged",
            "sha256": digest,
            "bytes": len(payload),
            "provider": cfg.get("provider"),
        }
    provider = cfg.get("provider") or _provider_for_url(url)
    if provider == "github":
        result = _put_github(url, payload)
    else:
        result = _put_http(url, payload)
    if not result.get("ok"):
        return {
            "pushed": False,
            "reason": result.get("reason") or "upload_failed",
            "http_status": result.get("http_status"),
            "error": result.get("error"),
            "body_preview": result.get("body_preview"),
            "sha256": digest,
            "provider": provider,
        }
    state["last_pushed_sha256"] = digest
    state["last_pushed_at"] = __import__("datetime").datetime.now(
        tz=__import__("datetime").timezone.utc
    ).isoformat()
    state["last_pushed_bytes"] = len(payload)
    state["provider"] = provider
    _save_state(state)
    return {
        "pushed": True,
        "reason": "uploaded",
        "sha256": digest,
        "bytes": len(payload),
        "http_status": result.get("http_status"),
        "provider": provider,
    }


def restore_from_remote_if_needed(conn) -> dict[str, Any]:
    """On empty local DB, download remote package and apply (overwrite).

    Runs before the HAMSTER seed. When restore succeeds, seed must not replace
    restored edits. Seed only fills posts when the DB is still empty of posts.

    Note: ``initialize_database`` / migrations always insert an empty Red Rock
    client shell. That alone must not block remote restore — we key off posts
    (and optional prompt overrides) as “has real data”.
    """
    cfg = persist_config()
    if not cfg["enabled"]:
        return {"restored": False, "reason": "disabled", "provider": cfg.get("provider")}
    client_count = int(conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0])
    post_count = int(conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
    prompt_count = 0
    try:
        if conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='maaike_prompt_settings'"
        ).fetchone():
            prompt_count = int(
                conn.execute("SELECT COUNT(*) FROM maaike_prompt_settings").fetchone()[0]
            )
    except Exception:
        prompt_count = 0
    force = os.getenv("MAAIKE_PERSIST_RESTORE_ALWAYS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    # Empty migration shell (clients, 0 posts, 0 prompt overrides) is still "empty".
    if (post_count > 0 or prompt_count > 0) and not force:
        return {
            "restored": False,
            "reason": "local_has_data",
            "clients": client_count,
            "posts": post_count,
            "prompt_settings": prompt_count,
        }

    load_dotenv(override=False)
    url = os.getenv("MAAIKE_PERSIST_BACKUP_URL", "").strip()
    provider = cfg.get("provider") or _provider_for_url(url)
    fetched = _get_github(url) if provider == "github" else _get_http(url)
    if not fetched.get("ok"):
        return {
            "restored": False,
            "reason": fetched.get("reason") or "download_failed",
            "http_status": fetched.get("http_status"),
            "error": fetched.get("error"),
            "provider": provider,
        }
    data = fetched["data"]
    transfer = _data_transfer()
    try:
        transfer.validate_package(data)
    except ValueError as exc:
        return {"restored": False, "reason": "invalid_package", "error": str(exc), "provider": provider}

    result = transfer.apply_import(conn, data, overwrite=True)
    digest = content_fingerprint(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    state = _load_state()
    state["last_restored_sha256"] = digest
    state["last_restored_at"] = __import__("datetime").datetime.now(
        tz=__import__("datetime").timezone.utc
    ).isoformat()
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    state["last_pushed_sha256"] = content_fingerprint(raw)
    state["provider"] = provider
    _save_state(state)
    return {
        "restored": True,
        "reason": "applied",
        "stats": result.get("stats") if isinstance(result, dict) else result,
        "clients_before": client_count,
        "posts_before": post_count,
        "provider": provider,
        "seed_should_skip": True,
    }


def public_persist_status() -> dict[str, Any]:
    try:
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
            "hamster_seed": "maaike/seed/hamster_redrock.json.gz",
            "backup_repo_hint": "https://github.com/SandrinePr/hamster-persist (private)",
            "free_tier_note": (
                "Without a Render disk, SQLite is ephemeral. On boot: remote persist "
                "restores first (when configured); HAMSTER seed only fills empty posts. "
                "Meta tokens stay out of the backup — reconnect Meta after a wipe if Fetch is needed."
            ),
        }
    except Exception as exc:
        return {
            "enabled": False,
            "has_url": False,
            "has_token": False,
            "url_host": "",
            "provider": "http",
            "missing": ["persist_status_error"],
            "error": exc.__class__.__name__,
            "note": "Persist status failed safely; dashboard can still boot.",
            "hamster_seed": "maaike/seed/hamster_redrock.json.gz",
            "free_tier_note": (
                "Without a Render disk, SQLite is ephemeral. Configure MAAIKE_PERSIST_* "
                "with the private hamster-persist GitHub Contents URL."
            ),
        }
