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


def test_canva_without_token_keeps_pdf_route(strategy_http, monkeypatch):
    http, client_id = strategy_http
    monkeypatch.delenv("CANVA_ACCESS_TOKEN", raising=False)
    res = http.post(
        f"/api/clients/{client_id}/strategy/import/canva-preview",
        json={"url": "https://www.canva.com/design/DAFexample/view"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["content_extracted"] is False
    assert body.get("link_import_available") is False
    assert body["proposed"]["start_answers"] == {}
    assert "design:content:read" in body["note"]
    assert "PDF" in body["note"] or any("PDF" in q for q in body.get("open_questions") or [])


def test_canva_connect_export_proposes_strategy_fields(strategy_http, monkeypatch):
    """Usable Canva design with strategy text → same review path as PDF (no paid AI)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import io

    from maaike.strategy_import import preview_canva_link

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.drawString(72, 750, "Tone of voice")
    pdf.drawString(72, 730, "Warm, deskundig en kort.")
    pdf.drawString(72, 700, "Doelgroep")
    pdf.drawString(72, 680, "MKB in Midden-Nederland.")
    pdf.save()
    monkeypatch.setenv("CANVA_ACCESS_TOKEN", "test-token")

    def _boom(*_a, **_k):
        raise AssertionError("live Canva export should not run in this test")

    monkeypatch.setattr("maaike.canva_connect.export_design_pdf_bytes", _boom)
    preview = preview_canva_link(
        "https://www.canva.com/design/DAFstrategyLive/view",
        pdf_bytes=buf.getvalue(),
        access_token="test-token",
    )
    assert preview["content_extracted"] is True
    assert preview["source_kind"] == "canva"
    assert "tone_of_voice" in preview["proposed"]["start_answers"]
    assert "doelgroep" in preview["proposed"]["strategy_fields"]
    assert "Canva Connect" in preview["proposed"]["field_sources"]["tone_of_voice"]

    http, client_id = strategy_http
    staged = http.post(
        f"/api/clients/{client_id}/strategy/import/apply",
        json={
            "proposed": preview["proposed"],
            "preserve_manual": True,
            "stage_only": True,
            "source_kind": "canva",
        },
    )
    assert staged.status_code == 200
    pending = staged.json()["pending_proposal"]
    assert pending["start_answers"]["tone_of_voice"]
    assert "website" not in pending["start_answers"]


def test_canva_no_access_returns_forbidden(strategy_http, monkeypatch):
    from maaike.canva_connect import CanvaAccessError

    http, client_id = strategy_http
    monkeypatch.setenv("CANVA_ACCESS_TOKEN", "test-token")

    def _denied(design_id: str, **_kwargs):
        raise CanvaAccessError(
            "Canva weigerde toegang tot dit ontwerp (HTTP 403). "
            f"Design-id: {design_id}."
        )

    monkeypatch.setattr("maaike.canva_connect.export_design_pdf_bytes", _denied)
    res = http.post(
        f"/api/clients/{client_id}/strategy/import/canva-preview",
        json={"url": "https://www.canva.com/design/DAFNoAccess/view"},
    )
    assert res.status_code == 403
    assert "403" in res.json()["detail"] or "toegang" in res.json()["detail"].lower()


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
    assert "website" not in answers
    assert "beschikbaar_beeld" not in answers
    assert "sectoren" not in answers
    assert "contentkeuzes" in fields
    assert "Behind the scenes" in fields["contentkeuzes"]
    assert answers.get("platforms") == "Instagram"


def test_figma_caption_noise_does_not_become_website(strategy_http):
    """Live creatives often have caption fragments like 'Branding, Website en' — not strategy."""
    from maaike.db import transaction
    from maaike.strategy_import import preview_figma_strategy

    http, client_id = strategy_http
    noisy = {
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "children": [
                {
                    "id": "1:1",
                    "type": "CANVAS",
                    "name": "Feed",
                    "children": [
                        {
                            "id": "1:2",
                            "type": "TEXT",
                            "characters": "Branding, Website en",
                        },
                        {
                            "id": "1:3",
                            "type": "TEXT",
                            "characters": "Social media beheer voor merken.",
                        },
                        {
                            "id": "1:4",
                            "type": "TEXT",
                            "characters": "Beeldmateriaal omschrijving: sfeerbeelden showroom",
                        },
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
                                        "Contentpijler: Cases "
                                        "Wat moet de gebruiker doen / onthouden na het zien van de post? x"
                                    ),
                                },
                            ],
                        },
                    ],
                }
            ],
        }
    }
    with transaction() as conn:
        preview = preview_figma_strategy(conn, client_id, document=noisy)
    answers = preview["proposed"]["start_answers"]
    fields = preview["proposed"]["strategy_fields"]
    assert "website" not in answers
    assert "beschikbaar_beeld" not in answers
    assert "doelgroep" not in fields
    assert "contentkeuzes" in fields
    assert "Cases" in fields["contentkeuzes"]


def test_figma_no_access_returns_error(strategy_http, monkeypatch):
    http, client_id = strategy_http

    def _boom(file_key: str):
        raise ValueError("Figma API refused access (403). Check token and file share permissions.")

    monkeypatch.setattr("maaike.figma_planning.fetch_figma_file", _boom)
    res = http.post(f"/api/clients/{client_id}/strategy/import/figma-preview")
    assert res.status_code == 403
    assert "403" in res.json()["detail"] or "access" in res.json()["detail"].lower()
