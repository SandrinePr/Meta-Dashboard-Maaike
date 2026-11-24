"""Role gates for Technisch beheer (feedback points 3 & 6)."""

from __future__ import annotations

import base64
import os

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


def test_session_reports_role(role_client):
    admin = role_client.get("/api/session", headers=_basic("admin", "admin-secret"))
    assert admin.status_code == 200
    body = admin.json()
    assert body["role"] == "admin"
    assert body["can_tech_admin"] is True
    assert body["role_enforced"] is True

    editor = role_client.get("/api/session", headers=_basic("editor", "editor-secret"))
    assert editor.status_code == 200
    assert editor.json()["role"] == "editor"
    assert editor.json()["can_tech_admin"] is False
    assert editor.json()["can_edit_clients"] is True
    assert editor.json()["can_delete_clients"] is False

    viewer = role_client.get("/api/session", headers=_basic("viewer", "viewer-secret"))
    assert viewer.status_code == 200
    assert viewer.json()["role"] == "viewer"
    assert viewer.json()["can_edit_clients"] is False


def test_tech_apis_forbidden_for_editor_and_viewer(role_client):
    for user, password in (("editor", "editor-secret"), ("viewer", "viewer-secret")):
        headers = _basic(user, password)
        assert role_client.get("/api/ai-status", headers=headers).status_code == 403
        assert role_client.get("/api/prompt-settings", headers=headers).status_code == 403
        assert role_client.get("/api/report-planning", headers=headers).status_code == 403
        assert role_client.get("/api/export/package.json", headers=headers).status_code == 403


def test_admin_can_open_tech_apis(role_client):
    headers = _basic("admin", "admin-secret")
    assert role_client.get("/api/ai-status", headers=headers).status_code == 200
    assert role_client.get("/api/prompt-settings", headers=headers).status_code == 200


def test_editor_can_list_clients_but_not_delete(role_client):
    headers = _basic("editor", "editor-secret")
    listed = role_client.get("/api/clients", headers=headers)
    assert listed.status_code == 200
    created = role_client.post("/api/clients", headers=headers, json={"name": "Roltest"})
    assert created.status_code == 201
    body = created.json()
    client_id = body.get("id") or body.get("client_id") or (body.get("client") or {}).get("id")
    assert client_id
    deleted = role_client.delete(f"/api/clients/{client_id}", headers=headers)
    assert deleted.status_code == 403


def test_viewer_cannot_mutate(role_client):
    headers = _basic("viewer", "viewer-secret")
    assert role_client.get("/api/clients", headers=headers).status_code == 200
    assert role_client.post("/api/clients", headers=headers, json={"name": "X"}).status_code == 403


def test_unauthenticated_gets_401_when_passwords_set(role_client):
    assert role_client.get("/api/session").status_code == 401
    assert role_client.get("/api/ai-status").status_code == 401


def test_open_mode_default_role_editor_blocks_tech(tmp_path, monkeypatch):
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
        assert session.json()["role_enforced"] is False
        assert client.get("/api/ai-status").status_code == 403
        assert client.get("/api/clients").status_code == 200
