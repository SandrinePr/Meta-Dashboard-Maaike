"""LOCAL_TEST: client report PDF from saved data — no paid AI."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from maaike.client_report_pdf import build_client_report_pdf_bytes, write_client_report_pdf
from maaike.client_report_view import build_client_report_presentation, comparison_prompt_block
from maaike.db import connect
from maaike.report_prompts import PROMPT_VERSION, load_report_instruction_bundle
from maaike.reports import get_report, inspect_client_report_data

REPO = Path(__file__).resolve().parents[1]
LIVE_DB = REPO / "data" / "maaike_redrock.db"
OUT = REPO / "data" / "report_pdfs" / "client-report-9-red-rock-2026-09.pdf"


def test_prompt_supplement_v22_loaded():
    assert PROMPT_VERSION == "maaike-rapporten-v2.2"
    bundle = load_report_instruction_bundle("client")
    assert bundle["supporting_files"]["analysis_supplement"]["loaded"] is True
    assert "Ontbrekende registratie" in bundle["system_text"] or "ontbrekende registratie" in bundle["system_text"].lower()
    assert "Niet onderzocht / onvoldoende gegevens" in bundle["system_text"]
    assert "klantlegenda" in bundle["system_text"].lower()


def test_comparison_block_in_inspect_prompt_input():
    if not LIVE_DB.exists():
        pytest.skip("maaike_redrock.db missing")
    conn = connect(LIVE_DB)
    try:
        preview = inspect_client_report_data(conn, 1, period_year=2026, period_month=9)
        block = (preview.get("prompt_input") or {}).get("comparison_for_prompt") or {}
        assert block.get("metric")
        assert "usable_posts" in block
        assert block["current_period"].get("post_count") is not None
        # helper stays consistent
        rebuilt = comparison_prompt_block(
            {
                "period": preview["period"],
                "metrics": preview["metrics"],
                "comparison": preview["comparison"],
            }
        )
        assert rebuilt["metric"] == block["metric"]
    finally:
        conn.close()


def test_report_9_pdf_dutch_partial_concept_no_ai():
    if not LIVE_DB.exists():
        pytest.skip("maaike_redrock.db missing")
    conn = connect(LIVE_DB)
    try:
        payload = get_report(conn, 1, 9)
        report = payload["report"]
        body_before = report["body"]
        six_before = body_before.get("six_answers")
        presentation = build_client_report_presentation(
            conn, 1, report, review=payload.get("review") or {}
        )
        assert presentation["title"] == "Maandrapport Red Rock — september 2026"
        assert presentation["status"]["label_pdf_nl"] == "Partieel concept — niet goedgekeurd"
        assert presentation["content_source"] == "ai_concept"
        assert presentation["content_corrections_open"] is True
        assert presentation["review_attention_points"]
        kinds = {p["kind"] for p in presentation["review_attention_points"]}
        assert "registration_vs_quality" in kinds
        assert "format_legend_mismatch" in kinds
        assert all(p.get("kind_nl") for p in presentation["review_attention_points"])
        # Format annotation uses official legend names (display only)
        joined = " ".join(a["text_display"] for a in presentation["six_answers"] + presentation["chapters"])
        assert "Medewerker aan het woord over andere medewerker" in joined
        assert "Carrousel van video's" in joined
        assert "praktische branchecase" not in joined
        assert "expert-carrousel" not in joined
        assert "higher" not in " ".join(m["value"] for m in presentation["key_metrics"])
        assert "lower" not in " ".join(m["value"] for m in presentation["key_metrics"])
        assert any("Geen passend trendrapport" in m for m in presentation["missing_data"])

        meta = write_client_report_pdf(conn, 1, 9, OUT)
        assert meta["paid_ai"] is False
        assert Path(meta["path"]).exists()

        reader = PdfReader(meta["path"])
        assert 1 <= len(reader.pages) <= 2
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        assert "Maandrapport Red Rock — september 2026" in text
        assert "Partieel concept — niet goedgekeurd" in text
        assert "Draft" in text
        assert "Opgeteld bekend postbereik" in text
        assert "Kerncijfers" in text
        assert "Zes analysevragen" in text
        assert "What performed better?" not in text  # no English section headers
        assert "registration_vs_quality" not in text
        assert "six_answers.stoppen" not in text
        # Personal feedback / review flags stay out of the client PDF
        assert "Registratie versus contentkwaliteit" not in text
        assert "Aandachtspunten voor menselijke review" not in text
        assert "higher" not in text
        assert "lower" not in text
        assert "No matching trend report" not in text
        assert "No targets recorded" not in text
        assert "raw_response" not in text
        assert "Persoonlijke feedback" in text
        assert "Niet onderzocht" in text
        # AI body unchanged after PDF generation
        after = get_report(conn, 1, 9)["report"]["body"]
        assert after.get("six_answers") == six_before
        assert after.get("partial") is True
    finally:
        conn.close()


def test_approved_pdf_uses_human_final_version():
    presentation = {
        "title": "Maandrapport Test — januari 2026",
        "client_name": "Test",
        "period_label": "2026-01-01 → 2026-01-31",
        "compare_label": "—",
        "version": 1,
        "created_at": "2026-01-02 10:00 UTC",
        "report_id": 99,
        "status": {
            "code": "approved",
            "label_nl": "Goedgekeurd",
            "label_pdf_nl": "Goedgekeurd",
            "approved": True,
        },
        "content_source": "approved_final",
        "content_source_label_nl": "Menselijke eindversie (goedgekeurd)",
        "approved_final_text": "Dit is de menselijke eindversie na review.",
        "show_summary": False,
        "key_metrics": [],
        "six_answers": [
            {
                "label_nl": "Wat presteerde beter?",
                "text": "AI-concept dat NIET in goedgekeurde PDF mag staan.",
                "text_display": "AI-concept dat NIET in goedgekeurde PDF mag staan.",
            }
        ],
        "chapters": [],
        "action_plan": [],
        "missing_data": [],
        "missing_sources": [],
        "review_attention_points": [],
        "content_corrections_open": False,
        "has_readable_content": True,
    }
    pdf = build_client_report_pdf_bytes(presentation)
    from io import BytesIO

    text = "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf)).pages)
    assert "menselijke eindversie na review" in text
    assert "AI-concept dat NIET" not in text
    assert "Goedgekeurd" in text
