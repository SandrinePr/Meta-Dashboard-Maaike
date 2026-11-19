"""Import client strategy from Canva URL (link-only) or PDF export — with preview.

Canva design pages are not scraped; Maaike pastes the design link and/or uploads the
PDF export. Preview never overwrites manual answers until she confirms save.
"""

from __future__ import annotations

import io
import re
from typing import Any
from urllib.parse import urlparse

from maaike.strategy import START_QUESTIONS, get_strategy, save_strategy

CANVA_HOSTS = {"canva.com", "www.canva.com"}

# Map Dutch/English headings in strategy PDFs → start_answers / strategy_fields keys
_FIELD_PATTERNS: list[tuple[str, str, str]] = [
    ("start_answers", "website", r"(?i)\bwebsite\b"),
    ("start_answers", "bedrijfsomschrijving", r"(?i)bedrijfsomschrijving|over (het )?bedrijf|wie zijn wij"),
    ("start_answers", "sectoren", r"(?i)\bsectoren?\b|branche"),
    ("start_answers", "geografische_regio", r"(?i)geografisch|werkgebied|regio"),
    ("start_answers", "producten_diensten", r"(?i)producten?\s*/?\s*diensten|aanbod"),
    ("start_answers", "onderscheidend_vermogen", r"(?i)onderscheid|usp|positionering"),
    ("start_answers", "gewenste_socialresultaten", r"(?i)social\s*doelen|gewenste social|kpi"),
    ("start_answers", "platforms", r"(?i)\bplatforms?\b|kanalen"),
    ("start_answers", "tone_of_voice", r"(?i)tone of voice|huisstijl|schrijfstijl"),
    ("start_answers", "beschikbaar_beeld", r"(?i)beeldmateriaal|beschikbaar beeld|fotobank"),
    ("start_answers", "frequentie_beperkingen", r"(?i)frequentie|plaatsingsfrequentie|beperkingen"),
    ("strategy_fields", "doelgroep", r"(?i)\bdoelgroep\b|target audience"),
    ("strategy_fields", "concurrenten", r"(?i)concurrent"),
    ("strategy_fields", "korte_termijn_doelen", r"(?i)korte\s*termijn|short.?term"),
    ("strategy_fields", "lange_termijn_doelen", r"(?i)lange\s*termijn|long.?term"),
    ("strategy_fields", "contentkeuzes", r"(?i)content(pijlers|keuzes)|pillars"),
    ("strategy_fields", "contactpersonen", r"(?i)contactpersoon|contactpersonen"),
    ("strategy_fields", "tags_samenwerkingen", r"(?i)\btags?\b|samenwerking|collab"),
    ("strategy_fields", "reactiebeleid", r"(?i)reactie|community.?beheer|moderatie"),
]


def _is_canva_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in CANVA_HOSTS or host.endswith(".canva.com")


