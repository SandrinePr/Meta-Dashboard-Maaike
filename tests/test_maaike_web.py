"""API checks for the React/FastAPI Maaike app. Uses a temporary database."""

from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi.testclient import TestClient

from maaike.config import project_root
from maaike.db import transaction
from maaike.meta_connect import PageOption, PendingLogin
from maaike.repository import list_formats, list_posts
from maaike_web.app import create_app
from maaike_web.session import clear_store

REPO = project_root()
TAOL = REPO / "data" / "social_search.db"
MAAIKE = REPO / "data" / "maaike_redrock.db"


def _stat(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    info = path.stat()
    return info.st_mtime_ns, info.st_size


TAOL_BEFORE = _stat(TAOL)
MAAIKE_BEFORE = _stat(MAAIKE)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clear_store()
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "maaike.db"))
    monkeypatch.setenv("DATABASE_PATH", str(TAOL))
    monkeypatch.setenv("MAAIKE_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("MAAIKE_FRONTEND_URL", "http://127.0.0.1:5173")
    monkeypatch.setenv("MAAIKE_BACKEND_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("MAAIKE_WEB_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/meta/callback")
    monkeypatch.delenv("MAAIKE_CORS_ORIGINS", raising=False)
    with TestClient(create_app()) as client:
        yield client
    clear_store()


def _insert_post(client_id: int) -> int:
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, content_kind, permalink,
                views, likes, comments, shares, saves, clicks, last_synced_at
            ) VALUES (?, 'instagram', 'ig-1', '2026-10-05T08:30:00+00:00', 'reel',
                      'https://instagram.com/p/example', NULL, 0, NULL, NULL, NULL, NULL,
                      '2026-10-16T07:00:19+00:00')
            """,
            (client_id,),
        )
        return int(cursor.lastrowid)


def test_web_package_does_not_import_streamlit_or_taol() -> None:
    forbidden = {"streamlit", "app", "db", "sync", "meta", "ai", "analytics"}
    for path in (REPO / "maaike_web").glob("*.py"):
        imported: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported.isdisjoint(forbidden)


def test_frontend_source_does_not_mention_secrets() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in (REPO / "frontend" / "src").rglob("*") if path.is_file())
    assert "client_secret" not in text
    assert "access_token" not in text
    assert "MAAIKE_SESSION_SECRET" not in text
    assert "page_token" not in text


def _stop_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a test from reading the real .env after a variable is removed."""
    for target in (
        "dotenv.load_dotenv",
        "maaike.config.load_dotenv",
        "maaike.meta_connect.load_dotenv",
        "maaike_web.settings.load_dotenv",
    ):
        monkeypatch.setattr(target, lambda *args, **kwargs: False)


def test_starts_without_meta_or_ai_keys(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _stop_dotenv(monkeypatch)
    for name in (
        "META_APP_ID",
        "META_APP_SECRET",
        "META_USER_ACCESS_TOKEN",
        "AI_API_KEY",
        "MAAIKE_META_APP_ID",
        "MAAIKE_META_APP_SECRET",
        "MAAIKE_META_LOGIN_CONFIG_ID",
        "CLAUDE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    health = api.get("/api/health")
    assert health.status_code == 200
    created = api.post("/api/clients", json={"name": "Zonder sleutels"})
    assert created.status_code == 201
    meta = api.get(f"/api/clients/{created.json()['id']}/meta")
    assert meta.status_code == 200
    body = meta.json()
    assert body["connected"] is False
    assert body["status_label"] == "Not connected"
    assert body["ready"] is False
    assert "super-secret-value" not in meta.text


def test_clients_legend_and_posts_stay_with_the_right_client(api: TestClient) -> None:
    client_a = api.post("/api/clients", json={"name": "Klant A"}).json()
    client_b = api.post("/api/clients", json={"name": "Klant B"}).json()
    assert api.patch(f"/api/clients/{client_a['id']}", json={"name": "Klant A2"}).status_code == 200
    created = api.post(
        f"/api/clients/{client_a['id']}/formats",
        json={"name": "Alleen A", "explanation": "Uitleg A"},
    )
    assert created.status_code == 201
    pillar = api.post(
        f"/api/clients/{client_a['id']}/pillars",
        json={"name": "Pijler A", "explanation": "Uitleg pijler"},
    )
    assert pillar.status_code == 201
    legend_b = api.get(f"/api/clients/{client_b['id']}/legend").json()
    assert legend_b["formats"] == []
    assert legend_b["pillars"] == []
    format_id = api.get(f"/api/clients/{client_a['id']}/legend").json()["formats"][0]["id"]
    pillar_id = api.get(f"/api/clients/{client_a['id']}/legend").json()["pillars"][0]["id"]
    denied = api.patch(
        f"/api/clients/{client_b['id']}/formats/{format_id}",
        json={"name": "Gewijzigd", "explanation": "nee"},
    )
    assert denied.status_code == 400
    assert api.get(f"/api/clients/{client_a['id']}/legend").json()["formats"][0]["name"] == "Alleen A"

    post_id = _insert_post(client_a["id"])
    post_b = _insert_post(client_b["id"])
    saved = api.patch(
        f"/api/clients/{client_a['id']}/posts/{post_id}",
        json={"format_id": format_id, "pillar_id": pillar_id, "hook": "Haak A", "views": 999999},
    )
    assert saved.status_code == 200
    leaked = api.patch(
        f"/api/clients/{client_b['id']}/posts/{post_id}",
        json={"format_id": None, "pillar_id": None, "hook": "lek"},
    )
    assert leaked.status_code == 400
    other_format = api.patch(
        f"/api/clients/{client_b['id']}/posts/{post_b}",
        json={"format_id": format_id, "pillar_id": pillar_id, "hook": "lek"},
    )
    assert other_format.status_code == 400

    overview = api.get(f"/api/clients/{client_a['id']}/posts").json()
    assert overview["posts"][0]["cells"]["Hook"] == "Haak A"
    assert overview["posts"][0]["cells"]["Contentformat"] == "Alleen A"
    assert overview["posts"][0]["cells"]["Likes"] == "0"
    assert overview["posts"][0]["cells"]["Weergaven"] == "not available"
    assert overview["posts"][0]["cells"]["Beoordeling"] == "not rated yet"
    assert overview["posts"][0]["cells"]["Insight"] == ""
    assert overview["posts"][0]["cells"]["Actie"] == ""
    assert overview["synced_at"] == "16-10-2026 09:00"
    assert overview["fetch_available"] is False
    assert overview["columns"][:4] == ["Maand", "Publicatiedatum", "Platform", "Account"]
    assert "Bereik" in overview["columns"]
    assert "Tekst" in overview["columns"]
    assert "Media" in overview["columns"]
    assert overview["fetch_available"] is False
    other_posts = api.get(f"/api/clients/{client_b['id']}/posts").json()["posts"]
    assert other_posts[0]["cells"]["Hook"] == ""
    assert other_posts[0]["cells"]["Contentformat"] == "—"
    assert "Haak A" not in api.get(f"/api/clients/{client_b['id']}/posts").text
    assert "999999" not in api.get(f"/api/clients/{client_a['id']}/posts").text

    with transaction() as conn:
        assert list_posts(conn, client_a["id"])[0].views is None
        assert list_posts(conn, client_a["id"])[0].hook == "Haak A"
        assert [item.name for item in list_formats(conn, client_b["id"])] == []


def test_values_remain_after_a_new_process(api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    created = api.post("/api/clients", json={"name": "Blijft"}).json()
    api.post(f"/api/clients/{created['id']}/formats", json={"name": "Carrousel", "explanation": "Meerdere beelden"})
    clear_store()
    with TestClient(create_app()) as again:
        names = [item["name"] for item in again.get("/api/clients").json()["clients"]]
        assert "Blijft" in names
        legend = again.get(f"/api/clients/{created['id']}/legend").json()
        assert legend["formats"][0]["name"] == "Carrousel"


def test_unverified_status_is_not_called_connected(api: TestClient) -> None:
    created = api.post("/api/clients", json={"name": "Open"}).json()
    with transaction() as conn:
        conn.execute(
            "UPDATE clients SET meta_status = 'connected', meta_page_name = 'Pagina' WHERE id = ?",
            (created["id"],),
        )
    body = api.get("/api/clients").json()
    client = next(item for item in body["clients"] if item["id"] == created["id"])
    assert client["connected"] is False
    assert client["status_label"] == "Not connected"
    assert "access_token" not in api.get("/api/clients").text


def test_meta_login_hides_secrets_and_rejects_a_reused_state(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _stop_dotenv(monkeypatch)
    monkeypatch.setenv("META_APP_ID", "9000000000000001")
    monkeypatch.setenv("META_APP_SECRET", "taol-secret-value")
    monkeypatch.setenv("META_PAGE_ACCESS_TOKEN", "taol-page-token")
    monkeypatch.setenv("MAAIKE_META_APP_ID", "1234567890123456")
    monkeypatch.setenv("MAAIKE_META_APP_SECRET", "super-secret-value")
    monkeypatch.setenv("MAAIKE_META_GRAPH_API_VERSION", "v25.0")
    monkeypatch.delenv("MAAIKE_META_LOGIN_CONFIG_ID", raising=False)
    calls = {"count": 0}

    def fake_collect(*, code: str, redirect_uri: str) -> PendingLogin:
        calls["count"] += 1
        option = PageOption("p1", "Pagina", "ig1", "studio", "page-token-secret")
        return PendingLogin("user-token-secret", None, (option,))

    monkeypatch.setattr("maaike_web.app.collect_pages", fake_collect)
    created = api.post("/api/clients", json={"name": "Meta klant"}).json()
    started = api.post(f"/api/clients/{created['id']}/meta/start", json={"popup": True})
    assert started.status_code == 200
    assert started.json()["popup"] is True
    assert "super-secret-value" not in started.text
    assert "taol-secret-value" not in started.text
    assert "9000000000000001" not in started.text
    assert "taol-page-token" not in started.text
    assert "client_secret" not in started.text
    state = parse_qs(urlparse(started.json()["login_url"]).query)["state"][0]

    # Meta → callback often omits the session cookie. State still binds to the armed session.
    api.cookies.clear()
    returned = api.get(f"/api/meta/callback?code=one-time-code&state={state}", follow_redirects=False)
    assert returned.status_code == 302
    assert calls["count"] == 1
    assert "one-time-code" not in returned.headers["location"]
    assert "meta=choose" in returned.headers["location"]
    assert "popup=1" in returned.headers["location"]
    assert "maaike_session=" in returned.headers.get("set-cookie", "")

    again = api.get(f"/api/meta/callback?code=one-time-code&state={state}", follow_redirects=False)
    assert again.status_code == 302
    assert calls["count"] == 1
    assert "hoort niet bij deze sessie" in unquote(again.headers["location"])

    meta = api.get(f"/api/clients/{created['id']}/meta")
    assert "page-token-secret" not in meta.text
    assert "user-token-secret" not in meta.text
    assert "Pagina (@studio)" in meta.text
    assert "page-token-secret" not in meta.headers.get("set-cookie", "")

    def fake_graph(url: str, params: dict | None, *, secrets: tuple[str, ...]) -> dict:
        assert "page-token-secret" not in url
        return {
            "id": "p1",
            "name": "Pagina",
            "instagram_business_account": {"id": "ig1", "username": "studio"},
        }

    monkeypatch.setattr("maaike.meta_connect._get_json", fake_graph)
    confirmed = api.post(f"/api/clients/{created['id']}/meta/confirm", json={"page_index": 0})
    assert confirmed.status_code == 200
    assert confirmed.json()["connected"] is True
    assert "page-token-secret" not in confirmed.text
    listed = api.get("/api/clients").text
    assert "page-token-secret" not in listed
    assert "user-token-secret" not in listed
    assert "Connected to Pagina (@studio)" in listed

    with transaction() as conn:
        token = conn.execute("SELECT page_access_token FROM client_meta_secrets").fetchone()[0]
        assert token == "page-token-secret"

    posts_before = api.get(f"/api/clients/{created['id']}/posts").json()
    disconnected = api.post(f"/api/clients/{created['id']}/meta/disconnect", json={})
    assert disconnected.status_code == 200
    assert disconnected.json()["disconnected"] is True
    listed_after = api.get("/api/clients").json()["clients"]
    row = next(item for item in listed_after if item["id"] == created["id"])
    assert row["connected"] is False
    with transaction() as conn:
        secrets = conn.execute(
            "SELECT COUNT(*) n FROM client_meta_secrets WHERE client_id = ?",
            (created["id"],),
        ).fetchone()[0]
        assert secrets == 0
    posts_after = api.get(f"/api/clients/{created['id']}/posts").json()
    assert len(posts_after.get("posts") or []) == len(posts_before.get("posts") or [])


def test_meta_callback_rejects_foreign_session_cookie(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _stop_dotenv(monkeypatch)
    monkeypatch.setenv("MAAIKE_META_APP_ID", "1234567890123456")
    monkeypatch.setenv("MAAIKE_META_APP_SECRET", "super-secret-value")
    monkeypatch.setenv("MAAIKE_META_GRAPH_API_VERSION", "v25.0")
    monkeypatch.delenv("MAAIKE_META_LOGIN_CONFIG_ID", raising=False)
    calls = {"count": 0}

    def fake_collect(*, code: str, redirect_uri: str) -> PendingLogin:
        calls["count"] += 1
        option = PageOption("p1", "Pagina", "ig1", "studio", "page-token-secret")
        return PendingLogin("user-token-secret", None, (option,))

    monkeypatch.setattr("maaike_web.app.collect_pages", fake_collect)
    created = api.post("/api/clients", json={"name": "CSRF klant"}).json()
    started = api.post(f"/api/clients/{created['id']}/meta/start", json={"popup": False})
    state = parse_qs(urlparse(started.json()["login_url"]).query)["state"][0]

    from maaike_web.session import COOKIE_NAME, cookie_value, ensure_session

    other_id, other_cookie = ensure_session(None, "test-session-secret")
    assert other_cookie is not None
    api.cookies.set(COOKIE_NAME, other_cookie)
    rejected = api.get(f"/api/meta/callback?code=one-time-code&state={state}", follow_redirects=False)
    assert rejected.status_code == 302
    assert calls["count"] == 0
    assert "hoort niet bij deze sessie" in unquote(rejected.headers["location"])
    assert other_id
    assert cookie_value(other_id, "test-session-secret") == other_cookie


def test_real_databases_stay_untouched() -> None:
    assert _stat(TAOL) == TAOL_BEFORE
    assert _stat(MAAIKE) == MAAIKE_BEFORE
