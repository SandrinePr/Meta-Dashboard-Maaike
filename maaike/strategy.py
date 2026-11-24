"""Start questions, strategy fields and targets for one client."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def _pending_user_questions(answers: dict[str, str]) -> list[dict[str, Any]]:
    """Concrete open questions; keep known source text but still ask for gaps."""
    pending: list[dict[str, Any]] = []
    for question in START_QUESTIONS:
        key = question["key"]
        value = str(answers.get(key) or "").strip()
        required = bool(question["required_for_complete"])
        if not value:
            pending.append(
                {
                    "key": key,
                    "question": question.get("short_question") or question["label"],
                    "required": required,
                }
            )
            continue
        lowered = value.lower()
        if key == "geografische_regio" and (
            "niet expliciet" in lowered or "open" in lowered or "onbekend" in lowered
        ):
            pending.append(
                {
                    "key": key,
                    "question": question.get("short_question") or question["label"],
                    "required": True,
                }
            )
    return pending


START_QUESTIONS = [
    {
        "key": "website",
        "label": "Website",
        "short_question": "Wat is de website van deze klant?",
        "required_for_complete": True,
    },
    {
        "key": "bedrijfsomschrijving",
        "label": "Bedrijfsomschrijving",
        "short_question": "Hoe omschrijven jullie dit bedrijf kort?",
        "required_for_complete": True,
    },
    {
        "key": "sectoren",
        "label": "Sectoren",
        "short_question": "Voor welke sectoren werkt deze klant?",
        "required_for_complete": True,
    },
    {
        "key": "geografische_regio",
        "label": "Geografisch werkgebied",
        "short_question": "Wat is het geografische werkgebied? (Alleen invullen als dit vaststaat.)",
        "required_for_complete": True,
    },
    {
        "key": "producten_diensten",
        "label": "Producten / diensten",
        "short_question": "Welke producten/diensten biedt deze klant aan?",
        "required_for_complete": True,
    },
    {
        "key": "onderscheidend_vermogen",
        "label": "Onderscheidend vermogen",
        "short_question": "Wat maakt dit merk onderscheidend?",
        "required_for_complete": True,
    },
    {
        "key": "gewenste_socialresultaten",
        "label": "Gewenste socialresultaten",
        "short_question": "Welke socialresultaten willen jullie bereiken (bereik, leads, employer branding, …)?",
        "required_for_complete": True,
    },
    {
        "key": "platforms",
        "label": "Platforms",
        "short_question": "Welke platforms en accountlabels gelden voor deze klant?",
        "required_for_complete": True,
    },
    {
        "key": "tone_of_voice",
        "label": "Tone of voice",
        "short_question": "Wat is de tone of voice? Pas een voorstel gerust aan.",
        "required_for_complete": True,
    },
    {
        "key": "beschikbaar_beeld",
        "label": "Beschikbaar beeld- en videomateriaal",
        "short_question": "Welk beeld- en videomateriaal is al beschikbaar?",
        "required_for_complete": False,
    },
    {
        "key": "nieuw_materiaal",
        "label": "Mogelijkheid om nieuw materiaal te maken en mensen in beeld te brengen",
        "short_question": "Kunnen jullie nieuw materiaal maken en mensen in beeld brengen?",
        "required_for_complete": False,
    },
    {
        "key": "frequentie_beperkingen",
        "label": "Plaatsingsfrequentie en praktische beperkingen",
        "short_question": "Wat is de gewenste plaatsingsfrequentie, en welke praktische beperkingen zijn er?",
        "required_for_complete": False,
    },
]

# Internal strategy_fields keys — not shown as free-text strategy fields in the UI.
STRATEGY_META_KEYS = {
    "pending_proposal",
    "answer_provenance",
    "field_provenance",
    "review_status",
    "last_pdf_meta",
    "strategy_pdf_ref",
    "canva_strategy_url",
    "canva_url",
}


def _is_manual_answer(value: str) -> bool:
    """Treat non-empty answers without auto-source markers as manual (do not overwrite)."""
    text = str(value or "").strip()
    if not text:
        return False
    markers = (
        "bron: red-rock-agency",
        "bron: https://redrockagency.nl",
        "website niet expliciet",
        "regio niet expliciet",
        "open laten",
        "(bron:",
    )
    lowered = text.lower()
    return not any(marker in lowered for marker in markers)


def _merge_answer(existing: dict[str, str], key: str, value: str) -> None:
    current = str(existing.get(key) or "").strip()
    if _is_manual_answer(current):
        return
    if value.strip():
        existing[key] = value.strip()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _infer_provenance(value: str) -> str:
    """Guess source of an already stored answer when no explicit provenance exists."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.upper().startswith("HAMSTER-HANDMATIG"):
        return "editor"
    markers = ("(bron:", "bron:", "red-rock-agency", "redrockagency.nl", "pdf-strategie")
    lowered = text.lower()
    if any(marker in lowered for marker in markers):
        return "hamster"
    return "editor"


