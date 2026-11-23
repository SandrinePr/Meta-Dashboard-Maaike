"""LOCAL_TEST: Claude postfeedback prepare + mock (no paid call)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maaike.db import initialize_database, transaction
from maaike.prompt_settings import active_prompt_text, save_prompt_override
from maaike_web.app import create_app
from maaike_web.session import clear_store


@pytest.fixture
def api(tmp_path, monkeypatch: pytest.MonkeyPatch):
    clear_store()
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "claude_feedback.db"))
    monkeypatch.setenv("MAAIKE_SESSION_SECRET", "test-session-secret")
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    initialize_database()
    with TestClient(create_app()) as client:
        yield client
    clear_store()


def _seed_post(conn, client_id: int) -> int:
    cur = conn.execute(
        """
        INSERT INTO posts (
            client_id, platform, external_id, published_at, content_kind,
            permalink, account_name, caption, media_urls, last_synced_at,
            reach, likes, comments
        ) VALUES (?, 'instagram', 'ext-mock-1', '2026-10-15T12:00:00+00:00', 'image',
                  'https://instagram.com/p/mock', 'redrock', 'Test caption',
                  'https://cdn.example/image.jpg', '2026-10-15T12:00:00+00:00',
                  1200, 40, 3)
        """,
        (client_id,),
    )
    return int(cur.lastrowid)


def test_prompt_override_and_mock_feedback(api, monkeypatch):
    monkeypatch.setattr(
        "maaike.post_analysis_workflow.prepare_post_media",
        lambda **kwargs: {
            "coverage": "caption_only",
            "images_for_model": [],
            "missing": ["afbeelding"],
            "limitations": ["Geen bereikbare afbeelding"],
            "full_video_to_model": False,
            "audio_to_model": False,
            "media_url_count": 1,
            "media_source": "meta_urls",
        },
    )
    monkeypatch.setattr(
        "maaike.post_analysis_workflow.claude_connection_status",
        lambda: {
            "configured": False,
            "missing_setting": "CLAUDE_API_KEY",
            "env_file_hint": ".env",
            "model": "claude-sonnet-4-5",
        },
    )
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        save_prompt_override(
            conn,
            "post_analysis",
            body_text="CUSTOM POST PROMPT FOR MAAIKE — mock test marker.",
            version_tag="post-custom-v-test",
            updated_by="test",
        )
        active = active_prompt_text(conn, "post_analysis")
        assert active["source"] == "dashboard_override"
        assert active["version_tag"] == "post-custom-v-test"
        post_id = _seed_post(conn, client_id)

    prepared = api.post(f"/api/clients/{client_id}/posts/{post_id}/analysis/prepare")
    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["paid_call"] is False
    assert body["provider"] == "Anthropic Claude"
    assert body["prompt_version"] == "post-custom-v-test"
    assert body["prompt_source"] == "dashboard_override"
    analysis_id = body["analysis_id"]

    mocked = api.post(
        f"/api/clients/{client_id}/posts/{post_id}/analysis/mock",
        json={"analysis_id": analysis_id},
    )
    assert mocked.status_code == 200, mocked.text
    mock_body = mocked.json()
    assert mock_body["is_mock"] is True
    assert mock_body["paid_call"] is False
    assert mock_body["input_checks"]["system_prompt"] is True
    assert mock_body["input_checks"]["metrics"] is True
    assert mock_body["input_checks"]["prompt_version"] == "post-custom-v-test"
    analysis = mock_body["analysis"]
    assert analysis["status"] == "mock_completed"
    assert analysis["prompt_version"] == "post-custom-v-test"
    assert "MOCK" in (analysis["insight_text"] or "")

    # Paid execute without Claude key must fail clearly (no silent Gemini fallback).
    paid = api.post(
        f"/api/clients/{client_id}/posts/{post_id}/analysis/execute",
        json={"confirm": True, "analysis_id": analysis_id, "max_cost_usd": 1},
    )
    assert paid.status_code == 400
    assert "Claude" in paid.json()["detail"]


def test_render_external_url_sets_oauth_callback(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://hamster-8zgq.onrender.com")
    # Empty string blocks dotenv from re-filling localhost defaults into these slots.
    monkeypatch.setenv("MAAIKE_FRONTEND_URL", "")
    monkeypatch.setenv("MAAIKE_BACKEND_URL", "")
    monkeypatch.setenv("MAAIKE_WEB_OAUTH_REDIRECT_URI", "")
    from maaike_web.settings import load_settings

    settings = load_settings()
    assert settings.backend_url == "https://hamster-8zgq.onrender.com"
    assert settings.oauth_redirect_uri == "https://hamster-8zgq.onrender.com/api/meta/callback"


def test_render_overrides_stale_onrender_oauth_redirect(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://hamster-8zgq.onrender.com")
    monkeypatch.setenv("MAAIKE_FRONTEND_URL", "https://old-hamster.onrender.com")
    monkeypatch.setenv("MAAIKE_BACKEND_URL", "https://old-hamster.onrender.com")
    monkeypatch.setenv(
        "MAAIKE_WEB_OAUTH_REDIRECT_URI",
        "https://old-hamster.onrender.com/api/meta/callback",
    )
    from maaike_web.settings import load_settings

    settings = load_settings()
    assert settings.frontend_url == "https://hamster-8zgq.onrender.com"
    assert settings.backend_url == "https://hamster-8zgq.onrender.com"
    assert settings.oauth_redirect_uri == "https://hamster-8zgq.onrender.com/api/meta/callback"


def test_local_oauth_callback_keeps_explicit_loopback(monkeypatch):
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.setenv("MAAIKE_FRONTEND_URL", "https://127.0.0.1:5173")
    monkeypatch.setenv("MAAIKE_BACKEND_URL", "https://127.0.0.1:8000")
    monkeypatch.setenv(
        "MAAIKE_WEB_OAUTH_REDIRECT_URI",
        "https://127.0.0.1:8000/api/meta/callback",
    )
    from maaike_web.settings import load_settings

    settings = load_settings()
    assert settings.oauth_redirect_uri == "https://127.0.0.1:8000/api/meta/callback"


def test_persist_skips_unchanged_upload(tmp_path, monkeypatch):
    from maaike.db import initialize_database, transaction
    from maaike.persist_remote import content_fingerprint, push_if_changed

    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "persist.db"))
    monkeypatch.setenv("MAAIKE_PERSIST_ENABLED", "1")
    monkeypatch.setenv("MAAIKE_PERSIST_BACKUP_URL", "https://example.test/backup.json")
    initialize_database()

    calls = {"n": 0}

    class FakeResp:
        status_code = 200

    def fake_put(url, data=None, headers=None, timeout=None):
        calls["n"] += 1
        calls["bytes"] = len(data or b"")
        calls["sha"] = content_fingerprint(data or b"")
        return FakeResp()

    monkeypatch.setattr("maaike.persist_remote.requests.put", fake_put)
    with transaction() as conn:
        first = push_if_changed(conn)
        second = push_if_changed(conn)
    assert first["pushed"] is True
    assert second["pushed"] is False
    assert second["reason"] == "unchanged"
    assert calls["n"] == 1