def _split_sections(text: str) -> dict[str, str]:
    """Heuristic: split PDF text on heading-like lines."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    sections: dict[str, list[str]] = {"_preamble": []}
    current = "_preamble"
    for ln in lines:
        if not ln:
            continue
        if len(ln) < 80 and not ln.endswith(".") and re.match(r"^[A-Za-zÀ-ÿ0-9 /&\-]{3,}$", ln):
            current = ln
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(ln)
    return {k: "\n".join(v).strip() for k, v in sections.items() if v}


def _map_sections_to_fields(sections: dict[str, str]) -> dict[str, dict[str, str]]:
    start: dict[str, str] = {}
    fields: dict[str, str] = {}
    for heading, body in sections.items():
        blob = f"{heading}\n{body}"
        for bucket, key, pattern in _FIELD_PATTERNS:
            if re.search(pattern, heading) or re.search(pattern, body[:200]):
                target = start if bucket == "start_answers" else fields
                if key not in target and body.strip():
                    target[key] = body.strip()[:4000]
    # Fallback: put preamble into bedrijfsomschrijving if empty
    if "_preamble" in sections and "bedrijfsomschrijving" not in start:
        pre = sections["_preamble"].strip()
        if len(pre) > 40:
            start["bedrijfsomschrijving"] = pre[:4000]
    return {"start_answers": start, "strategy_fields": fields}


def extract_pdf_text(file_bytes: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def preview_canva_link(url: str) -> dict[str, Any]:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("Plak een Canva-link.")
    if not cleaned.startswith("http"):
        cleaned = "https://" + cleaned
    if not _is_canva_url(cleaned):
        raise ValueError("Dit lijkt geen Canva-link (canva.com).")
    return {
        "source_kind": "canva_url",
        "canva_url": cleaned,
        "readable": True,
        "content_extracted": False,
        "note": (
            "Canva-ontwerp zelf wordt niet uitgelezen. Bewaar de link als bron en upload "
            "desnoods de PDF-export voor tekstimport."
        ),
        "proposed": {
            "start_answers": {},
            "strategy_fields": {"canva_strategy_url": cleaned},
            "source_notes": [f"Canva-strategie: {cleaned}"],
        },
        "missing": [q["label"] for q in START_QUESTIONS],
        "open_questions": [
            "Exporteer de Canva-strategie als PDF om velden automatisch te vullen, of vul handmatig aan."
        ],
    }


def preview_strategy_pdf(file_bytes: bytes, *, filename: str = "") -> dict[str, Any]:
    if not file_bytes:
        raise ValueError("Leeg PDF-bestand.")
    text = extract_pdf_text(file_bytes)
    if not text:
        raise ValueError("Geen tekst uit PDF gelezen (scan/beeld?). Exporteer als tekst-PDF.")
    sections = _split_sections(text)
    mapped = _map_sections_to_fields(sections)
    filled = {**mapped["start_answers"], **mapped["strategy_fields"]}
    missing = [q["label"] for q in START_QUESTIONS if not mapped["start_answers"].get(q["key"])]
    return {
        "source_kind": "strategy_pdf",
        "filename": filename or "strategie.pdf",
        "readable": True,
        "content_extracted": True,
        "char_count": len(text),
        "section_headings": [k for k in sections if k != "_preamble"][:20],
        "excerpt": text[:1200],
        "proposed": {
            "start_answers": mapped["start_answers"],
            "strategy_fields": mapped["strategy_fields"],
            "source_notes": [f"PDF-strategie import: {filename or 'upload'}"],
        },
        "missing": missing,
        "open_questions": [
            "Controleer de preview. Handmatige antwoorden blijven behouden bij opslaan."
        ],
        "filled_keys": sorted(filled.keys()),
    }


def apply_strategy_import(
    conn,
    client_id: int,
    *,
    proposed: dict[str, Any],
    preserve_manual: bool = True,
) -> dict[str, Any]:
    """Merge proposed preview into strategy. Never wipe manual answers when preserve_manual."""
    current = get_strategy(conn, client_id)
    answers = dict(current["start_answers"] or {})
    fields = dict(current["strategy_fields"] or {})
    notes = list(current["source_notes"] or [])

    for key, value in (proposed.get("start_answers") or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        if preserve_manual and str(answers.get(key) or "").strip():
            # keep existing
            continue
        answers[key] = text
    for key, value in (proposed.get("strategy_fields") or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        if preserve_manual and str(fields.get(key) or "").strip() and key != "canva_strategy_url":
            continue
        fields[key] = text
    for note in proposed.get("source_notes") or []:
        if note and note not in notes:
            notes.append(note)

    return save_strategy(
        conn,
        client_id,
        account_info=current["account_info"],
        start_answers=answers,
        strategy_fields=fields,
        source_notes=notes,
        mark_complete=False,
    )


def strategy_overview(conn, client_id: int) -> dict[str, Any]:
    """Structured overview for Targets & Strategy (what Maaike sees at a glance)."""
    data = get_strategy(conn, client_id)
    answers = data["start_answers"] or {}
    fields = data["strategy_fields"] or {}
    sections = [
        {
            "id": "bedrijfscontext",
            "title": "Bedrijfscontext",
            "items": [
                {"label": "Website", "value": answers.get("website") or ""},
                {"label": "Omschrijving", "value": answers.get("bedrijfsomschrijving") or ""},
                {"label": "Sectoren", "value": answers.get("sectoren") or ""},
                {"label": "Regio", "value": answers.get("geografische_regio") or ""},
                {"label": "Producten/diensten", "value": answers.get("producten_diensten") or ""},
            ],
        },
        {
            "id": "doelgroep_onderscheid",
            "title": "Doelgroep, onderscheid & concurrenten",
            "items": [
                {"label": "Doelgroep", "value": fields.get("doelgroep") or ""},
                {"label": "Onderscheid", "value": answers.get("onderscheidend_vermogen") or ""},
                {"label": "Concurrenten", "value": fields.get("concurrenten") or ""},
            ],
        },
        {
            "id": "doelen",
            "title": "Doelen",
            "items": [
                {"label": "Korte termijn", "value": fields.get("korte_termijn_doelen") or ""},
                {"label": "Lange termijn", "value": fields.get("lange_termijn_doelen") or ""},
                {"label": "Socialdoelen", "value": answers.get("gewenste_socialresultaten") or ""},
            ],
        },
        {
            "id": "content_platforms",
            "title": "Content, platforms & frequentie",
            "items": [
                {"label": "Contentkeuzes", "value": fields.get("contentkeuzes") or ""},
                {"label": "Platforms", "value": answers.get("platforms") or ""},
                {"label": "Frequentie/beperkingen", "value": answers.get("frequentie_beperkingen") or ""},
            ],
        },
        {
            "id": "stijl_beeld",
            "title": "Huisstijl, tone of voice & beeld",
            "items": [
                {"label": "Tone of voice", "value": answers.get("tone_of_voice") or fields.get("tone_of_voice") or ""},
                {"label": "Beschikbaar beeld", "value": answers.get("beschikbaar_beeld") or ""},
                {"label": "Nieuw materiaal", "value": answers.get("nieuw_materiaal") or ""},
            ],
        },
        {
            "id": "afspraken",
            "title": "Contact, tags, samenwerkingen & reacties",
            "items": [
                {"label": "Contactpersonen", "value": fields.get("contactpersonen") or ""},
                {"label": "Tags/samenwerkingen", "value": fields.get("tags_samenwerkingen") or ""},
                {"label": "Reactiebeleid", "value": fields.get("reactiebeleid") or ""},
                {"label": "Canva-bron", "value": fields.get("canva_strategy_url") or ""},
            ],
        },
    ]
    missing = []
    for section in sections:
        for item in section["items"]:
            if not str(item["value"] or "").strip():
                missing.append(f"{section['title']}: {item['label']}")
    return {
        **data,
        "overview_sections": sections,
        "missing_overview": missing,
        "canva_url": fields.get("canva_strategy_url") or "",
    }
