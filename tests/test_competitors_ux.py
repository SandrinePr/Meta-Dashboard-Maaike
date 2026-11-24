"""Automated UX & backend contract tests for Concurrenten (points 21–25)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from maaike.competitor_scheduler import is_off_hours, pick_next_competitor
from maaike.data_transfer import apply_import, export_package
from maaike.db import initialize_database, transaction
from maaike.migrate import apply_migrations
from maaike.repository import add_client, save_verified_link
from maaike_web.app import create_app


META_CONNECT_MSG = (
    "Koppel eerst het Facebook- en Instagram-account van deze klant om berichten van concurrenten op te halen."
)


def test_competitors_points_21_to_25_and_client_isolation(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "competitors_ux.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MAAIKE_PERSIST_ENABLED", "0")
    initialize_database(db_path)

    with transaction(db_path) as conn:
        apply_migrations(conn)
        unlinked_id = add_client(conn, "Klant Zonder Koppeling")
        linked_id = add_client(conn, "BBQube Testklant")
        other_id = add_client(conn, "Tweede Klant")

        save_verified_link(
            conn,
            linked_id,
            page_id="page_bbqube",
            page_name="BBQube Nederland",
            ig_user_id="ig_bbqube",
            ig_username="bbqube_nl",
            user_token="utok_bbqube",
            page_token="ptok_bbqube",
            user_expires_at="2027-01-01T00:00:00Z",
        )
        save_verified_link(
            conn,
            other_id,
            page_id="page_other",
            page_name="Tweede Pagina",
            ig_user_id="ig_other",
            ig_username="tweede_nl",
            user_token="utok_other",
            page_token="ptok_other",
            user_expires_at="2027-01-01T00:00:00Z",
        )

    app = create_app()
    http = TestClient(app)

    # Punt 24: Klant zonder Meta-koppeling toont de exacte vervolgstap; gekoppelde klant NIET.
    unlinked_state = http.get(f"/api/clients/{unlinked_id}/comparison").json()
    assert unlinked_state["meta_connection"]["connected"] is False
    assert unlinked_state["meta_connection"]["missing_message"] == META_CONNECT_MSG
    assert unlinked_state["refresh"]["available"] is False

    # Ophalen zonder koppeling geeft exact dezelfde Nederlandse vervolgstap terug
    blocked = http.post(f"/api/clients/{unlinked_id}/comparison/competitors/refresh", json={})
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == META_CONNECT_MSG

    # Wel alvast een concurrent toevoegen bij niet-gekoppelde klant (punt 21)
    added_unlinked = http.post(
        f"/api/clients/{unlinked_id}/comparison/competitors",
        json={"name": "@voorbeeld_concurrent"},
    )
    assert added_unlinked.status_code == 200
    u_data = added_unlinked.json()
    assert u_data["competitors"] == ["voorbeeld_concurrent"]
    u_row = [r for r in u_data["account_rows"] if r["role"] == "competitor"][0]
    assert u_row["has_fetched_data"] is False
    assert u_row["posts_fetched_label"] == "Nog geen berichten opgehaald"
    assert u_row["last_succeeded_label"] == "Nog niet gelukt"
    assert u_row["action_needed"] is True
    assert "Facebook" in u_row["action_label"]

    # Gekoppelde klant heeft GEEN ontbrekende-koppelmelding (punt 24)
    linked_state = http.get(f"/api/clients/{linked_id}/comparison").json()
    assert linked_state["meta_connection"]["connected"] is True
    assert linked_state["meta_connection"]["missing_message"] is None
    assert linked_state["refresh"]["available"] is True
    assert linked_state["refresh"]["button_label"] == "Berichten van concurrenten ophalen"

    # Punt 21: Toevoegen met @gebruikersnaam op gekoppelde klant + fout bij lege invoer of duplicaat
    empty_res = http.post(f"/api/clients/{linked_id}/comparison/competitors", json={"name": " @ "})
    assert empty_res.status_code == 400
    assert "@gebruikersnaam" in empty_res.json()["detail"]

    add_1 = http.post(f"/api/clients/{linked_id}/comparison/competitors", json={"name": "@weberbenelux"})
    assert add_1.status_code == 200
    dup_res = http.post(f"/api/clients/{linked_id}/comparison/competitors", json={"name": "weberbenelux"})
    assert dup_res.status_code == 400
    assert "staat al op de lijst" in dup_res.json()["detail"]

    add_2 = http.post(f"/api/clients/{linked_id}/comparison/competitors", json={"name": "@kamadojoe"})
    assert add_2.status_code == 200
    before_fetch = add_2.json()
    comp_before = {r["username"]: r for r in before_fetch["account_rows"] if r["role"] == "competitor"}
    assert comp_before["weberbenelux"]["posts_fetched_label"] == "Nog geen berichten opgehaald"
    assert comp_before["weberbenelux"]["last_succeeded_label"] == "Nog niet gelukt"
    assert comp_before["weberbenelux"]["action_needed"] is True

    # Bestaande automatische achtergrondselectie (competitor_scheduler) blijft intact (punt 25)
    with transaction(db_path) as conn:
        nxt = pick_next_competitor(conn)
        assert nxt is not None
        assert nxt["client_id"] == linked_id
        assert nxt["username"] in {"weberbenelux", "kamadojoe"}
    assert is_off_hours() in {True, False}

    # Punt 23 & 22: Mock Business Discovery voor ophalen én opnieuw ophalen
    def fake_graph_get(url: str, params: dict, *, secrets=()):
        fields = str(params.get("fields") or "")
        if "weberbenelux" in fields:
            return {
                "business_discovery": {
                    "id": "bd_weber",
                    "username": "weberbenelux",
                    "name": "Weber Benelux",
                    "followers_count": 14800,
                    "media": {
                        "data": [
                            {
                                "id": "w_post_1",
                                "caption": "Low & slow spareribs op zondag",
                                "media_type": "VIDEO",
                                "media_product_type": "REELS",
                                "permalink": "https://instagram.com/p/w_post_1",
                                "timestamp": "2026-11-20T14:00:00+0000",
                                "like_count": 420,
                                "comments_count": 28,
                            },
                            {
                                "id": "w_post_2",
                                "caption": "Winterbarbecue tips in 5 slides",
                                "media_type": "CAROUSEL_ALBUM",
                                "permalink": "https://instagram.com/p/w_post_2",
                                "timestamp": "2026-11-22T10:30:00+0000",
                                "like_count": 310,
                                "comments_count": 16,
                            },
                        ]
                    },
                }
            }
        return {
            "business_discovery": {
                "id": "bd_kamado",
                "username": "kamadojoe",
                "name": "Kamado Joe",
                "followers_count": 92500,
                "media": {
                    "data": [
                        {
                            "id": "k_post_1",
                            "caption": "Keramisch grillen op hoge temperatuur",
                            "media_type": "IMAGE",
                            "permalink": "https://instagram.com/p/k_post_1",
                            "timestamp": "2026-11-21T16:00:00+0000",
                            "like_count": 890,
                            "comments_count": 54,
                        }
                    ]
                },
            }
        }

    monkeypatch.setattr("maaike.account_crawl.graph_get", fake_graph_get)

    refresh_res = http.post(f"/api/clients/{linked_id}/comparison/competitors/refresh", json={})
    assert refresh_res.status_code == 200
    refresh_data = refresh_res.json()
    assert len(refresh_data["crawled"]) == 2
    assert refresh_data["errors"] == []

    # Controleer bijgewerkte status per concurrent (punt 21) + prestatiecijfers
    after_fetch = http.get(f"/api/clients/{linked_id}/comparison").json()
    comp_after = {r["username"]: r for r in after_fetch["account_rows"] if r["role"] == "competitor"}
    assert comp_after["weberbenelux"]["has_fetched_data"] is True
    assert comp_after["weberbenelux"]["fetched_posts_total"] == 2
    assert "2 berichten opgehaald" in comp_after["weberbenelux"]["posts_fetched_label"]
    assert comp_after["weberbenelux"]["last_succeeded_label"] != "Nog niet gelukt"
    assert comp_after["weberbenelux"]["action_needed"] is False
    assert comp_after["weberbenelux"]["likes_avg"] == 365.0
    assert comp_after["weberbenelux"]["comments_avg"] == 22.0

    # Opnieuw ophalen voor één specifieke concurrent (punt 22)
    refetch_one = http.post(
        f"/api/clients/{linked_id}/comparison/competitors/refresh",
        json={"username": "kamadojoe", "max_accounts": 1},
    )
    assert refetch_one.status_code == 200
    assert [c["username"] for c in refetch_one.json()["crawled"]] == ["kamadojoe"]

    # Punt 22: Verwijderen verwijdert alleen de gekozen concurrent
    del_res = http.delete(f"/api/clients/{linked_id}/comparison/competitors/kamadojoe")
    assert del_res.status_code == 200
    assert del_res.json()["competitors"] == ["weberbenelux"]

    # Punt 25: Wekelijkse controle met planning, handmatig/automatisch uitleg én verantwoordelijke
    weekly_res = http.put(
        f"/api/clients/{linked_id}/comparison/weekly-plan",
        json={
            "enabled": True,
            "weekday": 1,
            "time": "09:30",
            "responsible_name": "Jet",
            "note": "Check elke dinsdag de nieuwe Reels van concurrenten",
        },
    )
    assert weekly_res.status_code == 200
    wp = weekly_res.json()["weekly_plan"]
    assert wp["enabled"] is True
    assert wp["auto_execute"] is False
    assert wp["weekday_label"] == "dinsdag"
    assert wp["time"] == "09:30"
    assert wp["has_responsible"] is True
    assert wp["responsible_name"] == "Jet"
    assert "dinsdag" in wp["schedule_summary"]
    assert len(wp["user_steps"]) >= 3

    # Klantwissel-isolatie: Tweede Klant ziet géén concurrenten van BBQube of niet-gekoppelde klant
    http.post(f"/api/clients/{other_id}/comparison/competitors", json={"name": "@andere_concurrent"})
    other_state = http.get(f"/api/clients/{other_id}/comparison").json()
    assert other_state["client_id"] == other_id
    assert other_state["competitors"] == ["andere_concurrent"]
    assert "weberbenelux" not in other_state["competitors"]
    assert "voorbeeld_concurrent" not in other_state["competitors"]

    # Duurzame export/import bewaart weekly_responsible én crawl-account status
    with transaction(db_path) as conn:
        pkg = export_package(conn)

    db_restored = tmp_path / "competitors_restored.db"
    initialize_database(db_restored)
    with transaction(db_restored) as conn2:
        apply_migrations(conn2)
        apply_import(conn2, pkg)

    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db_restored))
    http2 = TestClient(create_app())
    restored_clients = {c["name"]: c["id"] for c in http2.get("/api/clients").json()["clients"]}
    restored_state = http2.get(f"/api/clients/{restored_clients['BBQube Testklant']}/comparison").json()
    assert restored_state["weekly_plan"]["responsible_name"] == "Jet"
    restored_weber = [r for r in restored_state["account_rows"] if r["username"] == "weberbenelux"][0]
    assert restored_weber["last_succeeded_label"] != "Nog niet gelukt"
