"""Check Meta + Claude access without printing secrets."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

from maaike.db import connect
from maaike.meta_connect import verify_stored_connection
from maaike.repository import connection_label, get_client, load_page_secret

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://127.0.0.1:8000"
CTX = ssl._create_unverified_context()


def call(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload


def main() -> None:
    file_vals = dotenv_values(ROOT / ".env")
    print(
        "claude_vars",
        {
            "CLAUDE_API_KEY_in_dotenv": bool((file_vals.get("CLAUDE_API_KEY") or "").strip()),
            "ANTHROPIC_API_KEY_in_dotenv": bool((file_vals.get("ANTHROPIC_API_KEY") or "").strip()),
            "CLAUDE_API_KEY_in_process": bool(os.getenv("CLAUDE_API_KEY", "").strip()),
            "ANTHROPIC_API_KEY_in_process": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
            "process_would_block_dotenv": bool(
                os.getenv("ANTHROPIC_API_KEY", "").strip()
                and not (file_vals.get("ANTHROPIC_API_KEY") or "").strip()
                and not (file_vals.get("CLAUDE_API_KEY") or "").strip()
            ),
        },
    )

    conn = connect()
    client = get_client(conn, 1)
    secret = load_page_secret(conn, 1)
    print(
        "meta_local",
        {
            "client": getattr(client, "name", None) or (client["name"] if client else None),
            "label": connection_label(client) if client else None,
            "secret_present": secret is not None,
            "page_id": secret[0] if secret else None,
            "ig_id": secret[1] if secret else None,
            "token_len": len(secret[2]) if secret else 0,
        },
    )

    # Live Graph check via existing helper if available
    try:
        result = verify_stored_connection(conn, 1)
        print(
            "meta_verify",
            {
                "ok": getattr(result, "ok", None) if not isinstance(result, dict) else result.get("ok"),
                "summary": str(result)[:300],
            },
        )
    except Exception as exc:  # noqa: BLE001
        print("meta_verify_error", type(exc).__name__, str(exc)[:200])

    st, payload = call("GET", "/api/clients/1/meta")
    print("meta_api_http", st)
    if isinstance(payload, dict):
        safe = {
            k: payload.get(k)
            for k in (
                "connected",
                "status_label",
                "page_name",
                "instagram_username",
                "facebook_page_name",
                "message",
                "error",
                "needs_reauth",
                "recheck",
            )
            if k in payload or True
        }
        # Keep only non-secret-ish fields that exist
        print(
            "meta_api",
            {
                k: v
                for k, v in payload.items()
                if k
                not in {
                    "access_token",
                    "page_token",
                    "token",
                    "user_token",
                    "pages",
                }
                and "token" not in k.lower()
            },
        )
        if "pages" in payload and isinstance(payload["pages"], list):
            print(
                "meta_pages",
                [
                    {
                        "page_name": p.get("page_name") or p.get("name"),
                        "ig_username": p.get("ig_username") or p.get("instagram_username"),
                    }
                    for p in payload["pages"][:5]
                    if isinstance(p, dict)
                ],
            )


if __name__ == "__main__":
    main()
