"""Maaike's client entry: own database, separated clients, no TAOL posts."""

from __future__ import annotations

import ast
import shutil
import sqlite3
from pathlib import Path

import pytest

from maaike.config import MaaikeConfigError, database_path, project_root
from maaike.db import initialize_database, transaction
from maaike.meta_connect import (
    MetaConnectError,
    PageOption,
    PendingLogin,
    build_login_url,
    classify_access_failure,
    confirm_selected_page,
    normalize_redirect_uri,
    pages_from_accounts,
    public_failure_detail,
    readiness,
    record_failed_attempt,
    redact,
    verified_choice,
)
from maaike.presentation import (
    NOT_AVAILABLE,
    RATING_PENDING,
    editorial_changes,
    format_metric,
    format_sync_moment,
    overview_record,
)
from maaike.repository import (
    UNSET_LABEL,
    Client,
    DuplicateLegendName,
    LegendInputError,
    add_client,
    add_format,
    add_pillar,
    connection_label,
    get_client,
    latest_sync_at,
    list_clients,
    list_formats,
    list_pillars,
    list_posts,
    mark_link_failed,
    save_editorial,
    update_format,
)

REPO = project_root()
MAAIKE_FILES = [REPO / "app_maaike.py", *sorted((REPO / "maaike").glob("*.py"))]
FORBIDDEN_ROOTS = {
    "config",
    "db",
    "sync",
    "meta",
    "ai",
    "analytics",
    "search",
    "reports",
    "app",
    "requests",
    "apscheduler",
}