def _public_strategy_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (fields or {}).items() if k not in STRATEGY_META_KEYS}


def _build_field_status(
    *,
    answers: dict[str, Any],
    fields: dict[str, Any],
    pending_proposal: dict[str, Any] | None,
) -> dict[str, Any]:
    provenance = dict((fields or {}).get("answer_provenance") or {})
    proposed_answers = dict((pending_proposal or {}).get("start_answers") or {})
    editor_filled: list[dict[str, str]] = []
    hamster_ready: list[dict[str, str]] = []
    missing_required: list[dict[str, str]] = []
    for question in START_QUESTIONS:
        key = question["key"]
        label = question["label"]
        value = str(answers.get(key) or "").strip()
        proposed = str(proposed_answers.get(key) or "").strip()
        source = str(provenance.get(key) or "").strip() or (_infer_provenance(value) if value else "")
        if value and source == "editor":
            editor_filled.append({"key": key, "label": label, "value": value})
        elif value and source in {"hamster", "approved"}:
            hamster_ready.append(
                {
                    "key": key,
                    "label": label,
                    "value": value,
                    "state": "opgenomen" if source == "approved" else "voorstel_opgenomen",
                }
            )
        elif proposed:
            hamster_ready.append(
                {
                    "key": key,
                    "label": label,
                    "value": proposed,
                    "state": "te_controleren",
                }
            )
        elif question.get("required_for_complete") and not value:
            missing_required.append({"key": key, "label": label})
        elif value:
            # Unknown provenance with content → treat as editor-owned.
            editor_filled.append({"key": key, "label": label, "value": value})
    return {
        "editor_filled": editor_filled,
        "hamster_proposals": hamster_ready,
        "missing_required_items": missing_required,
    }


def resolve_review_status(
    *,
    completed_at: str | None,
    fields: dict[str, Any],
    answers: dict[str, Any],
    pending_proposal: dict[str, Any] | None,
) -> str:
    explicit = str((fields or {}).get("review_status") or "").strip().lower()
    if completed_at:
        return "definitief"
    if pending_proposal:
        return "te_controleren"
    if explicit in {"concept", "te_controleren", "definitief"}:
        return explicit
    if any(str(v or "").strip() for v in (answers or {}).values()):
        return "concept"
    return "concept"


