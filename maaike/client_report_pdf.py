"""Client-report PDF export from saved presentation data. No AI calls."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from maaike.client_report_view import build_client_report_presentation

DARK = colors.Color(0.12, 0.14, 0.18)
MUTED = colors.Color(0.35, 0.38, 0.42)
LINE = colors.Color(0.85, 0.86, 0.88)
ACCENT = colors.Color(0.72, 0.47, 0.27)
HEADER_BG = colors.Color(0.96, 0.95, 0.93)
STATUS_BG = colors.Color(0.93, 0.90, 0.85)
WARN_BG = colors.Color(0.97, 0.93, 0.86)

_FONT_REG = "RroSans"
_FONT_BOLD = "RroSans-Bold"
_FONTS_READY = False


def _register_fonts() -> None:
    global _FONTS_READY, _FONT_REG, _FONT_BOLD
    if _FONTS_READY:
        return
    arial = Path(r"C:\Windows\Fonts\arial.ttf")
    arial_bd = Path(r"C:\Windows\Fonts\arialbd.ttf")
    if arial.exists() and arial_bd.exists():
        pdfmetrics.registerFont(TTFont(_FONT_REG, str(arial)))
        pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(arial_bd)))
    else:
        _FONT_REG = "Helvetica"
        _FONT_BOLD = "Helvetica-Bold"
    _FONTS_READY = True


def _esc(text: Any) -> str:
    raw = str(text or "")
    raw = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    raw = re.sub(r"\r\n?", "\n", raw)
    raw = raw.replace("\n", "<br/>")
    return raw


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts()
    return {
        "brand": ParagraphStyle(
            "CrBrandNl",
            fontName=_FONT_BOLD,
            fontSize=9,
            textColor=ACCENT,
            spaceAfter=2,
        ),
        "title": ParagraphStyle(
            "CrTitleNl",
            fontName=_FONT_BOLD,
            fontSize=15,
            textColor=DARK,
            leading=18,
            spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "CrMetaNl",
            fontName=_FONT_REG,
            fontSize=8.5,
            textColor=MUTED,
            leading=11,
            spaceAfter=2,
        ),
        "status": ParagraphStyle(
            "CrStatusNl",
            fontName=_FONT_BOLD,
            fontSize=9.5,
            textColor=DARK,
            alignment=TA_LEFT,
            leading=12,
        ),
        "h2": ParagraphStyle(
            "CrH2Nl",
            fontName=_FONT_BOLD,
            fontSize=10.5,
            textColor=DARK,
            spaceBefore=5,
            spaceAfter=2,
            leading=13,
        ),
        "h3": ParagraphStyle(
            "CrH3Nl",
            fontName=_FONT_BOLD,
            fontSize=9,
            textColor=DARK,
            spaceBefore=3,
            spaceAfter=1,
            leading=11,
        ),
        "body": ParagraphStyle(
            "CrBodyNl",
            fontName=_FONT_REG,
            fontSize=8.5,
            textColor=DARK,
            leading=10.5,
            spaceAfter=2,
        ),
        "note": ParagraphStyle(
            "CrNoteNl",
            fontName=_FONT_REG,
            fontSize=7.5,
            textColor=MUTED,
            leading=9.5,
            spaceAfter=2,
        ),
        "warn": ParagraphStyle(
            "CrWarnNl",
            fontName=_FONT_REG,
            fontSize=7.5,
            textColor=DARK,
            leading=9.5,
            spaceAfter=1,
        ),
        "th": ParagraphStyle(
            "CrThNl",
            fontName=_FONT_BOLD,
            fontSize=7.5,
            textColor=DARK,
            leading=9,
        ),
        "td": ParagraphStyle(
            "CrTdNl",
            fontName=_FONT_REG,
            fontSize=7.5,
            textColor=DARK,
            leading=9,
        ),
    }


def _box(paragraph: Paragraph, width: float, bg=STATUS_BG) -> Table:
    tbl = Table([[paragraph]], colWidths=[width])
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return tbl


def _metrics_table(rows: list[dict[str, str]], styles: dict[str, ParagraphStyle], width: float) -> Table:
    data = [[Paragraph("Kengetal", styles["th"]), Paragraph("Waarde", styles["th"])]]
    for row in rows:
        data.append(
            [
                Paragraph(_esc(row.get("label")), styles["td"]),
                Paragraph(_esc(row.get("value")), styles["td"]),
            ]
        )
    tbl = Table(data, colWidths=[width * 0.40, width * 0.60], repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return tbl


def build_client_report_pdf_bytes(presentation: dict[str, Any]) -> bytes:
    """Render presentation to Dutch PDF (A4). Presentation-only; does not rewrite stored AI body."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        title=str(presentation.get("title") or "Maandrapport"),
        author="Red Rock Agency — Bruine Beer",
    )
    usable = A4[0] - doc.leftMargin - doc.rightMargin
    story: list[Any] = []
    status = presentation.get("status") or {}

    story.append(Paragraph("Red Rock Agency · Maandelijks klantrapport", styles["brand"]))
    story.append(Paragraph(_esc(presentation.get("title") or "Maandrapport"), styles["title"]))
    story.append(
        Paragraph(
            f"Klant: <b>{_esc(presentation.get('client_name'))}</b> · "
            f"Verslagperiode: {_esc(presentation.get('period_label'))} · "
            f"Vergelijkingsperiode: {_esc(presentation.get('compare_label'))}",
            styles["meta"],
        )
    )
    story.append(
        Paragraph(
            f"Rapportversie v{_esc(presentation.get('version'))} · "
            f"Aangemaakt {_esc(presentation.get('created_at') or '—')} · "
            f"ID #{_esc(presentation.get('report_id'))}",
            styles["meta"],
        )
    )
    if presentation.get("content_source") == "approved_final":
        status_line = (
            f"Status: {status.get('label_pdf_nl') or 'Goedgekeurd'} · "
            f"{presentation.get('content_source_label_nl') or 'Menselijke eindversie (goedgekeurd)'}"
        )
    else:
        status_line = (
            f"Status: Draft / {status.get('label_pdf_nl') or status.get('label_nl') or 'Concept'} · "
            f"niet goedgekeurd"
        )
    story.append(_box(Paragraph(_esc(status_line), styles["status"]), usable))
    story.append(Spacer(1, 4))

    if presentation.get("content_source") == "approved_final":
        block = [
            Paragraph("Goedgekeurde eindversie", styles["h2"]),
            Paragraph(_esc(presentation.get("approved_final_text")), styles["body"]),
        ]
        story.append(KeepTogether(block))
    else:
        story.append(
            KeepTogether(
                [
                    Paragraph(
                        "Dit is een concept-PDF (Draft). Niet goedgekeurd voor de klant.",
                        styles["note"],
                    ),
                ]
            )
        )
        if presentation.get("show_summary") and presentation.get("summary"):
            story.append(
                KeepTogether(
                    [
                        Paragraph("Korte samenvatting", styles["h2"]),
                        Paragraph(_esc(presentation.get("summary")), styles["body"]),
                    ]
                )
            )

        metrics = presentation.get("key_metrics") or []
        if metrics:
            story.append(Paragraph("Kerncijfers", styles["h2"]))
            story.append(_metrics_table(metrics, styles, usable))

        if presentation.get("six_answers"):
            first = True
            for item in presentation["six_answers"]:
                parts = []
                if first:
                    parts.append(Paragraph("Zes analysevragen", styles["h2"]))
                    first = False
                parts.extend(
                    [
                        Paragraph(_esc(item.get("label_nl")), styles["h3"]),
                        Paragraph(
                            _esc(item.get("text_display") or item.get("text")),
                            styles["body"],
                        ),
                    ]
                )
                story.append(KeepTogether(parts))

        if presentation.get("chapters"):
            first = True
            for item in presentation["chapters"]:
                parts = []
                if first:
                    parts.append(Paragraph("Aanvullende hoofdstukken", styles["h2"]))
                    first = False
                parts.extend(
                    [
                        Paragraph(_esc(item.get("label_nl")), styles["h3"]),
                        Paragraph(
                            _esc(item.get("text_display") or item.get("text")),
                            styles["body"],
                        ),
                    ]
                )
                story.append(KeepTogether(parts))

        if presentation.get("action_plan"):
            first = True
            for item in presentation["action_plan"]:
                parts = []
                if first:
                    parts.append(Paragraph("Actieplan", styles["h2"]))
                    first = False
                parts.append(Paragraph(_esc(item.get("label_nl")), styles["h3"]))
                display_items = item.get("items_display") or item.get("items") or []
                if display_items:
                    for entry in display_items:
                        parts.append(Paragraph(f"• {_esc(entry)}", styles["body"]))
                elif item.get("text_display") or item.get("text"):
                    parts.append(
                        Paragraph(_esc(item.get("text_display") or item.get("text")), styles["body"])
                    )
                story.append(KeepTogether(parts))

        # Staff additions that were saved as report text (not personal feedback notes).
        for item in presentation.get("document_sections") or []:
            if item.get("group") != "addition":
                continue
            story.append(
                KeepTogether(
                    [
                        Paragraph(_esc(item.get("label_nl") or "Aanvulling"), styles["h3"]),
                        Paragraph(
                            _esc(item.get("text_display") or item.get("text")),
                            styles["body"],
                        ),
                    ]
                )
            )

    # Missing data: short note only on draft PDFs; never personal feedback or tech dumps.
    if presentation.get("content_source") != "approved_final":
        missing = presentation.get("missing_data") or []
        missing_sources = presentation.get("missing_sources") or []
        if missing or missing_sources:
            parts = [
                Paragraph("Ontbrekende gegevens", styles["h2"]),
                Paragraph(
                    "Beknopt overzicht. Persoonlijke feedback en technische gegevens staan niet in deze PDF.",
                    styles["note"],
                ),
            ]
            for item in missing[:8]:
                parts.append(Paragraph(f"• {_esc(item)}", styles["body"]))
            for item in missing_sources[:8]:
                parts.append(Paragraph(f"• {_esc(item)}", styles["body"]))
            story.append(KeepTogether(parts))

    story.append(
        Paragraph(
            "Persoonlijke feedback en technische details staan niet in deze klant-PDF.",
            styles["note"],
        )
    )

    def _footer(canvas, _doc) -> None:
        canvas.saveState()
        page = canvas.getPageNumber()
        canvas.setFont(_FONT_REG, 8)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(
            A4[0] / 2,
            9 * mm,
            f"Red Rock Agency · {presentation.get('client_name')} · "
            f"{status.get('label_pdf_nl') or status.get('label_nl')} · pagina {page}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def render_client_report_pdf(
    conn,
    client_id: int,
    report_id: int,
) -> tuple[bytes, dict[str, Any]]:
    from maaike.reports import get_report

    payload = get_report(conn, client_id, report_id)
    report = payload["report"]
    if report.get("report_type") != "client":
        raise ValueError("PDF export is currently available for client reports.")
    presentation = build_client_report_presentation(
        conn, client_id, report, review=payload.get("review") or {}
    )
    if not presentation.get("has_readable_content") and presentation.get("content_source") != "approved_final":
        presentation["summary"] = presentation.get("summary") or (
            report.get("error_text") or "Geen leesbare concepttekst beschikbaar voor dit rapport."
        )
        presentation["show_summary"] = True
    pdf = build_client_report_pdf_bytes(presentation)
    return pdf, presentation


def write_client_report_pdf(
    conn,
    client_id: int,
    report_id: int,
    dest: Path | str,
) -> dict[str, Any]:
    pdf, presentation = render_client_report_pdf(conn, client_id, report_id)
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf)
    return {
        "path": str(path.resolve()),
        "bytes": len(pdf),
        "report_id": report_id,
        "status": presentation.get("status"),
        "content_source": presentation.get("content_source"),
        "title": presentation.get("title"),
        "paid_ai": False,
    }