def _stat(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    info = path.stat()
    return info.st_mtime_ns, info.st_size


def _use_db(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(path))
    monkeypatch.setenv("DATABASE_PATH", str(REPO / "data" / "social_search.db"))


def _insert_post(conn: sqlite3.Connection, client_id: int, **overrides: object) -> int:
    values = {
        "client_id": client_id,
        "platform": "instagram",
        "external_id": "ig-1",
        "published_at": "2026-10-05T08:30:00+00:00",
        "content_kind": "reel",
        "permalink": "https://instagram.com/p/example",
        "views": None,
        "likes": 0,
        "comments": None,
        "shares": None,
        "saves": None,
        "clicks": None,
        "last_synced_at": "2026-10-16T07:00:19+00:00",
    }
    values.update(overrides)
    cursor = conn.execute(
        """
        INSERT INTO posts (
            client_id, platform, external_id, published_at, content_kind, permalink,
            views, likes, comments, shares, saves, clicks, last_synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            values["client_id"],
            values["platform"],
            values["external_id"],
            values["published_at"],
            values["content_kind"],
            values["permalink"],
            values["views"],
            values["likes"],
            values["comments"],
            values["shares"],
            values["saves"],
            values["clicks"],
            values["last_synced_at"],
        ),
    )
    return int(cursor.lastrowid)


def _red_rock_id(conn: sqlite3.Connection) -> int:
    for client in list_clients(conn):
        if client.name == "Red Rock":
            return client.client_id
    raise AssertionError("Red Rock ontbreekt")


def test_modules_do_not_import_taol_runtime_or_network() -> None:
    for path in MAAIKE_FILES:
        imported: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        forbidden = set(FORBIDDEN_ROOTS)
        if path.name == "meta_connect.py":
            forbidden.discard("requests")
        assert imported.isdisjoint(forbidden)


def test_default_path_ignores_taol_database_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAAIKE_DATABASE_PATH", raising=False)
    monkeypatch.setenv("DATABASE_PATH", "data/social_search.db")
    path = database_path()
    assert path == (REPO / "data" / "maaike_redrock.db").resolve()
    assert path.name == "maaike_redrock.db"


def test_refusing_taol_database_does_not_open_it() -> None:
    taol = REPO / "data" / "social_search.db"
    seed = REPO / "data" / "seed_social_search.db"
    before = (_stat(taol), _stat(seed))
    with pytest.raises(MaaikeConfigError):
        initialize_database(taol)
    with pytest.raises(MaaikeConfigError):
        initialize_database(seed)
    assert (_stat(taol), _stat(seed)) == before


def test_new_database_is_empty_and_leaves_taol_unchanged(tmp_path: Path) -> None:
    taol = REPO / "data" / "social_search.db"
    seed = REPO / "data" / "seed_social_search.db"
    before = (_stat(taol), _stat(seed))
    path = initialize_database(tmp_path / "maaike.db")
    assert (_stat(taol), _stat(seed)) == before
    assert path.stat().st_size < 200_000

    with transaction(path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"content_formats", "content_pillars", "posts", "post_editorial", "clients"} <= tables
        red_rock = _red_rock_id(conn)
        assert list_posts(conn, red_rock) == []
        assert latest_sync_at(conn, red_rock) is None
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
        assert get_client(conn, red_rock).meta_status == "not_connected"
    assert "accounts" not in tables
    assert "weekly_reports" not in tables
    assert "search_index" not in tables


def test_starts_without_meta_or_ai_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("maaike.config.load_dotenv", lambda *args, **kwargs: False)
    for name in (
        "META_APP_ID",
        "META_APP_SECRET",
        "META_USER_ACCESS_TOKEN",
        "META_PAGE_ID",
        "META_PAGE_ACCESS_TOKEN",
        "META_INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "AI_BASE_URL",
        "AI_API_KEY",
        "AI_MODEL",
        "DATABASE_PATH",
        "ENABLE_SCHEDULER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "maaike.db"))
    initialize_database()
    initialize_database()
    with transaction() as conn:
        red_rock = _red_rock_id(conn)
        assert list_posts(conn, red_rock) == []
        assert list_formats(conn, red_rock) == []
        assert list_pillars(conn, red_rock) == []
        assert latest_sync_at(conn, red_rock) is None


def test_legend_survives_reopen_and_rejects_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_db(monkeypatch, tmp_path / "maaike.db")
    initialize_database()
    with transaction() as conn:
        red_rock = _red_rock_id(conn)
        format_id = add_format(conn, red_rock, "  Reel B  ", "Korte video met een eerste zin")
        add_pillar(conn, red_rock, "Bewijs", "Resultaat uit een project")
    with transaction() as conn:
        formats = list_formats(conn, red_rock)
        pillars = list_pillars(conn, red_rock)
        assert [(item.item_id, item.name, item.explanation) for item in formats] == [
            (format_id, "Reel B", "Korte video met een eerste zin")
        ]
        assert pillars[0].name == "Bewijs"
        update_format(conn, red_rock, format_id, "Reel B1", "Aangepaste uitleg")
    with transaction() as conn:
        stored = list_formats(conn, red_rock)[0]
        assert stored.name == "Reel B1"
        assert stored.explanation == "Aangepaste uitleg"
        with pytest.raises(DuplicateLegendName):
            add_format(conn, red_rock, "reel b1", "zelfde naam")
        with pytest.raises(LegendInputError):
            add_pillar(conn, red_rock, "   ", "zonder naam")
        with pytest.raises(LegendInputError):
            add_format(conn, red_rock, UNSET_LABEL, "gereserveerd")


def test_missing_metrics_stay_unavailable_and_editorial_persists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_db(monkeypatch, tmp_path / "maaike.db")
    initialize_database()
    with transaction() as conn:
        red_rock = _red_rock_id(conn)
        format_id = add_format(conn, red_rock, "Carrousel", "Meerdere beelden")
        pillar_id = add_pillar(conn, red_rock, "Proces", "Hoe het gemaakt is")
        post_id = _insert_post(conn, red_rock)
        save_editorial(
            conn,
            red_rock,
            post_id=post_id,
            format_id=format_id,
            pillar_id=pillar_id,
            hook="  Kijk hoe dit ontstaat  ",
        )

    with transaction() as conn:
        post = list_posts(conn, red_rock)[0]
        assert latest_sync_at(conn, red_rock) == "2026-10-16T07:00:19+00:00"

    record = overview_record(post)
    assert record["Maand"] == "October 2026"
    assert record["Publicatiedatum"] == "05-10-2026"
    assert record["Platform"] == "Instagram"
    assert record["Contentsoort"] == "Reel"
    assert record["Contentformat"] == "Carrousel"
    assert record["Post-URL"] == "https://instagram.com/p/example"
    assert record["Contentpijler"] == "Proces"
    assert record["Hook"] == "Kijk hoe dit ontstaat"
    assert record["Likes"] == "0"
    assert record["Weergaven"] == NOT_AVAILABLE
    assert record["Comments"] == NOT_AVAILABLE
    assert record["Shares"] == NOT_AVAILABLE
    assert record["Saves"] == NOT_AVAILABLE
    assert record["Clicks"] == NOT_AVAILABLE
    assert record["Beoordeling"] == RATING_PENDING
    assert record["Insight"] == ""
    assert record["Actie"] == ""
    assert format_metric(0) == "0"
    assert format_metric(None) == NOT_AVAILABLE
    assert format_sync_moment("2026-10-16T07:00:19+00:00") == "16-10-2026 09:00"
    assert format_sync_moment(None) == NOT_AVAILABLE

    edited = dict(record)
    edited["Contentformat"] = UNSET_LABEL
    edited["Contentpijler"] = "Proces"
    edited["Hook"] = "Nieuwe eerste zin"
    edited["Weergaven"] = "999999"
    edited["Beoordeling"] = "goed"
    edited["Insight"] = "verzonnen"
    changes = editorial_changes(
        [post.post_id],
        [record],
        [edited],
        format_ids={"Carrousel": format_id},
        pillar_ids={"Proces": pillar_id},
    )
    assert len(changes) == 1
    assert changes[0].format_id is None
    assert changes[0].pillar_id == pillar_id
    assert changes[0].hook == "Nieuwe eerste zin"

    with transaction() as conn:
        save_editorial(
            conn,
            red_rock,
            post_id=changes[0].post_id,
            format_id=changes[0].format_id,
            pillar_id=changes[0].pillar_id,
            hook=changes[0].hook,
        )
    with transaction() as conn:
        stored = list_posts(conn, red_rock)[0]
        assert stored.views is None
        assert stored.likes == 0
        assert stored.clicks is None
        assert stored.format_id is None
        assert stored.pillar_name == "Proces"
        assert stored.hook == "Nieuwe eerste zin"
        again = overview_record(stored)
    assert again["Beoordeling"] == RATING_PENDING
    assert again["Insight"] == ""
    assert again["Actie"] == ""
    assert again["Weergaven"] == NOT_AVAILABLE


def test_midnight_utc_uses_amsterdam_date() -> None:
    from maaike.repository import StoredPost

    post = StoredPost(
        post_id=1,
        platform="facebook",
        published_at="2026-10-31T23:30:00+00:00",
        content_kind=None,
        permalink=None,
        views=None,
        likes=None,
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
    )
    record = overview_record(post)
    assert record["Maand"] == "November 2026"
    assert record["Publicatiedatum"] == "01-11-2026"
    assert record["Platform"] == "Facebook"
    assert record["Contentsoort"] == NOT_AVAILABLE
    assert record["Post-URL"] == NOT_AVAILABLE
    assert record["Contentformat"] == UNSET_LABEL


def test_unknown_legend_choice_is_rejected() -> None:
    with pytest.raises(ValueError, match="contentformat"):
        editorial_changes(
            [1],
            [{"Contentformat": UNSET_LABEL, "Contentpijler": UNSET_LABEL, "Hook": ""}],
            [{"Contentformat": "Bestaat niet", "Contentpijler": UNSET_LABEL, "Hook": ""}],
            format_ids={},
            pillar_ids={},
        )


def test_taol_app_still_imports() -> None:
    import app

    assert callable(app.main)


def test_clients_do_not_share_legend_or_post_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_db(monkeypatch, tmp_path / "maaike.db")
    initialize_database()
    with transaction() as conn:
        client_a = add_client(conn, "Klant A")
        client_b = add_client(conn, "Klant B")
        format_a = add_format(conn, client_a, "Alleen A", "Uitleg A")
        pillar_a = add_pillar(conn, client_a, "Pijler A", "Uitleg pijler")
        post_a = _insert_post(conn, client_a, external_id="post-a")
        post_b = _insert_post(conn, client_b, external_id="post-b")
        save_editorial(
            conn,
            client_a,
            post_id=post_a,
            format_id=format_a,
            pillar_id=pillar_a,
            hook="Haak A",
        )
    with transaction() as conn:
        assert [item.name for item in list_formats(conn, client_b)] == []
        assert [item.name for item in list_pillars(conn, client_b)] == []
        assert list_posts(conn, client_b)[0].hook == ""
        assert list_posts(conn, client_b)[0].format_name is None
        assert list_posts(conn, client_a)[0].hook == "Haak A"
        assert list_posts(conn, client_a)[0].format_name == "Alleen A"
        with pytest.raises(LegendInputError):
            save_editorial(conn, client_b, post_id=post_a, format_id=None, pillar_id=None, hook="lek")
        with pytest.raises(LegendInputError):
            save_editorial(conn, client_b, post_id=post_b, format_id=format_a, pillar_id=None, hook="lek")
        with pytest.raises(LegendInputError):
            update_format(conn, client_b, format_a, "Gewijzigd", "nee")
        add_format(conn, client_b, "Alleen A", "Zelfde naam mag bij een andere klant")
    with transaction() as conn:
        assert list_posts(conn, client_b)[0].hook == ""
        assert [item.name for item in list_formats(conn, client_a)] == ["Alleen A"]
        assert [item.explanation for item in list_formats(conn, client_b)] == [
            "Zelfde naam mag bij een andere klant"
        ]


def test_legacy_rows_move_to_red_rock_and_drop_only_unused_test_items(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE content_formats (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE,
            explanation TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE content_pillars (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE,
            explanation TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY,
            platform TEXT NOT NULL,
            external_id TEXT NOT NULL,
            published_at TEXT NOT NULL,
            content_kind TEXT,
            permalink TEXT,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            shares INTEGER,
            saves INTEGER,
            clicks INTEGER,
            last_synced_at TEXT,
            UNIQUE(platform, external_id)
        );
        CREATE TABLE post_editorial (
            post_id INTEGER PRIMARY KEY,
            format_id INTEGER,
            pillar_id INTEGER,
            hook TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        """
    )
    now = "2026-10-27T12:00:00+00:00"
    conn.execute(
        "INSERT INTO content_formats (name, explanation, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("Reel B1", "Korte video die opent met een eerste zin. Aanvulling na herstart.", now, now),
    )
    conn.execute(
        "INSERT INTO content_formats (name, explanation, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("Carrousel", "Meerdere beelden", now, now),
    )
    used_pillar = conn.execute(
        "INSERT INTO content_pillars (name, explanation, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("Bewijs", "Resultaat dat de klant kan laten zien.", now, now),
    )
    pillar_id = int(used_pillar.lastrowid)
    conn.execute(
        "INSERT INTO content_pillars (name, explanation, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("Bewijs houden", "Een andere uitleg", now, now),
    )
    conn.execute(
        """
        INSERT INTO posts (platform, external_id, published_at)
        VALUES ('instagram', 'ig-kept', '2026-10-01T00:00:00+00:00')
        """
    )
    post_id = int(conn.execute("SELECT id FROM posts").fetchone()[0])
    conn.execute(
        """
        INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at)
        VALUES (?, NULL, ?, 'blijft', ?)
        """,
        (post_id, pillar_id, now),
    )
    conn.commit()
    conn.close()

    initialize_database(path)
    with transaction(path) as migrated:
        red_rock = _red_rock_id(migrated)
        formats = [item.name for item in list_formats(migrated, red_rock)]
        pillars = list_pillars(migrated, red_rock)
        assert formats == ["Carrousel"]
        assert "Bewijs houden" in [item.name for item in pillars]
        used = [item for item in pillars if item.name == "Bewijs"]
        assert len(used) == 1
        assert used[0].explanation == "Resultaat dat de klant kan laten zien."
        assert list_posts(migrated, red_rock)[0].hook == "blijft"
        assert list_posts(migrated, red_rock)[0].pillar_name == "Bewijs"
        assert get_client(migrated, red_rock).meta_status == "not_connected"


def test_real_maaike_file_keeps_only_client_data(tmp_path: Path) -> None:
    source = REPO / "data" / "maaike_redrock.db"
    if not source.exists():
        pytest.skip("geen lokale Maaike-database")
    taol = REPO / "data" / "social_search.db"
    before = _stat(taol)
    before_source = _stat(source)
    target = tmp_path / "copy.db"
    shutil.copy(source, target)
    initialize_database(target)
    assert _stat(source) == before_source
    assert _stat(taol) == before
    with transaction(target) as conn:
        red_rock = get_client(conn, _red_rock_id(conn))
        assert red_rock is not None
        assert red_rock.name == "Red Rock"
        explanations = [item.explanation for item in list_formats(conn, red_rock.client_id)]
        pillar_notes = [item.explanation for item in list_pillars(conn, red_rock.client_id)]
        assert "Korte video die opent met een eerste zin. Aanvulling na herstart." not in explanations
        assert "Resultaat dat de klant kan laten zien." not in pillar_notes
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


def test_connected_label_requires_a_verified_timestamp() -> None:
    bare = Client(
        client_id=1,
        name="X",
        meta_status="connected",
        meta_status_detail=None,
        meta_page_name="Pagina",
        meta_ig_username="studio",
        meta_connected_at=None,
        meta_token_expires_at=None,
        meta_last_checked_at=None,
    )
    checked = Client(
        client_id=1,
        name="X",
        meta_status="connected",
        meta_status_detail=None,
        meta_page_name="Pagina",
        meta_ig_username="studio",
        meta_connected_at="2026-10-27T12:00:00+00:00",
        meta_token_expires_at=None,
        meta_last_checked_at=None,
    )
    assert connection_label(bare) == "Not connected"
    assert connection_label(checked) == "Connected to Pagina (@studio)"


def test_login_url_hides_the_secret_and_missing_config_cannot_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("maaike.meta_connect.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("META_APP_ID", "9000000000000001")
    monkeypatch.setenv("META_APP_SECRET", "taol-secret-value")
    monkeypatch.setenv("MAAIKE_META_APP_ID", "1234567890123456")
    monkeypatch.setenv("MAAIKE_META_APP_SECRET", "super-secret-value")
    monkeypatch.setenv("MAAIKE_META_GRAPH_API_VERSION", "v25.0")
    monkeypatch.delenv("MAAIKE_META_LOGIN_CONFIG_ID", raising=False)
    url = build_login_url(redirect_uri="http://127.0.0.1:8502/?code=abc", state="7.nonce")
    assert "super-secret-value" not in url
    assert "taol-secret-value" not in url
    assert "9000000000000001" not in url
    assert "client_id=1234567890123456" in url
    assert "client_secret" not in url
    assert "response_type=code" in url
    assert "pages_show_list" in url
    assert "instagram_manage_insights" in url
    assert "read_insights" in url
    assert "code=abc" not in url
    monkeypatch.setenv("MAAIKE_META_LOGIN_CONFIG_ID", "999")
    configured = build_login_url(redirect_uri="http://127.0.0.1:8502/", state="7.nonce")
    assert "config_id=999" in configured
    assert "scope=" not in configured
    assert "super-secret-value" not in configured
    monkeypatch.delenv("MAAIKE_META_APP_ID", raising=False)
    monkeypatch.delenv("MAAIKE_META_APP_SECRET", raising=False)
    ready = readiness("http://127.0.0.1:8502/")
    assert ready.ready is False
    with pytest.raises(MetaConnectError):
        build_login_url(redirect_uri="http://127.0.0.1:8502/", state="1.x")


def test_redirect_and_errors_do_not_keep_secrets() -> None:
    assert normalize_redirect_uri("http://127.0.0.1:8502/?code=abc&state=1") == "http://127.0.0.1:8502/"
    hidden = redact(
        "mislukt access_token=EAABzzzz&client_secret=super-secret-value",
        "super-secret-value",
    )
    assert "super-secret-value" not in hidden
    assert "EAABzzzz" not in hidden
    assert classify_access_failure(190, "The session is invalid because the user logged out.") == "revoked"
    assert classify_access_failure(190, "Error validating access token.") == "expired"
    assert public_failure_detail("expired", "access_token=EAABzzzz") == "De toegang is verlopen. Koppel opnieuw."
    options = pages_from_accounts(
        [
            {
                "id": "1",
                "name": "Met IG",
                "access_token": "page-token",
                "instagram_business_account": {"id": "9", "username": "studio"},
            },
            {"id": "2", "name": "Zonder IG", "access_token": "other-token"},
            {"id": "3", "name": "Zonder token"},
        ]
    )
    assert [page.page_name for page in options] == ["Met IG", "Zonder IG"]
    assert options[0].selectable is True
    assert options[1].selectable is False
    assert "page-token" not in repr(options[0])


def test_page_is_stored_only_after_a_matching_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_db(monkeypatch, tmp_path / "maaike.db")
    initialize_database()
    option = PageOption("p1", "Pagina", "ig1", "studio", "page-token")
    pending = PendingLogin("user-token", None, (option,))
    with transaction() as conn:
        client_id = _red_rock_id(conn)

    monkeypatch.setattr(
        "maaike.meta_connect._get_json",
        lambda *args, **kwargs: {"id": "p1", "name": "Pagina"},
    )
    with pytest.raises(MetaConnectError):
        with transaction() as conn:
            confirm_selected_page(conn, client_id, pending, option)
    with transaction() as conn:
        client = get_client(conn, client_id)
        assert client is not None
        assert connection_label(client) == "Not connected"
        assert conn.execute("SELECT COUNT(*) FROM client_meta_secrets").fetchone()[0] == 0
        with pytest.raises(ValueError):
            mark_link_failed(conn, client_id, status="connected", detail="nee")

    monkeypatch.setattr(
        "maaike.meta_connect._get_json",
        lambda *args, **kwargs: {
            "id": "p1",
            "name": "Pagina",
            "instagram_business_account": {"id": "ig1", "username": "studio"},
        },
    )
    with transaction() as conn:
        assert confirm_selected_page(conn, client_id, pending, option) == "Pagina"
    with transaction() as conn:
        client = get_client(conn, client_id)
        assert client is not None
        assert connection_label(client) == "Connected to Pagina (@studio)"
        assert "page-token" not in repr(client)
        assert "user-token" not in repr(client)
        record_failed_attempt(
            conn,
            client_id,
            MetaConnectError("temporary", code=190),
            replace_verified=False,
        )
    with transaction() as conn:
        client = get_client(conn, client_id)
        assert client is not None
        assert connection_label(client) == "Connected to Pagina (@studio)"
        record_failed_attempt(
            conn,
            client_id,
            MetaConnectError("The user has not authorized application.", code=190),
            replace_verified=True,
        )
    with transaction() as conn:
        client = get_client(conn, client_id)
        assert client is not None
        assert client.meta_status == "revoked"
        assert connection_label(client) == "Access revoked"
        assert conn.execute("SELECT COUNT(*) FROM client_meta_secrets").fetchone()[0] == 0
        assert "page-token" not in (client.meta_status_detail or "")


def test_screens_do_not_mention_tokens() -> None:
    for relative in ("maaike/ui.py", "maaike/presentation.py"):
        text = (REPO / relative).read_text(encoding="utf-8")
        assert "access_token" not in text
        assert "client_secret" not in text
        assert "load_page_secret" not in text


def test_verified_choice_rejects_a_different_instagram_account() -> None:
    option = PageOption("p1", "Pagina", "ig1", "studio", "page-token")
    with pytest.raises(MetaConnectError):
        verified_choice(
            {"id": "p1", "name": "Pagina", "instagram_business_account": {"id": "other", "username": "x"}},
            option,
        )
