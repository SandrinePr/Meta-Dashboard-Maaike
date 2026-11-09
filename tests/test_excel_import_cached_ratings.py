"""Excel import: cached Score/Beoordeling, no formula text, assessment preview diffs."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula

from maaike.db import initialize_database, transaction
from maaike.excel_import import (
    _is_formula_like,
    _resolve_cached_label,
    _resolve_cached_score,
    build_preview,
    execute_import,
    parse_workbook,
)
from maaike.migrate import apply_migrations
from maaike.repository import add_client


def _make_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Post performance"
    headers = [
        "Maand",
        "Datum",
        "Platform",
        "Content soort",
        "Content format",
        "Post: URL van post",
        "Contentpijler",
        "Weergaven",
        "Hook",
        "Likes",
        "Comments",
        "Shares",
        "Saves",
        "Clicks",
        "Beoordeling",
        "Insight: waarom gebeurde dit?",
        "Actie: wat doen we de volgende keer anders?",
        "Score",
    ]
    ws.append(headers)
    ws.append(
        [
            "Maart",
            "2026-03-01",
            "Instagram",
            "Reel",
            "R01",
            "https://www.instagram.com/p/TESTCACHED1/",
            "Cases",
            100,
            "nvt",
            10,
            1,
            0,
            2,
            0,
            "Goed",
            "Insight A",
            "Actie A",
            4.5,
        ]
    )
    # Row 3: formulas without cached values (fresh xlsx → data_only is None)
    ws.append(
        [
            "Maart",
            "2026-03-02",
            "Instagram",
            "Reel",
            "R02",
            "https://www.instagram.com/p/TESTMISSINGCACHE/",
            "Cases",
            50,
            "nvt",
            5,
            0,
            0,
            0,
            0,
            None,
            "Insight B",
            "Actie B",
            None,
        ]
    )
    ws["O3"] = ArrayFormula("O3", '=IF(R3="","","Goed")')
    ws["R3"] = ArrayFormula("R3", "=1+1")

    fmt = wb.create_sheet("Formats")
    fmt.append(["Carrousel / post formats", "Voorbeeld", "Omschrijving", "Status", "Aantal x ingezet"])
    fmt.append(["R01", "https://example.com/r01", "Reel case", "Actief", 3])
    fmt.append(["R02", "https://example.com/r02", "Reel tip", "Test", 1])

    tov = wb.create_sheet("Feedback TOV")
    tov["A1"] = "Feedback instagram en LinkedIn"
    tov["A2"] = "Houd het persoonlijk en concreet."

    april = wb.create_sheet("April 2026")
    april["A1"] = "Klant"
    april["B1"] = "QA Excel"
    april["A10"] = "Analyse vorige planning"
    april["A11"] = "Reels met cases deden het beter."
    april["A20"] = "Bijzonderheden"
    april["A21"] = "Lancering in week 2."

    wb.save(path)


def test_missing_cache_does_not_wipe_existing_values():
    from maaike.excel_import import ParsedRow, _effective_assessment_values

    row = ParsedRow(
        excel_row=9,
        maand="Maart",
        datum=None,
        platform_label="Instagram",
        platform_key="instagram",
        content_soort="Reel",
        format_code="R01",
        permalink_raw=None,
        permalink_norm=None,
        external_id="x",
        contentpijler=None,
        hook=None,
        metrics={},
        rating_text=None,
        rating_fill=None,
        insight=None,
        action=None,
        score_value=None,
        rating_origin="missing_cached_value",
        score_origin="missing_cached_value",
        rating_missing_reason="Beoordeling: formule zonder opgeslagen uitkomst",
        score_missing_reason="Score: formule zonder opgeslagen uitkomst",
    )
    existing = {
        "rating_text": "Goed",
        "score_value": 4.46,
        "rating_origin": "excel_cached_formula",
        "score_origin": "excel_cached_formula",
    }
    effective = _effective_assessment_values(existing, row)
    assert effective["rating_text"] == "Goed"
    assert effective["score_value"] == 4.46
    assert effective["rating_preserved_due_to_missing_cache"] is True
    assert effective["score_preserved_due_to_missing_cache"] is True


def test_formula_like_and_cached_resolvers():
    assert _is_formula_like("=SUM(1)")
    assert _is_formula_like(ArrayFormula("A1", "=1"))
    label, origin, missing = _resolve_cached_label(
        ArrayFormula("O2", '=IF(1,"Goed","")'),
        "Goed",
        field_name="Beoordeling",
    )
    assert label == "Goed"
    assert origin == "excel_cached_formula"
    assert missing is None
    label2, origin2, missing2 = _resolve_cached_label(
        ArrayFormula("O3", "=IF(1,1,1)"),
        None,
        field_name="Beoordeling",
    )
    assert label2 is None
    assert origin2 == "missing_cached_value"
    assert "formule zonder opgeslagen uitkomst" in (missing2 or "")
    score, s_origin, s_missing = _resolve_cached_score(ArrayFormula("R2", "=1"), 4.46)
    assert score == 4.46
    assert s_origin == "excel_cached_formula"
    assert s_missing is None
    score2, _, missing_score = _resolve_cached_score(ArrayFormula("R3", "=1"), None)
    assert score2 is None
    assert "geen 0" in (missing_score or "").lower() or "niet als 0" in (missing_score or "")


def test_import_preview_and_reimport_preserves_human_fields(tmp_path: Path):
    db = tmp_path / "excel.db"
    initialize_database(db)
    xlsx = tmp_path / "strategy.xlsx"
    _make_workbook(xlsx)

    with transaction(db) as conn:
        apply_migrations(conn)
        client_id = add_client(conn, "QA Excel")
        parsed = parse_workbook(xlsx)
        assert parsed["analysis_context"]["feedback_tov"]["present"] is True
        assert any(m["sheet_name"] == "April 2026" for m in parsed["analysis_context"]["month_sheets"])
        # Row with plain label has rating; formula row without cache must not become formula text
        by_url = {r.permalink_raw: r for r in parsed["rows"]}
        ok = by_url["https://www.instagram.com/p/TESTCACHED1/"]
        assert ok.rating_text == "Goed"
        assert ok.score_value == 4.5
        missing = by_url["https://www.instagram.com/p/TESTMISSINGCACHE/"]
        assert missing.rating_text is None
        assert missing.rating_origin == "missing_cached_value"
        assert missing.rating_missing_reason
        assert "ArrayFormula" not in (missing.rating_text or "")

        preview = build_preview(conn, client_id, parsed)
        assert preview["rating_formula_live"] is False
        assert preview["missing_cached_formula_outcomes"] >= 1

        result = execute_import(
            conn, client_id, path=xlsx, parsed=parsed, update_assessments=False
        )
        assert result["applied"]["added"] >= 1
        assert result["update_assessments"] is False

        # Seed a divergent assessment then preview diffs without applying
        post = conn.execute(
            "SELECT id FROM posts WHERE permalink LIKE '%TESTCACHED1%' AND client_id = ?",
            (client_id,),
        ).fetchone()
        conn.execute(
            """
            UPDATE post_assessments
            SET rating_text = 'Slecht', score_value = 0.5, insight_text = 'Menselijke insight'
            WHERE post_id = ? AND source = 'excel_imported'
            """,
            (post["id"],),
        )
        preview2 = build_preview(conn, client_id, parsed)
        assert preview2["assessment_diff_count"] >= 1
        # Reimport without update_assessments keeps human insight
        execute_import(conn, client_id, path=xlsx, parsed=parsed, update_assessments=False)
        row = conn.execute(
            "SELECT rating_text, insight_text, score_value FROM post_assessments WHERE post_id = ?",
            (post["id"],),
        ).fetchone()
        assert row["insight_text"] == "Menselijke insight"
        assert row["rating_text"] == "Slecht"

        # With update_assessments: rating/score update, insight preserved when already set
        execute_import(conn, client_id, path=xlsx, parsed=parsed, update_assessments=True)
        row2 = conn.execute(
            "SELECT rating_text, insight_text, score_value, rating_origin FROM post_assessments WHERE post_id = ?",
            (post["id"],),
        ).fetchone()
        assert row2["rating_text"] == "Goed"
        assert row2["insight_text"] == "Menselijke insight"
        assert float(row2["score_value"]) == 4.5

        # Client isolation: other client has no posts from this import
        other = add_client(conn, "Other Client")
        count_other = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE client_id = ?", (other,)
        ).fetchone()[0]
        assert count_other == 0

        # Formats extras stored
        fmt = conn.execute(
            "SELECT example_url, status, usage_count, explanation FROM content_formats WHERE client_id = ? AND name = 'R01'",
            (client_id,),
        ).fetchone()
        assert fmt["example_url"]
        assert fmt["status"] == "Actief"
        assert fmt["usage_count"] == 3
        assert "Reel case" in (fmt["explanation"] or "")