def get_strategy(conn, client_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM client_strategy WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if row is None:
        from maaike.strategy_files import resolve_strategy_pdf_status

        pending = _pending_user_questions({})
        empty_fields: dict[str, Any] = {}
        status = _build_field_status(answers={}, fields=empty_fields, pending_proposal=None)
        pdf_status = resolve_strategy_pdf_status(conn, client_id, empty_fields)
        return {
            "account_info": {},
            "start_answers": {},
            "strategy_fields": {},
            "public_strategy_fields": {},
            "source_notes": [],
            "completed_at": None,
            "updated_at": None,
            "questions": START_QUESTIONS,
            "pending_questions": pending,
            "targets": list_targets(conn, client_id),
            "missing_required": [item["key"] for item in pending if item.get("required")],
            "review_status": "concept",
            "review_status_label": "Concept",
            "pending_proposal": None,
            "canva_url": "",
            "last_pdf_meta": None,
            "strategy_pdf": pdf_status,
            "editor_filled": status["editor_filled"],
            "hamster_proposals": status["hamster_proposals"],
            "missing_required_items": status["missing_required_items"],
            "next_step": "Vul de verplichte vragen in, of lees een PDF-voorstel in ter controle.",
        }
    from maaike.strategy_files import resolve_strategy_pdf_status

    answers = json.loads(row["start_answers_json"] or "{}")
    fields = json.loads(row["strategy_fields_json"] or "{}")
    pdf_status = resolve_strategy_pdf_status(conn, client_id, fields)
    pending_proposal = fields.get("pending_proposal")
    if isinstance(pending_proposal, dict) and not (
        pending_proposal.get("start_answers") or pending_proposal.get("strategy_fields")
    ):
        pending_proposal = None
    pending = _pending_user_questions(answers)
    missing = [item["key"] for item in pending if item.get("required")]
    review_status = resolve_review_status(
        completed_at=row["completed_at"],
        fields=fields,
        answers=answers,
        pending_proposal=pending_proposal if isinstance(pending_proposal, dict) else None,
    )
    status = _build_field_status(
        answers=answers,
        fields=fields,
        pending_proposal=pending_proposal if isinstance(pending_proposal, dict) else None,
    )
    if review_status == "definitief":
        next_step = "Strategie is definitief. Pas velden aan als er iets wijzigt; markeer opnieuw als nodig."
    elif review_status == "te_controleren":
        next_step = "Controleer het HAMSTER-voorstel, pas aan waar nodig en keur het goed."
    elif status["missing_required_items"]:
        next_step = (
            "Vul de ontbrekende verplichte informatie in, of lees een PDF in voor voorstellen."
        )
    else:
        next_step = "Alles vereiste staat erin — markeer de strategie als definitief als die klopt."
    label_map = {
        "concept": "Concept",
        "te_controleren": "Te controleren",
        "definitief": "Definitief",
    }
    return {
        "account_info": json.loads(row["account_info_json"] or "{}"),
        "start_answers": answers,
        "strategy_fields": fields,
        "public_strategy_fields": _public_strategy_fields(fields),
        "source_notes": json.loads(row["source_notes_json"] or "[]"),
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
        "questions": START_QUESTIONS,
        "pending_questions": pending,
        "targets": list_targets(conn, client_id),
        "missing_required": missing,
        "review_status": review_status,
        "review_status_label": label_map.get(review_status, "Concept"),
        "pending_proposal": pending_proposal if isinstance(pending_proposal, dict) else None,
        "canva_url": str(fields.get("canva_strategy_url") or fields.get("canva_url") or "").strip(),
        "last_pdf_meta": fields.get("last_pdf_meta"),
        "strategy_pdf": pdf_status,
        "editor_filled": status["editor_filled"],
        "hamster_proposals": status["hamster_proposals"],
        "missing_required_items": status["missing_required_items"],
        "next_step": next_step,
    }


def save_strategy(
    conn,
    client_id: int,
    *,
    account_info: dict | None = None,
    start_answers: dict | None = None,
    strategy_fields: dict | None = None,
    source_notes: list | None = None,
    mark_complete: bool = False,
    clear_complete: bool = False,
    provenance_updates: dict[str, str] | None = None,
) -> dict[str, Any]:
    current = get_strategy(conn, client_id)
    account = account_info if account_info is not None else current["account_info"]
    answers = dict(start_answers if start_answers is not None else current["start_answers"])
    existing_fields = dict(current.get("strategy_fields") or {})
    if strategy_fields is not None:
        fields = dict(strategy_fields)
        # Preserve server-managed PDF reference if the caller sent an older strategy_fields snapshot.
        for meta_key in ("last_pdf_meta", "strategy_pdf_ref"):
            if meta_key not in fields and meta_key in existing_fields:
                fields[meta_key] = existing_fields[meta_key]
    else:
        fields = existing_fields
    notes = source_notes if source_notes is not None else current["source_notes"]
    pending = _pending_user_questions(answers)
    missing = [item["question"] for item in pending if item.get("required")]
    completed_at = current["completed_at"]
    if clear_complete:
        completed_at = None
        fields["review_status"] = "concept"
    if mark_complete:
        if missing:
            raise ValueError(
                "Strategie-afronding vereist nog antwoorden op: " + " | ".join(missing)
            )
        pending_block = fields.get("pending_proposal")
        if isinstance(pending_block, dict) and (
            pending_block.get("start_answers") or pending_block.get("strategy_fields")
        ):
            raise ValueError(
                "Er staat nog een voorstel klaar ter controle. Keur het goed of verwerp het "
                "voordat je de strategie definitief maakt."
            )
        if "pending_proposal" in fields:
            fields.pop("pending_proposal", None)
        completed_at = _now()
        fields["review_status"] = "definitief"

    provenance = dict(fields.get("answer_provenance") or {})
    previous_answers = dict(current.get("start_answers") or {})
    for key, value in answers.items():
        text = str(value or "").strip()
        prev = str(previous_answers.get(key) or "").strip()
        if text != prev:
            if provenance_updates and key in provenance_updates:
                provenance[key] = provenance_updates[key]
            elif text:
                # Editor edits become editor-owned unless caller sets provenance.
                provenance[key] = provenance.get(key) if text == prev else "editor"
                if text != prev:
                    provenance[key] = "editor"
            elif key in provenance:
                provenance.pop(key, None)
    if provenance_updates:
        for key, source in provenance_updates.items():
            if str(answers.get(key) or "").strip():
                provenance[key] = source
    fields["answer_provenance"] = provenance

    pending_proposal = fields.get("pending_proposal")
    if isinstance(pending_proposal, dict) and (
        pending_proposal.get("start_answers") or pending_proposal.get("strategy_fields")
    ):
        if not completed_at:
            fields["review_status"] = "te_controleren"
    elif not completed_at:
        fields["review_status"] = str(fields.get("review_status") or "concept")
        if fields["review_status"] == "te_controleren":
            fields["review_status"] = "concept"

    now = _now()
    conn.execute(
        """
        INSERT INTO client_strategy (
            client_id, account_info_json, start_answers_json, strategy_fields_json,
            source_notes_json, completed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            account_info_json = excluded.account_info_json,
            start_answers_json = excluded.start_answers_json,
            strategy_fields_json = excluded.strategy_fields_json,
            source_notes_json = excluded.source_notes_json,
            completed_at = excluded.completed_at,
            updated_at = excluded.updated_at
        """,
        (
            client_id,
            json.dumps(account, ensure_ascii=False),
            json.dumps(answers, ensure_ascii=False),
            json.dumps(fields, ensure_ascii=False),
            json.dumps(notes, ensure_ascii=False),
            completed_at,
            now,
        ),
    )
    return get_strategy(conn, client_id)


def enrich_red_rock_from_website(answers: dict[str, str], fields: dict[str, str], notes: list[dict[str, str]]) -> None:
    """Fill only facts stated on redrockagency.nl. Never invent social goals or region work area."""
    website = "https://redrockagency.nl/"
    _merge_answer(answers, "website", f"{website} (bron: https://redrockagency.nl/)")
    _merge_answer(
        answers,
        "bedrijfsomschrijving",
        (
            "Strategisch-creatieve partner / marketing agency die merken helpt groeien met "
            "online marketing die creativiteit, innovatie en technologie verbindt. "
            "(bron: https://redrockagency.nl/ en https://redrockagency.nl/over-ons/)"
        ),
    )
    _merge_answer(
        answers,
        "sectoren",
        (
            "Hospitality- en woonbranche; woon- en lifestylebranche; "
            "in social TOV ook wonen, interieur en outdoor als sectorcontext. "
            "(bron: https://redrockagency.nl/over-ons/, https://redrockagency.nl/, "
            "Red-rock-agency.docx — dit zijn sectoren, geen regio’s)"
        ),
    )
    # Contact address is not the same as geographic work area — leave open unless explicit.
    if not str(answers.get("geografische_regio") or "").strip():
        answers["geografische_regio"] = (
            "Niet expliciet als geografisch werkgebied vermeld op de website. "
            "Wel contactadres: Heiberg 10, 5504PB Veldhoven (bron: https://redrockagency.nl/contact/) — "
            "dat is geen bewezen werkgebied; open laten tot jullie dit bevestigen."
        )
    _merge_answer(
        answers,
        "producten_diensten",
        (
            "Merkidentiteit; Branding; Marketingstrategie; Website; Social media; SEO; "
            "Social media campagne; SEA. "
            "(bron: https://redrockagency.nl/ en https://redrockagency.nl/diensten/)"
        ),
    )
    _merge_answer(
        answers,
        "onderscheidend_vermogen",
        (
            "One size fits none — geen standaardoplossingen maar strategieën die bij merk en doelen passen; "
            "specialisme in hospitality-/woonbranche; verder kijken dan marketing alleen (bedrijfsstrategie); "
            "samenwerken op persoonlijke klik en vertrouwen; betrokken, creatief, warm, strategisch, met humor; "
            "we fix things. "
            "(bron: https://redrockagency.nl/over-ons/)"
        ),
    )
    fields["website_contact"] = (
        "Heiberg 10, 5504PB Veldhoven; info@redrockagency.nl; 085 070 94 19 "
        "(bron: https://redrockagency.nl/contact/)"
    )
    notes.append(
        {
            "bron": "https://redrockagency.nl/ (+ /over-ons/, /diensten/, /contact/)",
            "gebruik": (
                "Website, diensten, onderscheid, sectoren en contactadres aangevuld. "
                "Geen socialdoelen, materiaal of frequentie verzonnen. "
                "Geografisch werkgebied blijft open (adres ≠ werkgebied)."
            ),
        }
    )


def prefill_red_rock_from_sources(conn, client_id: int, imports_dir: Path) -> dict[str, Any]:
    """Prefill only facts found in local Red Rock source files + website. Leave gaps open."""
    current = get_strategy(conn, client_id)
    notes: list[dict[str, str]] = list(current.get("source_notes") or [])
    answers: dict[str, str] = dict(current.get("start_answers") or {})
    account: dict[str, str] = dict(current.get("account_info") or {})
    fields: dict[str, str] = dict(current.get("strategy_fields") or {})
    account.setdefault("naam", "Red Rock Agency")

    # Migrate legacy combined keys into split fields without inventing new facts.
    legacy_regio = str(answers.get("doelgroep_regio") or "").strip()
    if legacy_regio and not str(answers.get("sectoren") or "").strip():
        if "wonen" in legacy_regio.lower() or "interieur" in legacy_regio.lower() or "outdoor" in legacy_regio.lower():
            answers["sectoren"] = (
                "Wonen, interieur en outdoor / woonbranche "
                "(bron: Red-rock-agency.docx — sectoren, geen regio’s)."
            )
        if "regio niet" in legacy_regio.lower() and not str(answers.get("geografische_regio") or "").strip():
            answers["geografische_regio"] = (
                "Niet expliciet vastgelegd in Red-rock-agency.docx (open)."
            )
    legacy_prod = str(answers.get("producten_onderscheid") or "").strip()
    if legacy_prod:
        if not str(answers.get("producten_diensten") or "").strip():
            answers["producten_diensten"] = legacy_prod
        if not str(answers.get("onderscheidend_vermogen") or "").strip():
            # Keep empty unless the legacy text clearly separated both; do not invent split.
            pass

    tov_path = imports_dir / "Red-rock-agency.txt"
    if tov_path.exists():
        text = tov_path.read_text(encoding="utf-8").replace("\\n", "\n")
        if not any("Red-rock-agency" in (n.get("bron") or "") for n in notes):
            notes.append(
                {
                    "bron": "Bestanden social agent / Klanten/Actief / Red-rock-agency.docx",
                    "gebruik": "Tone of voice en kanaalregels overgenomen als starttekst.",
                }
            )
        tov_bits = []
        in_tov = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("### tone of voice") or stripped.lower() == "tone of voice":
                in_tov = True
                continue
            if in_tov and stripped.startswith("###"):
                break
            if in_tov and stripped.startswith("- "):
                tov_bits.append(stripped[2:])
        if not tov_bits:
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("- ") and (
                    "Persoonlijk" in line
                    or "Scherp" in line
                    or "Toegankelijk" in line
                    or "visie" in line.lower()
                ):
                    tov_bits.append(line[2:])
        if tov_bits:
            _merge_answer(answers, "tone_of_voice", "\n".join(tov_bits))
        if "LinkedIn Red Rock zakelijk" in text or "Instagram" in text:
            _merge_answer(
                answers,
                "platforms",
                (
                    "Instagram; LinkedIn Red Rock zakelijk; LinkedIn Selah en Monique "
                    "(bron: Red-rock-agency.docx — aparte labels, geen aanname dat dit één account is)"
                ),
            )
        if "wonen, interieur en outdoor" in text.lower() or "woonbranche" in text.lower():
            _merge_answer(
                answers,
                "sectoren",
                (
                    "Beslissers en merken in wonen, interieur en outdoor / woonbranche "
                    "(bron: Red-rock-agency.docx — sectoren, geen regio’s)"
                ),
            )
        fields["kanaalregels"] = fields.get("kanaalregels") or (
            "Instagram: scherpe eerste zin, wij-vorm. "
            "LinkedIn Red Rock zakelijk: visie/case met bewijs. "
            "LinkedIn Selah en Monique: ik-vorm, persoonlijker. (bron: Red-rock-agency.docx)"
        )

    # Website facts (do not overwrite manual answers)
    if not any("redrockagency.nl" in (n.get("bron") or "") for n in notes):
        enrich_red_rock_from_website(answers, fields, notes)
    else:
        # Still fill empty website-backed keys if needed
        enrich_red_rock_from_website(answers, fields, notes)
        # Avoid duplicate website notes
        dedup: list[dict[str, str]] = []
        seen_bron: set[str] = set()
        for note in notes:
            bron = note.get("bron") or ""
            if bron in seen_bron and "redrockagency.nl" in bron:
                continue
            seen_bron.add(bron)
            dedup.append(note)
        notes = dedup

    dec_path = imports_dir / "_december_qa.json"
    if not dec_path.exists():
        xlsx = imports_dir / "RRO_Social_strategie_overzicht_2026.xlsx"
        if xlsx.exists() and not fields.get("maandstrategie_december_2026"):
            try:
                from openpyxl import load_workbook

                wb = load_workbook(xlsx, data_only=True)
                if "December 2026" in wb.sheetnames:
                    ws = wb["December 2026"]
                    lines = []
                    for r in range(1, ws.max_row + 1):
                        a = ws.cell(r, 1).value
                        b = ws.cell(r, 2).value
                        if a or b:
                            lines.append(f"{a or ''}: {b or ''}".strip())
                    if lines:
                        fields["maandstrategie_december_2026"] = "\n".join(lines[:40])
                        notes.append(
                            {
                                "bron": "RRO_Social strategie overzicht_2026.xlsx / December 2026",
                                "gebruik": "Maandvragen en bijzonderheden als strategieveld, niet als verzonnen targets.",
                            }
                        )
            except Exception:
                pass
    elif not fields.get("maandstrategie_december_2026"):
        dec = json.loads(dec_path.read_text(encoding="utf-8"))
        lines = [f"{item.get('a') or ''}: {item.get('b') or ''}".strip() for item in dec]
        fields["maandstrategie_december_2026"] = "\n".join(lines)
        notes.append(
            {
                "bron": "RRO_Social strategie overzicht_2026.xlsx / December 2026",
                "gebruik": "Maandvragen overgenomen; geen nieuwe doelen verzonnen.",
            }
        )

    # Never auto-fill social goals / material / frequency without a source answer
    for key in (
        "gewenste_socialresultaten",
        "beschikbaar_beeld",
        "nieuw_materiaal",
        "frequentie_beperkingen",
    ):
        answers.setdefault(key, "")

    return save_strategy(
        conn,
        client_id,
        account_info=account,
        start_answers=answers,
        strategy_fields=fields,
        source_notes=notes,
        mark_complete=False,
    )


def list_targets(conn, client_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM client_targets
        WHERE client_id = ?
        ORDER BY period_year DESC, period_quarter IS NULL, period_quarter DESC, id DESC
        """,
        (client_id,),
    ).fetchall()
    out = []
    for row in rows:
        measurements = conn.execute(
            """
            SELECT id, measured_at, value, source_name, notes
            FROM client_target_measurements
            WHERE target_id = ?
            ORDER BY measured_at DESC, id DESC
            """,
            (row["id"],),
        ).fetchall()
        progress = _progress(row, measurements)
        out.append(
            {
                "id": row["id"],
                "account_key": row["account_key"],
                "platform": row["platform"],
                "metric_name": row["metric_name"],
                "target_kind": row["target_kind"],
                "baseline_value": row["baseline_value"],
                "target_value": row["target_value"],
                "unit": row["unit"],
                "period_year": row["period_year"],
                "period_quarter": row["period_quarter"],
                "notes": row["notes"],
                "measurements": [dict(m) for m in measurements],
                "progress": progress,
            }
        )
    return out


def upsert_target(conn, client_id: int, body: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    target_id = body.get("id")
    values = (
        client_id,
        str(body.get("account_key") or ""),
        str(body.get("platform") or ""),
        str(body.get("metric_name") or "").strip() or "metric",
        str(body.get("target_kind") or "absolute"),
        body.get("baseline_value"),
        body.get("target_value"),
        str(body.get("unit") or ""),
        body.get("period_year"),
        body.get("period_quarter"),
        str(body.get("notes") or ""),
        now,
        now,
    )
    if target_id:
        conn.execute(
            """
            UPDATE client_targets SET
                account_key=?, platform=?, metric_name=?, target_kind=?,
                baseline_value=?, target_value=?, unit=?, period_year=?,
                period_quarter=?, notes=?, updated_at=?
            WHERE id=? AND client_id=?
            """,
            values[1:12] + (now, target_id, client_id),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO client_targets (
                client_id, account_key, platform, metric_name, target_kind,
                baseline_value, target_value, unit, period_year, period_quarter,
                notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        target_id = int(cursor.lastrowid)
    return next(t for t in list_targets(conn, client_id) if t["id"] == target_id)


def add_target_measurement(conn, client_id: int, target_id: int, body: dict[str, Any]) -> dict[str, Any]:
    owner = conn.execute(
        "SELECT id FROM client_targets WHERE id = ? AND client_id = ?",
        (target_id, client_id),
    ).fetchone()
    if owner is None:
        raise ValueError("Dit doel hoort niet bij de gekozen klant.")
    conn.execute(
        """
        INSERT INTO client_target_measurements (
            target_id, measured_at, value, source_name, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            target_id,
            str(body.get("measured_at") or _now()[:10]),
            float(body["value"]),
            str(body.get("source_name") or "manual"),
            str(body.get("notes") or ""),
            _now(),
        ),
    )
    return next(t for t in list_targets(conn, client_id) if t["id"] == target_id)


def _progress(row, measurements) -> dict[str, Any]:
    if row["target_value"] is None:
        return {"status": "nog niet meetbaar", "current": None, "ratio": None}
    if not measurements:
        return {"status": "nog niet meetbaar", "current": None, "ratio": None}
    current = float(measurements[0]["value"])
    target = float(row["target_value"])
    baseline = float(row["baseline_value"]) if row["baseline_value"] is not None else None
    kind = str(row["target_kind"] or "absolute")
    if kind == "growth":
        if baseline is None:
            return {"status": "nog niet meetbaar", "current": current, "ratio": None}
        gained = current - baseline
        needed = target
        ratio = None if needed == 0 else gained / needed
        return {"status": "meetbaar", "current": current, "gained": gained, "ratio": ratio}
    ratio = None if target == 0 else current / target
    return {"status": "meetbaar", "current": current, "ratio": ratio}
