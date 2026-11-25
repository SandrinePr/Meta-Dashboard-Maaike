"""Canva Connect OAuth PKCE + refresh + import (no paid AI)."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


@pytest.fixture()
def canva_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "canva_oauth.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    monkeypatch.setenv("MAAIKE_PERSIST_ENABLED", "0")
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_PASSWORD", "")
    monkeypatch.setenv("MAAIKE_EDITOR_AUTH_PASSWORD", "")
    monkeypatch.setenv("MAAIKE_VIEWER_AUTH_PASSWORD", "")
    monkeypatch.setenv("CANVA_CLIENT_ID", "OC-test-client")
    monkeypatch.setenv("CANVA_CLIENT_SECRET", "canva-secret-value")
    monkeypatch.setenv("CANVA_REDIRECT_URI", "https://hamster.test/api/canva/callback")
    monkeypatch.delenv("CANVA_ACCESS_TOKEN", raising=False)

    from maaike.db import initialize_database, transaction
    from maaike.repository import add_client
    from maaike.strategy import save_strategy
    from maaike_web.app import create_app

    initialize_database(db)
    with transaction(db) as conn:
        client_id = add_client(conn, "Canva OAuth Klant")
        save_strategy(conn, client_id, start_answers={"website": "https://handmatig.example"})

    app = create_app()
    with TestClient(app) as http:
        yield http, client_id


def _strategy_pdf_bytes() -> bytes:
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.drawString(72, 750, "Tone of voice")
    pdf.drawString(72, 730, "Warm en kort.")
    pdf.drawString(72, 700, "Doelgroep")
    pdf.drawString(72, 680, "MKB met groeidoelen.")
    pdf.save()
    return buf.getvalue()


def test_oauth_start_uses_pkce_and_minimal_scope(canva_http):
    http, _client_id = canva_http
    res = http.post("/api/canva/oauth/start")
    assert res.status_code == 200
    body = res.json()
    assert "code_challenge=" in body["authorize_url"]
    assert "code_challenge_method=s256" in body["authorize_url"]
    assert "design%3Acontent%3Aread" in body["authorize_url"] or "design:content:read" in body[
        "authorize_url"
    ]
    assert "design:content:write" not in body["authorize_url"]
    assert body["scopes"] == ["design:content:read"]


def test_oauth_callback_stores_tokens_server_side(canva_http, monkeypatch):
    http, _client_id = canva_http
    started = http.post("/api/canva/oauth/start").json()
    state = started["state"]

    def _fake_token(form):
        assert form["grant_type"] == "authorization_code"
        assert form["code_verifier"]
        return {
            "access_token": "access-live-1",
            "refresh_token": "refresh-live-1",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "design:content:read",
        }

    monkeypatch.setattr("maaike.canva_connect._token_request", _fake_token)
    res = http.get(
        "/api/canva/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert res.status_code in {302, 307}
    assert "canva=connected" in res.headers.get("location", "")

    status = http.get("/api/canva/status").json()
    assert status["connected"] is True
    assert status["refresh_available"] is True
    assert "access_token" not in status
    assert "refresh_token" not in status

    # Secrets must not appear in backup export (table may be listed as omitted).
    package = http.get("/api/export/package.json")
    assert package.status_code in {200, 401, 403}
    if package.status_code == 200:
        body = package.json()
        text = package.text
        assert "access-live-1" not in text
        assert "refresh-live-1" not in text
        assert "canva_oauth_secrets" not in body
        assert "canva_oauth_secrets" in (body.get("secret_tables_omitted") or [])


def test_token_refresh_and_expired_without_refresh(canva_http, monkeypatch):
    from maaike.canva_connect import CanvaAccessError, ensure_canva_tables, refresh_access_token
    from maaike.db import transaction

    http, _client_id = canva_http
    _ = http

    with transaction() as conn:
        ensure_canva_tables(conn)
        past = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            """
            INSERT INTO canva_oauth_secrets
                (id, access_token, refresh_token, token_type, scope, expires_at, connected_at, updated_at)
            VALUES (1, 'old-access', 'refresh-abc', 'Bearer', 'design:content:read', ?, ?, ?)
            """,
            (past, past, past),
        )

    calls = {"n": 0}

    def _refresh(form):
        calls["n"] += 1
        assert form["grant_type"] == "refresh_token"
        assert form["refresh_token"] == "refresh-abc"
        return {
            "access_token": "new-access",
            "refresh_token": "refresh-xyz",
            "expires_in": 3600,
            "scope": "design:content:read",
        }

    monkeypatch.setattr("maaike.canva_connect._token_request", _refresh)
    with transaction() as conn:
        token = refresh_access_token(conn)
    assert token == "new-access"
    assert calls["n"] == 1

    # Expired access, no refresh → clear error
    with transaction() as conn:
        ensure_canva_tables(conn)
        past = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute("DELETE FROM canva_oauth_secrets")
        conn.execute(
            """
            INSERT INTO canva_oauth_secrets
                (id, access_token, refresh_token, token_type, scope, expires_at, connected_at, updated_at)
            VALUES (1, 'stale', '', 'Bearer', 'design:content:read', ?, ?, ?)
            """,
            (past, past, past),
        )
        with pytest.raises(CanvaAccessError, match="verlopen"):
            refresh_access_token(conn)


def test_allowed_design_proposes_empty_fields_only(canva_http, monkeypatch):
    http, client_id = canva_http
    from maaike.strategy_import import preview_canva_link

    monkeypatch.setenv("CANVA_ACCESS_TOKEN", "test-token")
    preview = preview_canva_link(
        "https://www.canva.com/design/DAFstrategyOK/view",
        pdf_bytes=_strategy_pdf_bytes(),
        access_token="test-token",
    )
    assert preview["content_extracted"] is True
    assert "tone_of_voice" in preview["proposed"]["start_answers"]

    staged = http.post(
        f"/api/clients/{client_id}/strategy/import/apply",
        json={
            "proposed": preview["proposed"],
            "preserve_manual": True,
            "stage_only": True,
            "source_kind": "canva",
        },
    ).json()
    pending = staged["pending_proposal"]
    assert pending["start_answers"]["tone_of_voice"]
    assert "website" not in pending["start_answers"]  # already filled manually

    approved = http.post(
        f"/api/clients/{client_id}/strategy/proposal/approve",
        json={"proposal": pending},
    ).json()
    assert approved["start_answers"]["website"] == "https://handmatig.example"
    assert approved["start_answers"]["tone_of_voice"] == "Warm en kort."
    assert approved["pending_proposal"] is None


def test_design_without_access_returns_403(canva_http, monkeypatch):
    from maaike.canva_connect import CanvaAccessError

    http, client_id = canva_http
    monkeypatch.setenv("CANVA_ACCESS_TOKEN", "test-token")

    def _denied(design_id: str, **_kwargs):
        raise CanvaAccessError(
            f"Canva weigerde toegang tot dit ontwerp (HTTP 403). Design-id: {design_id}."
        )

    monkeypatch.setattr("maaike.canva_connect.export_design_pdf_bytes", _denied)
    res = http.post(
        f"/api/clients/{client_id}/strategy/import/canva-preview",
        json={"url": "https://www.canva.com/design/DAFNoAccess/view"},
    )
    assert res.status_code == 403
    assert "toegang" in res.json()["detail"].lower()


def test_without_connection_keeps_pdf_path(canva_http, monkeypatch):
    http, client_id = canva_http
    monkeypatch.delenv("CANVA_ACCESS_TOKEN", raising=False)
    # Clear any oauth secrets
    from maaike.canva_connect import disconnect_oauth
    from maaike.db import transaction

    with transaction() as conn:
        disconnect_oauth(conn)

    res = http.post(
        f"/api/clients/{client_id}/strategy/import/canva-preview",
        json={"url": "https://www.canva.com/design/DAHDJ6X9OC8/view"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["content_extracted"] is False
    assert any("PDF" in q for q in body.get("open_questions") or [])
    status = http.get("/api/canva/status").json()
    assert "Private of Public" in status["admin_steps_nl"] or "private" in status["admin_steps_nl"].lower()
