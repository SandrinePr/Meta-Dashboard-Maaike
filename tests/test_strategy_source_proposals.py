"""Point 9: strategy proposals from Figma/Canva — no paid AI, empty fields only."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _figma_doc_with_strategy_and_creatives() -> dict:
    return {
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "name": "Document",
            "children": [
                {
                    "id": "1:1",
                    "type": "CANVAS",
                    "name": "Strategie",
                    "children": [
                        {
                            "id": "1:2",
                            "type": "TEXT",
                            "name": "Doelgroep",
                            "characters": "Doelgroep",
                        },
                        {
                            "id": "1:3",
                            "type": "TEXT",
                            "name": "body",
                            "characters": "Midden-Nederlandse MKB-ondernemers die zichtbaarheid willen.",
                        },
                        {
                            "id": "1:4",
                            "type": "TEXT",
                            "name": "Tone of voice",
                            "characters": "Tone of voice",
                        },
                        {
                            "id": "1:5",
                            "type": "TEXT",
                            "name": "tone body",
                            "characters": "Warm, deskundig en kort.",
                        },
                    ],
                },
                {
                    "id": "2:1",
                    "type": "CANVAS",
                    "name": "November",
                    "children": [
                        {
                            "id": "2:2",
                            "type": "SECTION",
                            "name": "Post B1",
                            "children": [
                                {
                                    "id": "2:3",
                                    "type": "TEXT",
                                    "characters": (
                                        "INSTA - POST Content format: R07 "
                                        "Contentpijler: Branche & Trends "
                                        "Wat moet de gebruiker doen / onthouden na het zien van de post? x"
                                    ),
                                },
                                {
                                    "id": "2:4",
                                    "type": "TEXT",
                                    "characters": "Hook / tekst in post: Een beurs op de planning?",
                                },
                            ],
                        }
                    ],
                },
            ],
        }
    }


def _figma_doc_creatives_only() -> dict:
    return {
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "children": [
                {
                    "id": "2:1",
                    "type": "CANVAS",
                    "name": "November",
                    "children": [
                        {
                            "id": "2:2",
                            "type": "SECTION",
                            "name": "Reel A1",
                            "children": [
                                {
                                    "id": "2:3",
                                    "type": "TEXT",
                                    "characters": (
                                        "INSTA - REEL Content format: R01 "
                                        "Contentpijler: Behind the scenes "
                                        "Wat moet de gebruiker doen / onthouden na het zien van de post? x"
                                    ),
                                },
                                {
                                    "id": "2:4",
                                    "type": "TEXT",
                                    "characters": "Hook / tekst in post: Kijk mee achter de schermen",
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    }


@pytest.fixture()
def strategy_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "strategy_sources.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    monkeypatch.setenv("MAAIKE_PERSIST_ENABLED", "0")
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_PASSWORD", "")
    monkeypatch.setenv("MAAIKE_EDITOR_AUTH_PASSWORD", "")
    monkeypatch.setenv("MAAIKE_VIEWER_AUTH_PASSWORD", "")
    monkeypatch.setenv("FIGMA_ACCESS_TOKEN", "test-token")

    from maaike.db import initialize_database, transaction
    from maaike.figma_planning import save_figma_connection
    from maaike.repository import add_client
    from maaike.strategy import save_strategy
    from maaike_web.app import create_app

    initialize_database(db)
    with transaction(db) as conn:
        client_id = add_client(conn, "Bron Test Klant")
        save_strategy(
            conn,
            client_id,
            start_answers={"website": "https://handmatig.example"},
        )
        save_figma_connection(
            conn,
            client_id,
            file_key="AbcFigmaKey123",
            source_url="https://www.figma.com/design/AbcFigmaKey123/test",
        )

    app = create_app()
    with TestClient(app) as http:
        yield http, client_id


def test_canva_link_does_not_extract_content(strategy_http):
    http, client_id = strategy_http
    res = http.post(
        f"/api/clients/{client_id}/strategy/import/canva-preview",
        json={"url": "https://www.canva.com/design/DAFexample/view"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["content_extracted"] is False
    assert body.get("link_import_available") is False
    assert body["proposed"]["start_answers"] == {}
    assert "PDF" in body["note"]
    assert "nog open" in body["note"].lower() or "openstaat" in body["note"].lower()


def test_figma_usable_source_proposes_only_found_fields(strategy_http):
    http, client_id = strategy_http
    from maaike.db import transaction
    from maaike.strategy_import import preview_figma_strategy

    with transaction() as conn:
        preview = preview_figma_strategy(
            conn, client_id, document=_figma_doc_with_strategy_and_creatives()
        )
    assert preview["content_extracted"] is True
    assert "tone_of_voice" in preview["proposed"]["start_answers"]
    assert "doelgroep" in preview["proposed"]["strategy_fields"]
    assert preview["proposed"]["field_sources"]["tone_of_voice"]
    assert "platforms" in preview["proposed"]["start_answers"]
    assert "Instagram" in preview["proposed"]["start_answers"]["platforms"]

    staged = http.post(
        f"/api/clients/{client_id}/strategy/import/apply",
        json={
            "proposed": preview["proposed"],
            "preserve_manual": True,
            "stage_only": True,
            "source_kind": "figma",
        },
    )
    assert staged.status_code == 200
    pending = staged.json()["pending_proposal"]
    assert pending["start_answers"]["tone_of_voice"]
    assert "website" not in pending["start_answers"]  # manual kept empty in proposal

    edited = dict(pending)
    edited["start_answers"] = {
        **pending["start_answers"],
        "tone_of_voice": "Aangepast door editor.",
    }
    approved = http.post(
        f"/api/clients/{client_id}/strategy/proposal/approve",
        json={"proposal": edited},
    )
    assert approved.status_code == 200
    answers = approved.json()["start_answers"]
    assert answers["website"] == "https://handmatig.example"
    assert answers["tone_of_voice"] == "Aangepast door editor."
    assert approved.json()["pending_proposal"] is None


def test_figma_creatives_only_no_audience_or_goals(strategy_http):
    from maaike.db import transaction
    from maaike.strategy_import import preview_figma_strategy

    http, client_id = strategy_http
    with transaction() as conn:
        preview = preview_figma_strategy(conn, client_id, document=_figma_doc_creatives_only())
    fields = preview["proposed"]["strategy_fields"]
    answers = preview["proposed"]["start_answers"]
    assert "doelgroep" not in fields
    assert "korte_termijn_doelen" not in fields
    assert "lange_termijn_doelen" not in fields
    assert "contentkeuzes" in fields
    assert "Behind the scenes" in fields["contentkeuzes"]
    assert answers.get("platforms") == "Instagram"


def test_figma_no_access_returns_error(strategy_http, monkeypatch):
    http, client_id = strategy_http

    def _boom(file_key: str):
        raise ValueError("Figma API refused access (403). Check token and file share permissions.")

    monkeypatch.setattr("maaike.figma_planning.fetch_figma_file", _boom)
    res = http.post(f"/api/clients/{client_id}/strategy/import/figma-preview")
    assert res.status_code == 403
    assert "403" in res.json()["detail"] or "access" in res.json()["detail"].lower()
