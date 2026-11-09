"""LOCAL_TEST: Figma planning parse/link rules — no Figma writes, no paid AI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from maaike.db import initialize_database, transaction
from datetime import date

import pytest

from maaike.figma_planning import (
    FILE_KEY_DEFAULT,
    apply_link_to_post,
    content_kind_label,
    is_usable_classification,
    parse_brief_fields,
    parse_hook_field,
    parse_items_from_metadata_xml,
    preview_link_to_post,
    suggest_post_matches,
    sync_from_metadata_files,
    upsert_planning_items,
    week_letter_for_date,
)
from maaike.repository import add_format, add_pillar, save_editorial


SAMPLE_XML = """
<canvas id="0:1" name="November">
  <section id="6018:2" name="Post C1" x="0" y="0" width="100" height="100">
    <text id="6018:6" name="INSTA - POST Content format: nvt. Contentpijler: Branche &amp; Trends Wat moet de gebruiker doen / onthouden na het zien van de post? Contact opnemen. Beeldmateriaal omschrijving: Slide 1. Inspiratie / voorbeeld post: nvt." />
    <text id="6018:7" name="Hook / tekst in post: Een beurs op de planning staan?" />
  </section>
  <section id="6012:14" name="Post B1" x="0" y="0" width="100" height="100">
    <text id="6012:25" name="INSTA - REEL Content format: R07 Contentpijler: Branche &amp; Trends Wat moet de gebruiker doen / onthouden na het zien van de post? Positioneren. Beeldmateriaal omschrijving: InCoDa. Inspiratie / voorbeeld post: nvt." />
    <text id="6101:34" name="Hook / tekst in post: nvt --&gt; ondertitelen" />
  </section>
  <section id="2004:40" name="Template - Reel" x="0" y="0" width="100" height="100">
    <text id="2001:7" name="INSTA - REEL Content format: Hier in te vullen Contentpijler: Hier in te vullen Wat moet de gebruiker doen / onthouden na het zien van de post? Hier in te vullen" />
  </section>
