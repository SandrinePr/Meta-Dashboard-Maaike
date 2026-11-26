"""Everyone inside HAMSTER can use the same functions.

App access (Basic Auth accounts, or the open link) stays separate from feature use.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture()
def role_client(tmp_path, monkeypatch):
    db = tmp_path / "roles.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_USER", "admin")
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_PASSWORD", "admin-secret")
    monkeypatch.setenv("MAAIKE_EDITOR_AUTH_USER", "editor")
    monkeypatch.setenv("MAAIKE_EDITOR_AUTH_PASSWORD", "editor-secret")
    monkeypatch.setenv("MAAIKE_VIEWER_AUTH_USER", "viewer")
    monkeypatch.setenv("MAAIKE_VIEWER_AUTH_PASSWORD", "viewer-secret")
    monkeypatch.delenv("MAAIKE_DEFAULT_ROLE", raising=False)
    from maaike_web.app import create_app

    with TestClient(create_app()) as client:
        yield client


def _assert_full_access(body: dict) -> None:
    assert body["can_tech_admin"] is True
    assert body["can_edit_clients"] is True
    assert body["can_delete_clients"] is True
    assert body["role_enforced"] is False


def test_every_account_has_the_same_functions(role_client):
    for user, password, username in (
        ("admin", "admin-secret", "admin"),
        ("editor", "editor-secret", "editor"),
        ("viewer", "viewer-secret", "viewer"),
    ):
        session = role_client.get("/api/session", headers=_basic(user, password))
        assert session.status_code == 200
        body = session.json()
        assert body["username"] == username
        _assert_full_access(body)
        headers = _basic(user, password)
        assert role_client.get("/api/ai-status", headers=headers).status_code == 200
        assert role_client.get("/api/prompt-settings", headers=headers).status_code == 200
        assert role_client.get("/api/report-planning", headers=headers).status_code == 200
        created = role_client.post("/api/clients", headers=headers, json={"name": f"Roltest {user}"})
        assert created.status_code == 201
        payload = created.json()
        client_id = payload.get("id") or payload.get("client_id") or (payload.get("client") or {}).get("id")
        assert client_id
        assert role_client.delete(f"/api/clients/{client_id}", headers=headers).status_code in {200, 204}


def test_open_link_has_the_same_functions(role_client):
    session = role_client.get("/api/session")
    assert session.status_code == 200
    body = session.json()
    assert body["username"] == "open"
    _assert_full_access(body)
    assert role_client.get("/api/ai-status").status_code == 200
    created = role_client.post("/api/clients", json={"name": "Open link"})
    assert created.status_code == 201


def test_open_mode_without_passwords_keeps_full_functions(tmp_path, monkeypatch):
    db = tmp_path / "open.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_PASSWORD", "")
    monkeypatch.setenv("MAAIKE_EDITOR_AUTH_PASSWORD", "")
    monkeypatch.setenv("MAAIKE_VIEWER_AUTH_PASSWORD", "")
    monkeypatch.setenv("MAAIKE_DEFAULT_ROLE", "editor")
    from maaike_web.app import create_app

    with TestClient(create_app()) as client:
        session = client.get("/api/session")
        assert session.status_code == 200
        assert session.json()["role"] == "editor"
        _assert_full_access(session.json())
        assert client.get("/api/ai-status").status_code == 200
        assert client.get("/api/clients").status_code == 200
