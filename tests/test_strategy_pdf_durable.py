"""Durable per-client strategy PDF storage, isolation, restore, and legacy fallback."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _sample_pdf_bytes(title: str = "BBQube Strategie") -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 800, title)
    c.drawString(72, 780, "Website")
    c.drawString(72, 760, "https://bbqube.nl")
    c.drawString(72, 720, "Tone of voice")
    c.drawString(72, 700, "Warm en ambachtelijk.")
    c.save()
    return buf.getvalue()


def test_strategy_pdf_persists_isolates_and_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_a = tmp_path / "maaike_a.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db_a))
    monkeypatch.setenv("MAAIKE_PERSIST_ENABLED", "0")
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_PASSWORD", "")

    from maaike.data_transfer import apply_import, export_package_json_bytes
    from maaike.db import initialize_database, transaction
    from maaike.repository import add_client
    from maaike.strategy import save_strategy
    from maaike_web.app import create_app

    initialize_database(db_a)
    with transaction(db_a) as conn:
        client_a = add_client(conn, "Tijdelijk PDF Klant")
        client_b = add_client(conn, "Andere Klant")
        save_strategy(
            conn,
            client_a,
            start_answers={
                "website": "https://handmatig.bbqube.nl",
                "bedrijfsomschrijving": "Handmatige omschrijving.",
                "sectoren": "Horeca & events",
                "geografische_regio": "Nederland",
                "producten_diensten": "BBQ-catering",
                "onderscheidend_vermogen": "Beleving op vuur",
                "gewenste_socialresultaten": "Bereik en aanvragen",
                "platforms": "Instagram",
            },
        )

    app = create_app()
    pdf_bytes = _sample_pdf_bytes()

    with TestClient(app) as http:
        prev = http.post(
            f"/api/clients/{client_a}/strategy/import/pdf-preview",
            files={"file": ("bbqube-strategie.pdf", pdf_bytes, "application/pdf")},
        )
        assert prev.status_code == 200
        prev_json = prev.json()
        assert prev_json["file_ref"].startswith("spdf_")

        staged = http.post(
            f"/api/clients/{client_a}/strategy/import/apply",
            json={
                "proposed": prev_json["proposed"],
                "preserve_manual": True,
                "stage_only": True,
                "source_kind": "strategy_pdf",
                "filename": prev_json["filename"],
                "file_ref": prev_json["file_ref"],
            },
        )
        assert staged.status_code == 200
        staged_json = staged.json()
        assert staged_json["strategy_pdf"]["available"] is True
        assert staged_json["strategy_pdf"]["needs_reupload"] is False
        assert staged_json["start_answers"]["website"] == "https://handmatig.bbqube.nl"

        approved = http.post(
            f"/api/clients/{client_a}/strategy/proposal/approve",
            json={"proposal": staged_json["pending_proposal"]},
        )
        assert approved.status_code == 200

        completed = http.put(
            f"/api/clients/{client_a}/strategy",
            json={
                "account_info": {"naam": "BBQube"},
                "start_answers": approved.json()["start_answers"],
                "strategy_fields": {},  # omits last_pdf_meta on purpose: server must preserve ref
                "source_notes": [],
                "mark_complete": True,
            },
        )
        assert completed.status_code == 200
        comp_json = completed.json()
        assert comp_json["review_status"] == "definitief"
        assert comp_json["canva_url"] == ""
        assert comp_json["strategy_pdf"]["available"] is True

        # Cross-client isolation: client_b cannot fetch client_a's PDF even with exact ref.
        forbidden_other = http.get(
            f"/api/clients/{client_b}/strategy/pdf",
            params={"ref": prev_json["file_ref"]},
        )
        assert forbidden_other.status_code == 404

        # Authorized client_a can view and download identical bytes.
        inline = http.get(
            f"/api/clients/{client_a}/strategy/pdf",
            params={"disposition": "inline", "ref": prev_json["file_ref"]},
        )
        assert inline.status_code == 200
        assert inline.content == pdf_bytes
        assert "inline" in inline.headers.get("content-disposition", "")

        dl = http.get(
            f"/api/clients/{client_a}/strategy/pdf",
            params={"disposition": "attachment", "ref": prev_json["file_ref"]},
        )
        assert dl.status_code == 200
        assert dl.content == pdf_bytes
        assert "attachment" in dl.headers.get("content-disposition", "")

    # Simulate Render Free restart: export package -> fresh SQLite DB -> PDF & approved strategy survive.
    with transaction(db_a) as conn:
        pkg_bytes = export_package_json_bytes(conn)

    db_b = tmp_path / "maaike_restored.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db_b))
    initialize_database(db_b)
    with transaction(db_b) as conn:
        apply_import(conn, json.loads(pkg_bytes.decode("utf-8")), overwrite=True)
        restored_row = conn.execute(
            "SELECT id FROM clients WHERE name = ?", ("Tijdelijk PDF Klant",)
        ).fetchone()
        assert restored_row is not None
        restored_id = int(restored_row["id"])

    app_restored = create_app()
    with TestClient(app_restored) as http2:
        strat = http2.get(f"/api/clients/{restored_id}/strategy").json()
        assert strat["review_status"] == "definitief"
        assert strat["strategy_pdf"]["available"] is True
        dl2 = http2.get(f"/api/clients/{restored_id}/strategy/pdf?disposition=attachment")
        assert dl2.status_code == 200
        assert dl2.content == pdf_bytes


def test_legacy_filename_only_signals_reupload_and_preserves_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "maaike_legacy.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MAAIKE_PERSIST_ENABLED", "0")
    monkeypatch.setenv("MAAIKE_BASIC_AUTH_PASSWORD", "")

    from maaike.db import initialize_database, transaction
    from maaike.repository import add_client
    from maaike.strategy import save_strategy
    from maaike_web.app import create_app

    initialize_database(db_path)
    with transaction(db_path) as conn:
        cid = add_client(conn, "Legacy PDF Klant")
        save_strategy(
            conn,
            cid,
            start_answers={
                "website": "https://legacy.example",
                "bedrijfsomschrijving": "Bestaande goedgekeurde tekst",
                "sectoren": "Retail",
                "geografische_regio": "Brabant",
                "producten_diensten": "Producten",
                "onderscheidend_vermogen": "Snel",
                "gewenste_socialresultaten": "Zichtbaarheid",
                "platforms": "Instagram",
                "tone_of_voice": "Helder",
            },
            strategy_fields={"last_pdf_meta": {"filename": "oude-strategie.pdf"}},
            mark_complete=True,
        )

    app = create_app()
    pdf_bytes = _sample_pdf_bytes("Herstelde PDF")
    with TestClient(app) as http:
        before = http.get(f"/api/clients/{cid}/strategy").json()
        assert before["review_status"] == "definitief"
        assert before["strategy_pdf"]["available"] is False
        assert before["strategy_pdf"]["needs_reupload"] is True
        assert before["strategy_pdf"]["filename"] == "oude-strategie.pdf"

        reup = http.post(
            f"/api/clients/{cid}/strategy/pdf",
            files={"file": ("oude-strategie.pdf", pdf_bytes, "application/pdf")},
        )
        assert reup.status_code == 200
        after = reup.json()
        assert after["review_status"] == "definitief"
        assert after["start_answers"]["bedrijfsomschrijving"] == "Bestaande goedgekeurde tekst"
        assert after["strategy_pdf"]["available"] is True
        assert after["strategy_pdf"]["needs_reupload"] is False
