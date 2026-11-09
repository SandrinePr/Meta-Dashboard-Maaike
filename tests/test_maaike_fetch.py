"""Post fetch uses a temporary database and never calls the live Meta API."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from maaike.db import transaction
from maaike.meta_connect import MetaConnectError, MetaRateLimitError
from maaike.repository import list_posts, save_verified_link
from maaike_web.app import create_app
from maaike_web.session import clear_store


@pytest.fixture
def api(tmp_path, monkeypatch: pytest.MonkeyPatch):
    clear_store()
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "maaike.db"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "do-not-create.db"))
    monkeypatch.setenv("MAAIKE_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("META_APP_ID", "9000000000000001")
    monkeypatch.setenv("META_APP_SECRET", "taol-secret-value")
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "taol-page-token")
    monkeypatch.setenv("META_USER_ACCESS_TOKEN", "taol-user-token")
    for name in ("MAAIKE_META_APP_ID", "MAAIKE_META_APP_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app()) as client:
        yield client
    clear_store()


def _connect(client_id: int, *, page_token: str, page_id: str, ig_id: str) -> None:
    with transaction() as conn:
        save_verified_link(
            conn,
            client_id,
            page_id=page_id,
            page_name="Red Rock",
            ig_user_id=ig_id,
            ig_username="redrock",
            user_token="user-token-for-this-client",
            page_token=page_token,
            user_expires_at=None,
        )


def _graph(state):
    def get_json(url: str, params, *, secrets):
        state["calls"] += 1
        blob = f"{url} {params} {secrets}"
        assert "taol-page-token" not in blob
        assert "taol-user-token" not in blob
        assert "taol-secret-value" not in blob
        assert "9000000000000001" not in blob
        if state["token"] not in secrets or "page-token-" in blob and state["token"] not in blob:
            raise AssertionError("verkeerde klanttoken")
        for token in ("page-token-a", "page-token-b"):
            if token != state["token"] and token in blob:
                raise AssertionError("token van een andere klant")
        if "/comments" in url:
            return {"data": []}
        if "/insights" in url:
            if state["limit"]:
                raise MetaRateLimitError("Meta beperkt het aantal verzoeken.", code=4)
            metric = (params or {}).get("metric", "")
            if state["repeat"] and metric.startswith("views"):
                return {"data": [{"name": "likes", "values": [{"value": 0}]}]}
            if metric == "post_media_view":
                return {"data": [{"name": "post_media_view", "values": [{"value": 8}]}]}
            if metric == "post_clicks":
                return {"data": [{"name": "post_clicks", "values": [{"value": 0}]}]}
            return {
                "data": [
                    {"name": "views", "values": [{"value": 10}]},
                    {"name": "reach", "values": [{"value": 4}]},
                    {"name": "saved", "values": [{"value": 1}]},
                    {"name": "shares", "values": [{"value": 2}]},
                    {"name": "likes", "values": [{"value": 3}]},
                    {"name": "comments", "values": [{"value": 0}]},
                ]
            }
        if url.endswith("/media"):
            return {
                "data": [
                    {
                        "id": "ig-post-1",
                        "caption": "Hallo Red Rock",
                        "media_type": "VIDEO",
                        "media_product_type": "REELS",
                        "permalink": "https://instagram.com/reel/abc",
                        "timestamp": "2026-10-02T10:00:00+0000",
                        "media_url": "https://cdn.example/reel.mp4",
                        "like_count": 99,
                    }
                ]
            }
        if url.endswith("/published_posts"):
            return {
                "data": [
                    {
                        "id": f"{state['page']}_99",
                        "message": "Facebook tekst",
                        "created_time": "2026-10-03T12:00:00+0000",
                        "permalink_url": "https://facebook.com/posts/99",
                        "status_type": "added_photos",
                        "full_picture": "https://cdn.example/photo.jpg",
                        "likes": {"summary": {"total_count": 5}},
                        "comments": {"summary": {"total_count": 0}},
                        "shares": {"count": 0},
                    }
                ]
            }
        raise MetaConnectError("Onverwacht adres.")

    return get_json


def test_fetch_updates_without_duplicates_and_keeps_manual_fields(api: TestClient, monkeypatch) -> None:
    state = {"calls": 0, "token": "page-token-a", "page": "page-a", "repeat": False, "limit": False}
    monkeypatch.setattr("maaike.post_fetch.graph_get", _graph(state))
    created = api.post("/api/clients", json={"name": "Klant A"}).json()
    _connect(created["id"], page_token="page-token-a", page_id="page-a", ig_id="ig-a")
    state["calls"] = 0
    assert api.get(f"/api/clients/{created['id']}/posts").json()["posts"] == []
    assert state["calls"] == 0

    first = api.post(f"/api/clients/{created['id']}/posts/fetch")
    assert first.status_code == 200
    body = first.json()
    assert body["fetch_status"] == "complete"
    assert "Instagram: 1 posts" in body["fetch_message"]
    assert "Facebook: 1 posts" in body["fetch_message"]
    instagram = next(post for post in body["posts"] if post["cells"]["Platform"] == "Instagram")
    facebook = next(post for post in body["posts"] if post["cells"]["Platform"] == "Facebook")
    assert instagram["cells"]["Weergaven"] == "10"
    assert instagram["cells"]["Bereik"] == "4"
    assert instagram["cells"]["Likes"] == "3"
    assert instagram["cells"]["Comments"] == "0"
    assert instagram["cells"]["Clicks"] == "not available"
    assert instagram["cells"]["Tekst"] == "Hallo Red Rock"
    assert instagram["cells"]["Account"] == "@redrock"
    assert facebook["cells"]["Weergaven"] == "8"
    assert facebook["cells"]["Clicks"] == "0"
    assert facebook["cells"]["Saves"] == "not available"
    assert facebook["cells"]["Bereik"] == "not available"
    assert facebook["cells"]["Comments"] == "0"
    saved = api.patch(
        f"/api/clients/{created['id']}/posts/{instagram['id']}",
        json={"format_id": None, "pillar_id": None, "hook": "Haak blijft"},
    )
    assert saved.status_code == 200

    state["repeat"] = True
    again = api.post(f"/api/clients/{created['id']}/posts/fetch")
    assert again.status_code == 200
    rows = again.json()["posts"]
    assert len(rows) == 2
    instagram = next(post for post in rows if post["cells"]["Platform"] == "Instagram")
    assert instagram["cells"]["Hook"] == "Haak blijft"
    assert instagram["cells"]["Weergaven"] == "10 (previously measured)"
    assert instagram["cells"]["Likes"] == "0"
    with transaction() as conn:
        assert len(list_posts(conn, created["id"])) == 2


def test_clients_cannot_use_each_others_link_or_posts(api: TestClient, monkeypatch) -> None:
    state = {"calls": 0, "token": "page-token-a", "page": "page-a", "repeat": False, "limit": False}
    monkeypatch.setattr("maaike.post_fetch.graph_get", _graph(state))
    client_a = api.post("/api/clients", json={"name": "Klant A"}).json()
    client_b = api.post("/api/clients", json={"name": "Klant B"}).json()
    _connect(client_a["id"], page_token="page-token-a", page_id="page-a", ig_id="ig-a")
    _connect(client_b["id"], page_token="page-token-b", page_id="page-b", ig_id="ig-b")
    api.post(f"/api/clients/{client_a['id']}/posts/fetch")
    state["token"] = "page-token-b"
    state["page"] = "page-b"
    fetched = api.post(f"/api/clients/{client_b['id']}/posts/fetch")
    assert fetched.status_code == 200
    assert "Haak" not in fetched.text
    assert {post["cells"]["Meta-post-ID"] for post in fetched.json()["posts"]} == {
        "ig-post-1",
        "page-b_99",
    }
    with transaction() as conn:
        posts_a = list_posts(conn, client_a["id"])
        denied = api.patch(
            f"/api/clients/{client_b['id']}/posts/{posts_a[0].post_id}",
            json={"format_id": None, "pillar_id": None, "hook": "lek"},
        )
    assert denied.status_code == 400


def test_rate_limit_stops_and_keeps_saved_posts(api: TestClient, monkeypatch) -> None:
    state = {"calls": 0, "token": "page-token-a", "page": "page-a", "repeat": False, "limit": False}
    monkeypatch.setattr("maaike.post_fetch.graph_get", _graph(state))
    created = api.post("/api/clients", json={"name": "Klant A"}).json()
    _connect(created["id"], page_token="page-token-a", page_id="page-a", ig_id="ig-a")
    api.post(f"/api/clients/{created['id']}/posts/fetch")
    calls_before = state["calls"]
    state["limit"] = True
    limited = api.post(f"/api/clients/{created['id']}/posts/fetch")
    assert limited.status_code == 200
    assert limited.json()["fetch_status"] == "partial"
    assert "beperkt" in limited.json()["fetch_message"]
    assert state["calls"] > calls_before
    assert "10 (previously measured)" in limited.text
    assert os.environ.get("META_PAGE_ACCESS_TOKEN") == "taol-page-token"


def test_facebook_reduce_data_retries_leaner_pages(api: TestClient, monkeypatch) -> None:
    """Reproduce Meta 'reduce data' and confirm leaner Facebook pages still store metrics."""
    state = {
        "calls": 0,
        "token": "page-token-a",
        "page": "page-a",
        "repeat": False,
        "limit": False,
        "fb_attempts": 0,
    }

    def get_json(url: str, params, *, secrets):
        state["calls"] += 1
        if "/comments" in url:
            return {"data": []}
        if "/insights" in url:
            metric = (params or {}).get("metric", "")
            if metric == "post_media_view":
                return {"data": [{"name": "post_media_view", "values": [{"value": 8}]}]}
            if metric == "post_clicks":
                return {"data": [{"name": "post_clicks", "values": [{"value": 1}]}]}
            return {
                "data": [
                    {"name": "views", "values": [{"value": 10}]},
                    {"name": "reach", "values": [{"value": 4}]},
                    {"name": "saved", "values": [{"value": 1}]},
                    {"name": "shares", "values": [{"value": 2}]},
                    {"name": "likes", "values": [{"value": 3}]},
                    {"name": "comments", "values": [{"value": 0}]},
                ]
            }
        if url.endswith("/media"):
            return {
                "data": [
                    {
                        "id": "ig-post-1",
                        "caption": "Hallo Red Rock",
                        "media_type": "IMAGE",
                        "media_product_type": "FEED",
                        "permalink": "https://instagram.com/p/abc",
                        "timestamp": "2026-10-02T10:00:00+0000",
                        "media_url": "https://cdn.example/img.jpg",
                        "like_count": 3,
                        "comments_count": 0,
                    }
                ]
            }
        if url.endswith("/published_posts") or "/published_posts?" in url:
            state["fb_attempts"] += 1
            limit = str((params or {}).get("limit") or "")
            fields = str((params or {}).get("fields") or "")
            # First attempt with larger page size is rejected like live Meta.
            if state["fb_attempts"] == 1 and limit == "10":
                raise MetaConnectError(
                    "Please reduce the amount of data you're asking for, then retry your request"
                )
            assert "likes.summary" in fields
            assert "comments.summary" in fields
            assert "shares" in fields
            return {
                "data": [
                    {
                        "id": f"{state['page']}_99",
                        "message": "Facebook tekst",
                        "created_time": "2026-10-03T12:00:00+0000",
                        "permalink_url": "https://facebook.com/posts/99",
                        "status_type": "added_photos",
                        "full_picture": "https://cdn.example/photo.jpg",
                        "likes": {"summary": {"total_count": 5}},
                        "comments": {"summary": {"total_count": 2}},
                        "shares": {"count": 1},
                    }
                ]
            }
        raise MetaConnectError("Onverwacht adres.")

    monkeypatch.setattr("maaike.post_fetch.graph_get", get_json)
    created = api.post("/api/clients", json={"name": "Klant Reduce"}).json()
    _connect(created["id"], page_token="page-token-a", page_id="page-a", ig_id="ig-a")
    result = api.post(f"/api/clients/{created['id']}/posts/fetch")
    assert result.status_code == 200
    body = result.json()
    assert state["fb_attempts"] >= 2
    facebook = next(post for post in body["posts"] if post["cells"]["Platform"] == "Facebook")
    assert facebook["cells"]["Likes"] == "5"
    assert facebook["cells"]["Comments"] == "2"
    assert "reduce" in body["fetch_message"].lower() or body["fetch_status"] in {"complete", "partial"}
    with transaction() as conn:
        assert len(list_posts(conn, created["id"])) == 2


def test_unconnected_client_does_not_fetch(api: TestClient, monkeypatch) -> None:
    called = {"count": 0}

    def fail(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("Meta werd aangeroepen")

    monkeypatch.setattr("maaike.post_fetch.graph_get", fail)
    created = api.post("/api/clients", json={"name": "Nog niet"}).json()
    denied = api.post(f"/api/clients/{created['id']}/posts/fetch")
    assert denied.status_code == 400
    assert called["count"] == 0
    assert api.get(f"/api/clients/{created['id']}/posts").json()["fetch_available"] is False
