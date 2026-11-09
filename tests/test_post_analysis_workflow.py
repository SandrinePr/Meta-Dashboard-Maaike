"""LOCAL_TEST: post media inventory + prepare/save insight (no paid AI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maaike.db import initialize_database, transaction
from maaike.figma_planning import week_letter_for_date
from maaike.post_analysis_workflow import (
    analysis_panel,
    inventory_for_post,
    prepare_post_analysis,
    save_reviewed_insight,
)
from maaike.report_metrics import attach_assessments_and_ai, summarize_attached_ai_analyses
from maaike_web.app import create_app
from maaike_web.session import clear_store
from datetime import date


@pytest.fixture
def api(tmp_path, monkeypatch: pytest.MonkeyPatch):
    clear_store()
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "workflow.db"))
    monkeypatch.setenv("MAAIKE_SESSION_SECRET", "test-session-secret")
    initialize_database()
    with TestClient(create_app()) as client:
        yield client
    clear_store()


def _seed_post(conn, client_id: int, *, kind: str, media: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO posts (
            client_id, platform, external_id, published_at, content_kind,
            permalink, account_name, caption, media_urls, last_synced_at
        ) VALUES (?, 'instagram', ?, '2026-10-15T12:00:00+00:00', ?, ?, 'redrock', 'caption', ?, ?)
        """,
        (
            client_id,
            f"ext-{kind}-{media[:12] or kind}",
            kind,
            f"https://instagram.com/p/{kind}",
            media or None,
            "2026-10-15T12:00:00+00:00",
        ),
    )
    return int(cur.lastrowid)


def test_week_letter_nov_3_is_b():
    assert week_letter_for_date(date(2026, 11, 3), year=2026, month=11) == "B"


def test_inventory_reel_thumbnail_only_and_story_gap(api):
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        reel_id = _seed_post(
            conn,
            client_id,
            kind="reel",
            media="https://cdn.example/thumb.jpg",
        )
        story_id = _seed_post(conn, client_id, kind="story", media="")

    with transaction() as conn:
        reel = inventory_for_post(conn, client_id, reel_id)
        assert reel["analysis_role"] == "reel"
        assert any("thumbnail" in x.lower() or "no full video" in x.lower() for x in reel["limitations"])
        story = inventory_for_post(conn, client_id, story_id)
        assert story["analysis_role"] == "story"
        assert any("story" in x.lower() for x in story["limitations"])


def test_prepare_and_save_insight_attaches_to_report_posts(api, monkeypatch):
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
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        post_id = _seed_post(
            conn,
            client_id,
            kind="image",
            media="https://cdn.example/image.jpg",
        )
        prep = prepare_post_analysis(conn, client_id, post_id, download_media=True)
        assert prep["status"] == "prepared_not_executed"
        assert prep["paid_call"] is False
        saved = save_reviewed_insight(
            conn,
            client_id,
            post_id,
            {
                "insight_text": "Hook werkte; CTA zwak.",
                "action_text": "Herhaal hook; test sterkere CTA.",
                "rating_text": "Gemiddeld",
                "source_analysis_id": prep["analysis_id"],
            },
        )
        assert saved["analysis"]["status"] == "completed"
        assert "Hook werkte" in saved["analysis"]["insight_text"]

        posts = [{"post_id": post_id}]
        attached = attach_assessments_and_ai(conn, client_id, posts)
        summary = summarize_attached_ai_analyses(attached)
        assert summary["completed_post_ai_analyses"] == 1
        assert attached[0]["ai_analysis"]["insight_text"].startswith("Hook werkte")

        panel = analysis_panel(conn, client_id, post_id)
        assert panel["paid_call_on_open"] is False
        assert panel["draft"]["insight_text"].startswith("Hook werkte")


def test_http_analysis_panel_routes(api, monkeypatch):
    monkeypatch.setattr(
        "maaike.post_analysis_workflow.prepare_post_media",
        lambda **kwargs: {
            "coverage": "image_and_caption",
            "images_for_model": [{"path": "x.jpg", "bytes": 10}],
            "missing": [],
            "limitations": [],
            "full_video_to_model": False,
            "audio_to_model": False,
            "media_url_count": 1,
            "media_source": "meta_urls",
        },
    )
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        post_id = _seed_post(
            conn,
            client_id,
            kind="carousel_album",
            media="https://cdn.example/a.jpg\nhttps://cdn.example/b.jpg",
        )

    panel = api.get(f"/api/clients/{client_id}/posts/{post_id}/analysis-panel")
    assert panel.status_code == 200
    assert panel.json()["inventory"]["analysis_role"] == "carousel"

    prepared = api.post(f"/api/clients/{client_id}/posts/{post_id}/analysis/prepare")
    assert prepared.status_code == 200
    body = prepared.json()
    assert body["paid_call"] is False
    assert body["status"] == "prepared_not_executed"

    saved = api.patch(
        f"/api/clients/{client_id}/posts/{post_id}/analysis/insight",
        json={
            "insight_text": "Carousel slide 1 droeg het meeste.",
            "action_text": "Zet sterkste slide eerst.",
            "source_analysis_id": body["analysis_id"],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["analysis"]["status"] == "completed"
