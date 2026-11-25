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


# Creative-brief scaffolding in Figma planning files — not strategy answers.
_CREATIVE_BRIEF_NOISE = re.compile(
    r"(?i)content\s*format|contentpijler|hook\s*/\s*tekst|beeldmateriaal\s*omschrijving|"
    r"inspiratie\s*/\s*voorbeeld|wat moet de gebruiker|caption\s*bij|insta\s*-\s*(post|reel)|"
    r"hier in te vullen|niet van toepassing|nvt\b"
)


def _is_creative_brief_noise(heading: str, body: str) -> bool:
    blob = f"{heading}\n{body}"
    hits = len(_CREATIVE_BRIEF_NOISE.findall(blob))
    return hits >= 2 or bool(_CREATIVE_BRIEF_NOISE.search(heading or ""))


def _trim_creative_tail(body: str) -> str:
    """Keep strategy prose; stop once creative-brief scaffolding starts."""
    lines: list[str] = []
    for ln in (body or "").splitlines():
        if _CREATIVE_BRIEF_NOISE.search(ln):
            break
        lines.append(ln)
    return "\n".join(lines).strip()


# Strict Figma strategy headings only — creatives often contain the word "website"/"regio"
# inside captions; those must not become strategy proposals.
_FIGMA_HEADING_ALIASES: dict[str, tuple[str, ...]] = {
    "website": (r"(?i)^website$", r"(?i)^onze website$"),
    "bedrijfsomschrijving": (r"(?i)^bedrijfsomschrijving$", r"(?i)^over (het )?bedrijf$"),
    "sectoren": (r"(?i)^sectoren?$", r"(?i)^branche$"),
    "geografische_regio": (r"(?i)^geografisch(e)? (werkgebied|regio)$", r"(?i)^werkgebied$", r"(?i)^regio$"),
    "producten_diensten": (r"(?i)^producten?\s*/?\s*diensten$", r"(?i)^aanbod$"),
    "onderscheidend_vermogen": (r"(?i)^onderscheidend vermogen$", r"(?i)^usp$", r"(?i)^positionering$"),
    "gewenste_socialresultaten": (r"(?i)^gewenste social(resultaten)?$", r"(?i)^social doelen$", r"(?i)^kpis?$"),
    "platforms": (r"(?i)^platforms?$", r"(?i)^kanalen$"),
    "tone_of_voice": (r"(?i)^tone of voice$", r"(?i)^huisstijl$", r"(?i)^schrijfstijl$"),
    "beschikbaar_beeld": (r"(?i)^beschikbaar beeld(-| )?materiaal$", r"(?i)^fotobank$"),
    "frequentie_beperkingen": (r"(?i)^plaatsingsfrequentie$", r"(?i)^frequentie$", r"(?i)^beperkingen$"),
    "doelgroep": (r"(?i)^doelgroep$", r"(?i)^target audience$"),
    "concurrenten": (r"(?i)^concurrenten$", r"(?i)^concurrentie$"),
    "korte_termijn_doelen": (r"(?i)^korte[- ]?termijn(s)?( doelen)?$",),
    "lange_termijn_doelen": (r"(?i)^lange[- ]?termijn(s)?( doelen)?$",),
    "contentkeuzes": (r"(?i)^content(pijlers|keuzes)$", r"(?i)^pillars$"),
    "contactpersonen": (r"(?i)^contactpersonen$", r"(?i)^contactpersoon$"),
    "tags_samenwerkingen": (r"(?i)^tags$", r"(?i)^samenwerkingen$"),
    "reactiebeleid": (r"(?i)^reactiebeleid$", r"(?i)^community.?beheer$"),
}


def _heading_is_field_label(heading: str, pattern: str, *, key: str = "", strict: bool = False) -> bool:
    """True when the heading is essentially the field label, not a caption fragment."""
    h = (heading or "").strip()
    if not h or len(h) > 48:
        return False
    if strict:
        aliases = _FIGMA_HEADING_ALIASES.get(key) or ()
        return any(re.fullmatch(alias, h) for alias in aliases)
    match = re.search(pattern, h)
    if not match:
        return False
    remainder = (h[: match.start()] + h[match.end() :]).strip(" \t:-–—|/&,.")
    return len(remainder) <= 12