</canvas>
"""


def test_usable_and_parse_helpers():
    assert is_usable_classification("R07") is True
    assert is_usable_classification("Branche & Trends") is True
    assert is_usable_classification("Hier in te vullen") is False
    assert is_usable_classification("nvt.") is False
    assert is_usable_classification("n.v.t.") is False
    brief = parse_brief_fields(
        "INSTA - REEL Content format: R07 Contentpijler: Branche & Trends Wat moet de gebruiker doen / onthouden na het zien van de post? x"
    )
    assert brief["format_raw"] == "R07"
    assert brief["format_usable"] is True
    assert brief["pillar_usable"] is True
    assert brief["content_kind"] == "reel"
    hook = parse_hook_field("Hook / tekst in post: nvt --> ondertitelen")
    assert hook["hook_usable"] is False


def test_metadata_xml_import_and_no_duplicates(tmp_path: Path, monkeypatch):
    db = tmp_path / "figma.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        items = parse_items_from_metadata_xml(
            SAMPLE_XML,
            file_key=FILE_KEY_DEFAULT,
            page_name="November",
            page_node_id="0:1",
        )
        assert {i["code"] for i in items} == {"C1", "B1"}
        c1 = next(i for i in items if i["code"] == "C1")
        assert c1["format_usable"] is False  # nvt.
        assert c1["pillar_usable"] is True
        assert c1["hook_usable"] is True
        b1 = next(i for i in items if i["code"] == "B1")
        assert b1["format_raw"] == "R07"
        assert b1["hook_usable"] is False

        first = upsert_planning_items(conn, client_id, items)
        second = upsert_planning_items(conn, client_id, items)
        assert first["inserted"] == 2
        assert second["inserted"] == 0
        assert second["updated"] == 2

        result = sync_from_metadata_files(
            conn,
            client_id,
            [{"page_name": "November", "page_node_id": "0:1", "xml": SAMPLE_XML}],
            file_key=FILE_KEY_DEFAULT,
            note="LOCAL_TEST snapshot",
        )
        assert result["connection"]["file_key"] == FILE_KEY_DEFAULT
        assert len(result["items"]) == 2


def test_link_preview_keeps_manual_values(tmp_path: Path, monkeypatch):
    db = tmp_path / "figma_link.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    now = datetime.now(tz=timezone.utc).isoformat()
    with transaction() as conn:
        qa = int(
            conn.execute(
                "INSERT INTO clients (name, created_at, updated_at, meta_status) VALUES ('QA Controle', ?, ?, 'not_connected')",
                (now, now),
            ).lastrowid
        )
        add_format(conn, qa, "R07", "LOCAL_TEST reel")
        add_pillar(conn, qa, "Branche & Trends", "LOCAL_TEST")
        conn.execute(
            """
            INSERT INTO posts (
                id, client_id, platform, external_id, published_at, content_kind,
                permalink, caption, media_urls, views, likes, comments, shares, saves, clicks, reach
            ) VALUES (501, ?, 'instagram', 'qa-501', '2026-11-10T12:00:00+00:00', 'reel',
                      'https://ig/501', 'LOCAL_TEST', '', 10, 1, 0, 0, 0, NULL, 20)
            """,
            (qa,),
        )
        # Existing manual format — must not be overwritten
        fmt_id = int(conn.execute("SELECT id FROM content_formats WHERE name='R07'").fetchone()[0])
        save_editorial(conn, qa, post_id=501, format_id=fmt_id, pillar_id=None, hook="manual hook")

        sync_from_metadata_files(
            conn,
            qa,
            [{"page_name": "November", "page_node_id": "0:1", "xml": SAMPLE_XML}],
            file_key=FILE_KEY_DEFAULT,
            note="LOCAL_TEST",
        )
        item_id = int(
            conn.execute(
                "SELECT id FROM figma_planning_items WHERE client_id=? AND code='B1'",
                (qa,),
            ).fetchone()[0]
        )
        preview = preview_link_to_post(conn, qa, item_id, 501)
        assert any(s["field"] == "format" and "kept" in s["reason"].lower() for s in preview["skipped"])
        # B1 hook in Figma is n.v.t. → unusable, so not proposed for fill
        assert any(s["field"] == "hook" and "unusable" in s["reason"].lower() for s in preview["skipped"])
        # Pillar empty on post + usable in Figma → fill
        assert any(c["field"] == "pillar" for c in preview["changes"])

        applied = apply_link_to_post(conn, qa, item_id, 501, confirm=True)
        assert applied["ok"] is True
        row = conn.execute("SELECT hook FROM post_editorial WHERE post_id=501").fetchone()
        assert row["hook"] == "manual hook"


def test_b1_suggestions_prefer_november_week_b(tmp_path: Path, monkeypatch):
    assert week_letter_for_date(date(2026, 11, 3), year=2026, month=11) == "B"
    db = tmp_path / "figma_suggest.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        sync_from_metadata_files(
            conn,
            client_id,
            [{"page_name": "November", "page_node_id": "0:1", "xml": SAMPLE_XML}],
            file_key=FILE_KEY_DEFAULT,
            note="LOCAL_TEST",
        )
        item_id = int(
            conn.execute(
                "SELECT id FROM figma_planning_items WHERE client_id=? AND code='B1'",
                (client_id,),
            ).fetchone()[0]
        )
        # Week B reel (Nov 3) should outrank an out-of-month reel.
        conn.execute(
            """
            INSERT INTO posts (
                id, client_id, platform, external_id, published_at, content_kind,
                permalink, caption
            ) VALUES
            (701, ?, 'instagram', 'nov-b', '2026-11-03T12:00:00+00:00', 'reel', 'https://ig/701', 'week B'),
            (702, ?, 'instagram', 'oct-r', '2026-10-07T12:00:00+00:00', 'reel', 'https://ig/702', 'other month'),
            (703, ?, 'instagram', 'nov-c', '2026-11-12T12:00:00+00:00', 'reel', 'https://ig/703', 'week C')
            """,
            (client_id, client_id, client_id),
        )
        suggestions = suggest_post_matches(conn, client_id, item_id, limit=5)
        assert suggestions
        assert suggestions[0]["post_id"] == 701
        assert suggestions[0]["week_letter"] == "B"
        assert suggestions[0]["planning_week_letter"] == "B"
        assert any("same week letter B" in r for r in suggestions[0]["reasons"])
        # Multiple candidates remain; never auto-linked.
        assert all(s["confidence"] in {"low", "medium"} for s in suggestions)
        assert suggestions[0].get("note")


def test_content_kind_mismatch_requires_explicit_accept_and_cancel_saves_nothing(tmp_path: Path, monkeypatch):
    assert content_kind_label("carousel_album") == "carrousel"
    assert content_kind_label("reel") == "reel"
    db = tmp_path / "figma_mismatch.db"
    monkeypatch.setenv("MAAIKE_DATABASE_PATH", str(db))
    initialize_database()
    with transaction() as conn:
        client_id = int(conn.execute("SELECT id FROM clients WHERE name = 'Red Rock'").fetchone()[0])
        add_format(conn, client_id, "R07", "LOCAL_TEST reel")
        add_pillar(conn, client_id, "Branche & Trends", "LOCAL_TEST")
        sync_from_metadata_files(
            conn,
            client_id,
            [{"page_name": "November", "page_node_id": "0:1", "xml": SAMPLE_XML}],
            file_key=FILE_KEY_DEFAULT,
            note="LOCAL_TEST",
        )
        item_id = int(
            conn.execute(
                "SELECT id FROM figma_planning_items WHERE client_id=? AND code='B1'",
                (client_id,),
            ).fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO posts (
                id, client_id, platform, external_id, published_at, content_kind,
                permalink, caption
            ) VALUES (802, ?, 'instagram', 'nov-car', '2026-11-05T12:00:00+00:00', 'carousel_album',
                      'https://ig/802', 'carousel in week B')
            """,
            (client_id,),
        )
        preview = preview_link_to_post(conn, client_id, item_id, 802)
        assert preview["content_kind_compare"]["display"] == "Figma: reel · Gepubliceerd: carrousel"
        assert preview["content_kind_compare"]["mismatch"] is True
        assert any(c["field"] == "format" for c in preview["changes"])

        with pytest.raises(ValueError, match="accept_content_kind_mismatch"):
            apply_link_to_post(conn, client_id, item_id, 802, confirm=True)

        # Cancel path: nothing linked, no editorial
        item = conn.execute(
            "SELECT linked_post_id, link_status FROM figma_planning_items WHERE id=?",
            (item_id,),
        ).fetchone()
        assert item["linked_post_id"] is None
        ed = conn.execute("SELECT format_id, pillar_id FROM post_editorial WHERE post_id=802").fetchone()
        assert ed is None or (ed["format_id"] is None and ed["pillar_id"] is None)

        applied = apply_link_to_post(
            conn,
            client_id,
            item_id,
            802,
            confirm=True,
            accept_content_kind_mismatch=True,
        )
        assert applied["ok"] is True
        assert (
            conn.execute(
                "SELECT linked_post_id FROM figma_planning_items WHERE id=?",
                (item_id,),
            ).fetchone()["linked_post_id"]
            == 802
        )
