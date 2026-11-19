"""Render health check must stay open when Basic Auth is enabled."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient


def test_health_open_with_basic_auth(monkeypatch):
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_USER", "maaike")
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_PASSWORD", "secret-for-test")
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", os.environ.get("MAAIKE_DATABASE_PATH", "data/maaike_redrock.db"))
    # Fresh app so middleware picks up env.
    from maaike_web.app import create_app

    client = TestClient(create_app())
    open_health = client.get("/api/health")
    assert open_health.status_code == 200
    assert open_health.json()["status"] == "ok"

    blocked = client.get("/api/clients")
    assert blocked.status_code == 401
    assert blocked.headers.get("www-authenticate", "").lower().startswith("basic")

    allowed = client.get(
        "/api/clients",
        headers={"Authorization": "Basic bWFhaWtlOnNlY3JldC1mb3ItdGVzdA=="},  # maaike:secret-for-test
    )
    assert allowed.status_code == 200
