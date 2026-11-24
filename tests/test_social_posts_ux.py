"""Tests for Socialmediaberichten improvements (points 16–20):
- Truthful Facebook/Instagram connection & fetch status messages
- Weekly post check (open posts, checklist, responsible person, completion, durable export/import)
- Strict separation of own client figures vs. crawled competitor posts in Alle berichten & Resultaten
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maaike.comparison_service import save_competitors
from maaike.data_transfer import apply_import, export_package
from maaike.db import transaction
from maaike.repository import add_client, add_format, add_pillar, save_verified_link
from maaike_web.app import create_app
from maaike_web.session import clear_store


@pytest.fixture
def http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clear_store()
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "social_posts_ux.db"))
    monkeypatch.setenv("MAAIKE_SESSION_SECRET", "test-session-secret-social")
    monkeypatch.setenv("MAAIKE_FRONTEND_URL", "http://127.0.0.1:5173")
    monkeypatch.setenv("MAAIKE_BACKEND_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("MAAIKE_WEB_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/meta/callback")
    monkeypatch.delenv("MAAIKE_PERSIST_ENABLED", raising=False)
    with TestClient(create_app()) as client:
        yield client
    clear_store()


def test_channel_status_three_client_states(http: TestClient) -> None:
    with transaction() as conn:
        unlinked_id = add_client(conn, "BBQube Zonder Koppeling")
        linked_empty_id = add_client(conn, "BBQube Gekoppeld Leeg")
        save_verified_link(
            conn,
            linked_empty_id,
            page_id="page-empty-1",
            page_name="BBQube Leeg Pagina",
            ig_user_id="ig-empty-1",
            ig_username="bbqube_leeg",
            user_token="tok-u",
            page_token="tok-p",
            user_expires_at="2026-12-31T00:00:00+00:00",
        )
        linked_with_posts_id = add_client(conn, "BBQube Actief")
        save_verified_link(
            conn,
            linked_with_posts_id,
            page_id="page-bbq-1",
            page_name="BBQube Nederland",
            ig_user_id="ig-bbq-1",
            ig_username="bbqube_nl",
            user_token="tok-u2",
            page_token="tok-p2",
            user_expires_at="2026-12-31T00:00:00+00:00",
        )
        conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, caption, permalink,
                account_name, views, likes, comments, saves, shares, last_synced_at, source_origin
            ) VALUES (?, 'instagram', 'own-1', '2026-11-10T10:00:00+00:00',
                      'Rooktips voor het weekend op de BBQube!', 'https://instagram.com/p/own1',
                      '@bbqube_nl', 2400, 145, 19, 34, 11, '2026-11-20T09:30:00+00:00', 'meta_api')
            """,
            (linked_with_posts_id,),
        )
        conn.execute(
            "UPDATE clients SET last_fetch_at = '2026-11-20T09:30:00+00:00', last_fetch_status = 'ok' WHERE id = ?",
            (linked_with_posts_id,),
        )

    # 1. Klant zonder koppeling
    r1 = http.get(f"/api/clients/{unlinked_id}/posts").json()["channel_status"]
    assert r1["state"] == "connect_required"
    assert r1["headline"] == "Koppel eerst je accounts"
    assert r1["facebook"]["connected"] is False
    assert r1["instagram"]["connected"] is False
    assert r1["last_fetched_label"] == "Nog nooit opgehaald"

    # 2. Gekoppelde klant zonder opgehaalde berichten
    r2 = http.get(f"/api/clients/{linked_empty_id}/posts").json()["channel_status"]
    assert r2["state"] == "fetch_first_posts"
    assert r2["headline"] == "Haal je eerste berichten op"
    assert r2["facebook"]["connected"] is True
    assert "BBQube Leeg Pagina" in r2["facebook"]["label"]
    assert r2["instagram"]["connected"] is True
    assert "@bbqube_leeg" in r2["instagram"]["label"]
    assert r2["last_fetched_label"] == "Nog nooit opgehaald"

    # 3. Gekoppelde klant met opgehaalde berichten
    r3 = http.get(f"/api/clients/{linked_with_posts_id}/posts").json()["channel_status"]
    assert r3["state"] == "ready_to_view"
    assert r3["headline"] == "Je berichten zijn klaar om te bekijken"
    assert r3["own_post_count"] == 1
    assert r3["has_fetched"] is True
    assert r3["last_fetched_label"] != "Nog nooit opgehaald"