def _map_sections_to_fields(
    sections: dict[str, str],
    *,
    heading_only: bool = False,
    allow_preamble_fallback: bool = True,
) -> dict[str, dict[str, str]]:
    start: dict[str, str] = {}
    fields: dict[str, str] = {}
    for heading, body in sections.items():
        if heading == "_preamble":
            continue
        clean_body = _trim_creative_tail(body) if heading_only else (body or "").strip()
        if not clean_body:
            continue
        if _is_creative_brief_noise(heading, clean_body):
            continue
        for bucket, key, pattern in _FIELD_PATTERNS:
            if heading_only:
                heading_hit = _heading_is_field_label(
                    heading, pattern, key=key, strict=True
                )
                body_hit = False
            else:
                heading_hit = bool(re.search(pattern, heading))
                body_hit = bool(re.search(pattern, clean_body[:200]))
            if heading_hit or body_hit:
                target = start if bucket == "start_answers" else fields
                if key not in target:
                    target[key] = clean_body[:4000]
    # Fallback: put preamble into bedrijfsomschrijving if empty (PDF strategy docs).
    if allow_preamble_fallback and "_preamble" in sections and "bedrijfsomschrijving" not in start:
        pre = sections["_preamble"].strip()
        if len(pre) > 40 and not _is_creative_brief_noise("_preamble", pre):
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
        "link_import_available": False,
        "note": (
            "Deze Canva-link kan niet worden uitgelezen. Directe linkimport staat nog open. "
            "Exporteer de strategie als PDF en gebruik ‘Voorstellen ophalen via PDF’, "
            "of vul handmatig in."
        ),
        "proposed": {
            "start_answers": {},
            "strategy_fields": {"canva_strategy_url": cleaned},
            "source_notes": [f"Canva-strategie: {cleaned}"],
            "field_sources": {},
        },
        "missing": [q["label"] for q in START_QUESTIONS],
        "open_questions": [
            "Directe Canva-linkimport staat nog open. Exporteer intussen als PDF of vul handmatig aan."
        ],
        "filled_keys": [],
    }


def _platform_label(hint: str) -> str:
    raw = str(hint or "").strip().lower()
    if not raw:
        return ""
    if "insta" in raw:
        return "Instagram"
    if "face" in raw or raw == "fb":
        return "Facebook"
    if "linked" in raw:
        return "LinkedIn"
    if "tiktok" in raw:
        return "TikTok"
    return str(hint).strip()[:80]


