"""Feed filters and performance stay client-scoped."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maaike.db import transaction
from maaike.feed import feed_card, filter_posts, parse_media_urls
from maaike.repository import StoredPost, add_client
from maaike_web.app import create_app
from maaike_web.session import clear_store


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clear_store()
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "maaike.db"))
    monkeypatch.setenv("MAAIKE_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("MAAIKE_FRONTEND_URL", "http://127.0.0.1:5173")
    monkeypatch.setenv("MAAIKE_BACKEND_URL", "http://127.0.0.1:8000")
    with TestClient(create_app()) as client:
        yield client
    clear_store()


def _seed(client_id: int) -> tuple[int, int]:
    with transaction() as conn:
        first = conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, content_kind, permalink,
                views, likes, comments, shares, saves, clicks, reach, account_name, caption, media_urls,
                last_synced_at
            ) VALUES (?, 'instagram', 'ig-1', '2026-10-05T08:30:00+00:00', 'reel',
                      'https://instagram.com/p/one', 10, 2, 1, NULL, 0, NULL, 8, '@one', 'Hallo wereld',
                      'https://example.com/a.jpg\nhttps://example.com/a.mp4',
                      '2026-10-16T07:00:19+00:00')
            """,
            (client_id,),
        ).lastrowid
        second = conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, content_kind, permalink,
                views, likes, comments, shares, saves, clicks, reach, account_name, caption, media_urls,
                last_synced_at
            ) VALUES (?, 'facebook', 'fb-1', '2026-09-01T08:30:00+00:00', 'photo',
                      'https://facebook.com/p/two', NULL, 0, NULL, NULL, NULL, NULL, NULL, 'Page', 'Andere tekst',
                      NULL, '2026-10-16T07:00:19+00:00')
            """,
            (client_id,),
        ).lastrowid
        return int(first), int(second)


def test_parse_media_marks_video_and_image() -> None:
    items = parse_media_urls("https://cdn.example/x.jpg\nhttps://cdn.example/y.mp4")
    assert [item["kind"] for item in items] == ["image", "video"]


def test_feed_card_keeps_zero_and_missing() -> None:
    post = StoredPost(
        post_id=1,
        platform="facebook",
        published_at="2026-09-01T08:30:00+00:00",
        content_kind="photo",
        permalink=None,
        views=None,
        likes=0,
        comments=None,
        shares=None,
        saves=None,
        clicks=None,
        last_synced_at=None,
        format_id=None,
        format_name=None,
        pillar_id=None,
        pillar_name=None,
        hook="",
        media_urls=None,
    )
    card = feed_card(post)
    assert card["metrics"]["likes"]["label"] == "0"
    assert card["metrics"]["views"]["label"] == "not available"
    assert card["media_note"] == "No media available for this post."


def test_filter_posts_by_platform_and_query() -> None:
    posts = [
        StoredPost(
            post_id=1,
            platform="instagram",
            published_at="2026-10-05T08:30:00+00:00",
            content_kind="reel",
            permalink=None,
            views=1,
            likes=1,
            comments=1,
            shares=None,
            saves=None,
            clicks=None,
            last_synced_at=None,
            format_id=None,
            format_name=None,
            pillar_id=None,
            pillar_name=None,
            hook="",
            caption="Hallo wereld",
        ),
        StoredPost(
            post_id=2,
            platform="facebook",
            published_at="2026-09-01T08:30:00+00:00",
            content_kind="photo",
            permalink=None,
            views=None,
            likes=0,
            comments=None,
            shares=None,
            saves=None,
            clicks=None,
            last_synced_at=None,
            format_id=None,
            format_name=None,
            pillar_id=None,
            pillar_name=None,
            hook="",
            caption="Andere tekst",
        ),
    ]
    found = filter_posts(posts, query="wereld", platforms={"instagram"})
    assert [post.post_id for post in found] == [1]


def test_feed_and_performance_endpoints(api: TestClient) -> None:
    created = api.post("/api/clients", json={"name": "Acme"})
    client_id = created.json()["id"]
    first, second = _seed(client_id)

    feed = api.get(f"/api/clients/{client_id}/feed?platform=instagram")
    assert feed.status_code == 200
    body = feed.json()
    assert body["total"] == 1
    assert body["posts"][0]["id"] == first
    assert body["posts"][0]["has_video"] is True
    assert body["posts"][0]["metrics"]["saves"]["label"] == "0"

    detail = api.get(f"/api/clients/{client_id}/posts/{second}")
    assert detail.status_code == 200
    assert detail.json()["metrics"]["likes"]["label"] == "0"
    assert detail.json()["metrics"]["views"]["label"] == "not available"

    overview = api.get(f"/api/clients/{client_id}/overview")
    assert overview.json()["post_count"] == 2
    assert overview.json()["instagram_count"] == 1

    perf = api.get(f"/api/clients/{client_id}/performance?year=2026&month=10")
    assert perf.status_code == 200
    likes = next(section for section in perf.json()["sections"] if section["metric"] == "likes")
    assert likes["posts"][0]["id"] == first

    other = api.post("/api/clients", json={"name": "Other"}).json()["id"]
    foreign = api.get(f"/api/clients/{other}/posts/{first}")
    assert foreign.status_code == 404


def test_ai_status_hides_secrets(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AI_API_KEY", "secret-key-value")
    monkeypatch.setenv("AI_MODEL", "demo-model")
    payload = api.get("/api/ai-status").json()
    assert payload["configured"] is True
    assert payload["has_api_key"] is True
    assert "secret-key-value" not in str(payload)
    assert payload["model"] == "demo-model"