def test_competitor_posts_never_leak_into_client_posts_or_results(http: TestClient) -> None:
    with transaction() as conn:
        bbq_id = add_client(conn, "BBQube")
        save_verified_link(
            conn,
            bbq_id,
            page_id="page-bbq",
            page_name="BBQube Official",
            ig_user_id="ig-bbq",
            ig_username="bbqube",
            user_token="u-tok",
            page_token="p-tok",
            user_expires_at=None,
        )
        save_competitors(
            conn,
            bbq_id,
            ["weberbenelux", "kamadojoe"],
        )
        # Own post with modest figures
        conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, caption, permalink,
                account_name, views, likes, comments, saves, shares, last_synced_at, source_origin
            ) VALUES (?, 'instagram', 'bbq-own-1', '2026-11-12T12:00:00+00:00',
                      'Onze eigen BBQube buitenkeuken in actie', 'https://instagram.com/p/bbq1',
                      '@bbqube', 1800, 120, 14, 22, 6, '2026-11-23T08:00:00+00:00', 'meta_api')
            """,
            (bbq_id,),
        )
        # Competitor post stored via business_discovery crawl with huge likes
        conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, caption, permalink,
                account_name, views, likes, comments, saves, shares, last_synced_at, source_origin
            ) VALUES (?, 'instagram', 'bd:weberbenelux:999', '2026-11-14T15:00:00+00:00',
                      'Weber wintergrill actie van concurrent', 'https://instagram.com/p/weber999',
                      '@weberbenelux', 95000, 8400, 410, 900, 120, '2026-11-23T09:00:00+00:00',
                      'business_discovery:weberbenelux')
            """,
            (bbq_id,),
        )
        # Legacy competitor row without source_origin but matching configured competitor handle
        conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, caption, permalink,
                account_name, views, likes, comments, saves, shares, last_synced_at
            ) VALUES (?, 'instagram', 'legacy-kamado-1', '2026-11-15T15:00:00+00:00',
                      'Kamado Joe keramische grill post', 'https://instagram.com/p/kj1',
                      '@kamadojoe', 50000, 4200, 210, 300, 80, '2026-11-23T09:00:00+00:00')
            """,
            (bbq_id,),
        )

    posts_res = http.get(f"/api/clients/{bbq_id}/posts").json()
    assert len(posts_res["posts"]) == 1
    assert posts_res["posts"][0]["caption"] == "Onze eigen BBQube buitenkeuken in actie"

    totals_res = http.get(f"/api/clients/{bbq_id}/sync-totals").json()
    assert totals_res["instagram_posts"] == 1

    perf_res = http.get(f"/api/clients/{bbq_id}/performance?year=2026&month=11").json()
    assert perf_res["post_count"] == 1
    likes_section = next(s for s in perf_res["sections"] if s["metric"] == "likes")
    assert len(likes_section["posts"]) == 1
    assert likes_section["posts"][0]["metric_value"] == 120
    for section in perf_res["sections"]:
        for p in section["posts"]:
            assert "weber" not in (p.get("caption") or "").lower()
            assert "kamado" not in (p.get("caption") or "").lower()

    # Meanwhile, Competitors page still has the configured competitors
    cmp_res = http.get(f"/api/clients/{bbq_id}/comparison").json()
    assert set(cmp_res["competitors"]) == {"weberbenelux", "kamadojoe"}


def test_weekly_check_unchecked_posts_responsible_and_completion_persist(
    http: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today_iso = date.today().isoformat()
    with transaction() as conn:
        bbq_id = add_client(conn, "BBQube Weekcheck")
        fmt_id = add_format(conn, bbq_id, "Reel", "Korte grillvideo")
        pil_id = add_pillar(conn, bbq_id, "Inspiratie", "Recepten & vuurbeleving")
        cur = conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, caption, permalink,
                account_name, likes, comments, last_synced_at
            ) VALUES (?, 'instagram', 'wk-1', ?, 'Traag gegaarde brisket op eikenhout', 'https://instagram.com/p/wk1',
                      '@bbqube', 88, 9, ?)
            """,
            (bbq_id, f"{today_iso}T10:00:00+00:00", f"{today_iso}T11:00:00+00:00"),
        )
        post_id = int(cur.lastrowid)

    # Initially 1 unchecked post and no responsible set
    plan0 = http.get(f"/api/clients/{bbq_id}/logs/weekly-plan").json()["weekly_plan"]
    assert plan0["posts_in_window_count"] == 1
    assert plan0["unchecked_in_window_count"] == 1
    assert plan0["has_responsible"] is False
    assert set(plan0["unchecked_posts"][0]["missing_labels"]) == {
        "Contentformat",
        "Contentpijler",
        "Hook",
    }

    # Save weekly plan with responsible person "Jet"
    plan1 = http.put(
        f"/api/clients/{bbq_id}/logs/weekly-plan",
        json={
            "enabled": True,
            "weekday": 1,
            "time": "10:00",
            "responsible_name": "Jet",
            "note": "Elke dinsdag nieuwe BBQube-posts nalopen",
        },
    ).json()["weekly_plan"]
    assert plan1["has_responsible"] is True
    assert plan1["responsible_name"] == "Jet"

    # Fill format, pillar & hook -> unchecked count drops to 0
    patch_res = http.patch(
        f"/api/clients/{bbq_id}/posts/{post_id}",
        json={
            "format_id": fmt_id if isinstance(fmt_id, int) else fmt_id.item_id,
            "pillar_id": pil_id if isinstance(pil_id, int) else pil_id.item_id,
            "hook": "Zo krijg je een perfecte rookring op je brisket",
            "figma_url": "",
        },
    )
    assert patch_res.status_code == 200

    plan2 = http.get(f"/api/clients/{bbq_id}/logs/weekly-plan").json()["weekly_plan"]
    assert plan2["unchecked_in_window_count"] == 0
    assert plan2["checked_in_window_count"] == 1

    # Complete weekly check
    completed = http.post(
        f"/api/clients/{bbq_id}/logs/weekly-plan/complete",
        json={},
    ).json()["weekly_plan"]
    assert completed["last_completed_at"] is not None
    assert completed["last_completed_by"] == "Jet"
    assert completed["last_completed_count"] == 1

    # Verify durable export/import preserves weekly plan + completion
    with transaction() as conn:
        pkg = export_package(conn, client_id=bbq_id)

    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(tmp_path / "restored_social.db"))
    with TestClient(create_app()):
        with transaction() as conn2:
            apply_import(conn2, json.loads(json.dumps(pkg)), overwrite=True)
            row = conn2.execute(
                "SELECT responsible_name, last_completed_by, last_completed_count FROM client_logs_weekly_preferences"
            ).fetchone()
            assert row is not None
            assert row["responsible_name"] == "Jet"
            assert row["last_completed_by"] == "Jet"
            assert row["last_completed_count"] == 1
