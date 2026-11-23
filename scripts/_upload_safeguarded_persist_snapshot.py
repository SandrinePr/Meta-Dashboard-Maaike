"""Replace GitHub hamster-persist snapshot with safeguarded live export (no secrets).

Never uploads Meta tokens. Source is the local safeguarded all-clients export
(Red Rock + BBQube), not the old Red-Rock-only remote file.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "data" / "backups" / "maaike-live-all-clients-20261123-144028.json"
BACKUP_URL = (
    "https://api.github.com/repos/SandrinePr/hamster-persist/contents/hamster-maaike-backup.json"
)


def _token() -> str:
    env = os.getenv("MAAIKE_PERSIST_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if env:
        return env.strip()
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


def main() -> int:
    if not EXPORT.is_file():
        print("MISSING", EXPORT)
        return 1
    raw = EXPORT.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("secrets_excluded") is not True:
        print("REFUSING: secrets_excluded is not true")
        return 2
    if "client_meta_secrets" in data:
        print("REFUSING: package contains client_meta_secrets key")
        return 3
    names = [c.get("name") for c in data.get("clients") or []]
    if "Red Rock" not in names or "BBQube" not in names:
        print("REFUSING: expected Red Rock + BBQube, got", names)
        return 4

    token = _token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    current = requests.get(BACKUP_URL, headers=headers, timeout=60)
    sha = None
    if current.status_code == 200:
        sha = current.json().get("sha")
    elif current.status_code != 404:
        print("GET_FAILED", current.status_code, current.text[:300])
        return 5

    payload = {
        "message": "Replace snapshot with safeguarded live Red Rock + BBQube export (no secrets)",
        "content": base64.b64encode(raw).decode("ascii"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    put = requests.put(BACKUP_URL, headers=headers, json=payload, timeout=120)
    print("PUT", put.status_code)
    if put.status_code not in {200, 201}:
        print(put.text[:500])
        return 6

    # Verify download
    verify = requests.get(BACKUP_URL, headers=headers, timeout=60)
    download_url = verify.json().get("download_url")
    body = requests.get(download_url, headers=headers, timeout=120)
    remote = body.json()
    remote_names = [c.get("name") for c in remote.get("clients") or []]
    print(
        json.dumps(
            {
                "remote_clients": remote_names,
                "counts": remote.get("counts"),
                "exported_at": remote.get("exported_at"),
                "secrets_excluded": remote.get("secrets_excluded"),
                "bytes": len(body.content),
            },
            ensure_ascii=False,
        )
    )
    if "Red Rock" not in remote_names or "BBQube" not in remote_names:
        print("VERIFY_FAIL")
        return 7
    print("UPLOAD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