def preview_figma_strategy(
    conn,
    client_id: int,
    *,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Propose strategy fills only from text/planning that is demonstrably in Figma.

    Creatives-only files may yield contentkeuzes/platforms from briefs, never invented
    doelgroep or bedrijfsdoelen.
    """
    from maaike.figma_planning import (
        collect_all_text_from_figma_document,
        extract_items_from_figma_document,
        fetch_figma_file,
        get_figma_connection,
        is_usable_classification,
    )

    link = get_figma_connection(conn, client_id)
    if not link.get("linked"):
        raise ValueError("Koppel eerst een Figma-bestand bij deze klant.")
    file_key = str(link.get("file_key") or "").strip()
    doc = document if isinstance(document, dict) else fetch_figma_file(file_key)

    text = collect_all_text_from_figma_document(doc)
    sections = _split_sections(text) if text else {}
    # Figma creatives are noisy: only map clear strategy headings, never brief scaffolding.
    mapped = (
        _map_sections_to_fields(
            sections,
            heading_only=True,
            allow_preamble_fallback=False,
        )
        if sections
        else {"start_answers": {}, "strategy_fields": {}}
    )
    start = dict(mapped["start_answers"])
    fields = dict(mapped["strategy_fields"])
    field_sources: dict[str, str] = {
        key: "Figma-tekst (strategie-kop in het bestand)"
        for key in list(start.keys()) + list(fields.keys())
    }

    items = extract_items_from_figma_document(doc, file_key)
    pillars = sorted(
        {
            str(item.get("pillar_raw") or "").strip()
            for item in items
            if item.get("pillar_usable") and is_usable_classification(item.get("pillar_raw"))
        }
    )
    platforms = sorted(
        {
            label
            for item in items
            if (label := _platform_label(item.get("platform_hint") or ""))
        }
    )
    if pillars and not str(fields.get("contentkeuzes") or "").strip():
        fields["contentkeuzes"] = "Contentpijlers uit Figma-planning: " + ", ".join(pillars)
        field_sources["contentkeuzes"] = "Figma-planning · Contentpijler"
    if platforms and not str(start.get("platforms") or "").strip():
        start["platforms"] = ", ".join(platforms)
        field_sources["platforms"] = "Figma-planning · platform in brief"

    filled = {**start, **fields}
    missing = [q["label"] for q in START_QUESTIONS if not start.get(q["key"])]
    notes = [
        f"Figma-bron: {link.get('source_url') or file_key}",
        f"{len(items)} planning-item(s) gelezen; {len(text)} tekens platte tekst.",
    ]
    if not filled:
        notes.append(
            "Geen strategievelden gevonden. Een Figma met alleen creatives levert "
            "geen doelgroep of bedrijfsdoelen op."
        )
    return {
        "source_kind": "figma",
        "file_key": file_key,
        "source_url": link.get("source_url") or "",
        "readable": True,
        "content_extracted": bool(text or items),
        "char_count": len(text),
        "planning_item_count": len(items),
        "section_headings": [k for k in sections if k != "_preamble"][:20],
        "excerpt": text[:1200],
        "proposed": {
            "start_answers": start,
            "strategy_fields": fields,
            "source_notes": notes,
            "field_sources": field_sources,
        },
        "missing": missing,
        "open_questions": [
            "Controleer de voorstellen. Alleen lege velden worden gevuld na goedkeuring.",
            "Velden die niet in Figma staan (bijv. doelgroep) blijven leeg.",
        ],
        "filled_keys": sorted(filled.keys()),
        "note": (
            "Voorstellen komen alleen uit tekst en planninglabels die in Figma staan."
            if filled
            else "Geen bruikbare strategie-informatie in dit Figma-bestand."
        ),
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
    field_sources = {
        key: f"PDF-strategie ({filename or 'upload'})" for key in filled
    }
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
            "field_sources": field_sources,
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
    stage_only: bool = True,
    source_kind: str = "",
    filename: str = "",
    file_ref: str = "",
) -> dict[str, Any]:
    """Stage or merge a preview. Default: stage as proposal until the editor approves.

    Manual answers stay untouched. Canva URL may be saved immediately (optional link only).
    """
    current = get_strategy(conn, client_id)
    answers = dict(current["start_answers"] or {})
    fields = dict(current["strategy_fields"] or {})
    notes = list(current["source_notes"] or [])

    proposed_answers = {
        k: str(v).strip()
        for k, v in (proposed.get("start_answers") or {}).items()
        if str(v or "").strip()
    }
    proposed_fields = {
        k: str(v).strip()
        for k, v in (proposed.get("strategy_fields") or {}).items()
        if str(v or "").strip()
    }

    # Optional Canva link is not a content proposal — store immediately.
    canva = str(proposed_fields.pop("canva_strategy_url", "") or proposed_fields.pop("canva_url", "") or "").strip()
    if canva:
        fields["canva_strategy_url"] = canva

    activated_pdf: dict[str, Any] | None = None
    if file_ref:
        from maaike.strategy_files import activate_strategy_pdf

        activated_pdf = activate_strategy_pdf(conn, client_id, file_ref, filename=filename)

    if activated_pdf is not None:
        fields["strategy_pdf_ref"] = activated_pdf["file_ref"]
        fields["last_pdf_meta"] = {
            "filename": activated_pdf["filename"],
            "source_kind": source_kind or "strategy_pdf",
            "file_ref": activated_pdf["file_ref"],
            "byte_size": activated_pdf["byte_size"],
            "updated_at": activated_pdf["updated_at"],
        }
    elif filename or source_kind == "strategy_pdf":
        existing_meta = dict(fields.get("last_pdf_meta") or {})
        fields["last_pdf_meta"] = {
            **existing_meta,
            "filename": filename or existing_meta.get("filename") or "strategie.pdf",
            "source_kind": source_kind or existing_meta.get("source_kind") or "strategy_pdf",
        }

    if stage_only:
        # Drop keys the editor already filled manually when preserve_manual.
        if preserve_manual:
            proposed_answers = {
                k: v
                for k, v in proposed_answers.items()
                if not str(answers.get(k) or "").strip()
            }
            proposed_fields = {
                k: v
                for k, v in proposed_fields.items()
                if not str(fields.get(k) or "").strip()
            }
        has_proposal_content = bool(proposed_answers or proposed_fields)
        if has_proposal_content:
            fields["pending_proposal"] = {
                "start_answers": proposed_answers,
                "strategy_fields": proposed_fields,
                "source_notes": list(proposed.get("source_notes") or []),
                "field_sources": dict(proposed.get("field_sources") or {}),
                "source_kind": source_kind or "import",
                "filename": filename or "",
                "preserve_manual": bool(preserve_manual),
            }
            fields["review_status"] = "te_controleren"
        else:
            # PDF/Canva meta may still be stored; no empty proposal that blocks afronden.
            fields.pop("pending_proposal", None)
            if fields.get("review_status") == "te_controleren":
                fields["review_status"] = "concept"
        return save_strategy(
            conn,
            client_id,
            account_info=current["account_info"],
            start_answers=answers,
            strategy_fields=fields,
            source_notes=notes,
            mark_complete=False,
        )

    # Legacy immediate merge path (still never overwrites filled answers when preserve_manual).
    provenance_updates: dict[str, str] = {}
    for key, text in proposed_answers.items():
        if preserve_manual and str(answers.get(key) or "").strip():
            continue
        answers[key] = text
        provenance_updates[key] = "hamster"
    for key, text in proposed_fields.items():
        if preserve_manual and str(fields.get(key) or "").strip():
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
        provenance_updates=provenance_updates,
    )


def approve_strategy_proposal(
    conn,
    client_id: int,
    *,
    edited_proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge staged proposal into the saved strategy after editor approval."""
    current = get_strategy(conn, client_id)
    fields = dict(current["strategy_fields"] or {})
    pending = edited_proposal or fields.get("pending_proposal")
    if not isinstance(pending, dict):
        raise ValueError("Er is geen voorstel om goed te keuren.")
    answers = dict(current["start_answers"] or {})
    notes = list(current["source_notes"] or [])
    preserve_manual = bool(pending.get("preserve_manual", True))
    provenance_updates: dict[str, str] = {}

    for key, value in (pending.get("start_answers") or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        if preserve_manual and str(answers.get(key) or "").strip():
            continue
        answers[key] = text
        provenance_updates[key] = "approved"
    for key, value in (pending.get("strategy_fields") or {}).items():
        text = str(value or "").strip()
        if not text or key in {"canva_strategy_url", "canva_url"}:
            continue
        if preserve_manual and str(fields.get(key) or "").strip():
            continue
        fields[key] = text
    for note in pending.get("source_notes") or []:
        if note and note not in notes:
            notes.append(note)

    fields.pop("pending_proposal", None)
    fields["review_status"] = "concept"
    return save_strategy(
        conn,
        client_id,
        account_info=current["account_info"],
        start_answers=answers,
        strategy_fields=fields,
        source_notes=notes,
        mark_complete=False,
        provenance_updates=provenance_updates,
    )


def discard_strategy_proposal(conn, client_id: int) -> dict[str, Any]:
    """Drop staged proposal without changing saved answers."""
    current = get_strategy(conn, client_id)
    fields = dict(current["strategy_fields"] or {})
    if "pending_proposal" not in fields:
        return current
    fields.pop("pending_proposal", None)
    fields["review_status"] = "concept"
    return save_strategy(
        conn,
        client_id,
        account_info=current["account_info"],
        start_answers=current["start_answers"],
        strategy_fields=fields,
        source_notes=current["source_notes"],
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
        "canva_url": data.get("canva_url") or fields.get("canva_strategy_url") or "",
    }
