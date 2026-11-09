"""Readable client-report presentation (UI + PDF). No AI calls."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from maaike.repository import get_client

MONTHS_NL = {
    1: "januari",
    2: "februari",
    3: "maart",
    4: "april",
    5: "mei",
    6: "juni",
    7: "juli",
    8: "augustus",
    9: "september",
    10: "oktober",
    11: "november",
    12: "december",
}

SIX_ANSWER_SECTIONS = [
    ("beter", "What performed better?", "Wat presteerde beter?"),
    ("slechter", "What performed worse?", "Wat presteerde slechter?"),
    ("verklaring", "What explains this?", "Welke formats, hooks, onderwerpen of timing verklaren dit?"),
    ("herhalen", "What should we repeat?", "Welke succesvolle formats herhalen we?"),
    ("stoppen", "What should we stop?", "Welke formats of content laten we achterwege?"),
    ("testen", "What should we test?", "Welke nieuwe ideeën testen we gecontroleerd?"),
]

CHAPTER_SECTIONS = [
    ("input_brainstorm", "Brainstorm input", "Input van brainstorm"),
    ("per_kanaal", "Per channel", "Wat dit betekent per kanaal"),
    ("seo_serp", "SEO and SERP", "SEO en SERP"),
    ("concurrenten", "Competitors", "Concurrenten en best practices"),
    ("hooks_formats_testen", "Hooks and formats to test", "Hooks en formats om te testen"),
    ("laten_liggen_aanscherpen", "Leave or refine", "Wat laten liggen of aanscherpen"),
]

ACTION_PLAN_FIELDS = [
    ("planning_note", "Planning note", "Planningsnoot"),
    ("hoofdfocus", "Main focus", "Hoofdfocus"),
    ("waarom_nu", "Why now", "Waarom nu"),
    ("actions", "Actions", "Acties"),
    ("stop_or_test_decisions", "Stop or test", "Stoppen of testen"),
    ("watch_outs", "Watch-outs", "Let op"),
]

_FORMAT_CODE_RE = re.compile(r"\b([CRL][A-Z]{0,2}\d{2}|LZ[CR]\d{2}|LCR\d{2})\b", re.IGNORECASE)
_FORMAT_CODE_WITH_PAREN_RE = re.compile(
    r"\b([CRL][A-Z]{0,2}\d{2}|LZ[CR]\d{2}|LCR\d{2})\b(?:\s*\(([^)]*)\))?",
    re.IGNORECASE,
)

DIRECTION_LABEL_NL = {
    "higher": "hoger",
    "lower": "lager",
    "unchanged": "gelijk",
    "not comparable": "niet vergelijkbaar",
    "no previous value": "geen vorige waarde",
    "no current value": "geen huidige waarde",
    "both missing": "beide ontbrekend",
}

MISSING_DATA_NL = {
    "No matching trend report selected.": "Geen passend trendrapport geselecteerd.",
    "No targets recorded.": "Geen targets vastgelegd.",
}

REVIEW_KIND_NL = {
    "registration_vs_quality": "Registratie versus contentkwaliteit",
    "overconfident_claim": "Te stellige claim",
    "visual_claim_without_media_review": "Visuele claim zonder beeldonderzoek",
    "period_comparison_thin": "Dunne periodevergelijking",
    "format_legend_mismatch": "Formatnaam wijkt af van de legenda",
}

LOCATION_PATH_NL = {
    "six_answers": "Zes analysevragen",
    "six_answers.beter": "Wat presteerde beter?",
    "six_answers.slechter": "Wat presteerde slechter?",
    "six_answers.verklaring": "Welke formats, hooks, onderwerpen of timing verklaren dit?",
    "six_answers.herhalen": "Welke succesvolle formats herhalen we?",
    "six_answers.stoppen": "Welke formats of content laten we achterwege?",
    "six_answers.testen": "Welke nieuwe ideeën testen we gecontroleerd?",
    "chapters": "Aanvullende hoofdstukken",
    "chapters.input_brainstorm": "Input van brainstorm",
    "chapters.per_kanaal": "Wat dit betekent per kanaal",
    "chapters.seo_serp": "SEO en SERP",
    "chapters.concurrenten": "Concurrenten en best practices",
    "chapters.hooks_formats_testen": "Hooks en formats om te testen",
    "chapters.laten_liggen_aanscherpen": "Wat laten liggen of aanscherpen",
    "action_plan": "Actieplan",
}


def _display_title(title: str | None) -> str:
    text = str(title or "Client report").strip()
    text = re.sub(r"\s*[—-]\s*JSON-syntaxherstel van #\d+\s*$", "", text, flags=re.IGNORECASE)
    return text.strip() or "Client report"


def _display_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(value)[:19]


def _fmt_num(value: Any) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}".replace(",", ".")
    return f"{number:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _period_label(period: dict[str, Any] | None) -> str:
    period = period or {}
    start = period.get("start") or period.get("period_start")
    end = period.get("end") or period.get("period_end")
    year = period.get("year")
    month = period.get("month")
    if start and end:
        return f"{start} → {end}"
    if year and month:
        return f"{int(year)}-{int(month):02d}"
    return period.get("label") or "—"


def _compare_label(period: dict[str, Any] | None) -> str:
    period = period or {}
    start = period.get("previous_start") or period.get("compare_start")
    end = period.get("previous_end") or period.get("compare_end")
    if start and end:
        return f"{start} → {end}"
    return period.get("compare_label") or "—"


def monthly_report_title_nl(client_name: str, year: int | None, month: int | None) -> str:
    if year and month and 1 <= int(month) <= 12:
        return f"{client_name} – analyse {MONTHS_NL[int(month)]} {int(year)}"
    return f"{client_name} – analyse"


def presentation_status(
    *,
    body: dict[str, Any],
    review: dict[str, Any] | None,
    report_status: str,
) -> dict[str, Any]:
    review = review or {}
    approved = bool(review.get("is_approved"))
    partial = bool(body.get("partial")) or bool(
        (body.get("source_grounding") or {}).get("requires_human_review")
    )
    if approved:
        code = "approved"
        label_en = "Approved"
        label_nl = "Goedgekeurd"
        label_pdf_nl = "Goedgekeurd"
    elif partial or report_status == "failed":
        code = "partial_concept"
        label_en = "Partial concept — not approved"
        label_nl = "Partieel concept — niet goedgekeurd"
        label_pdf_nl = "Partieel concept — niet goedgekeurd"
    elif report_status in {"completed", "mock_completed"}:
        code = "concept"
        label_en = "Concept — not approved"
        label_nl = "Concept — niet goedgekeurd"
        label_pdf_nl = "Concept — niet goedgekeurd"
    elif report_status == "prepared":
        code = "prepared"
        label_en = "Prepared (no AI draft yet)"
        label_nl = "Voorbereid (nog geen AI-concept)"
        label_pdf_nl = "Voorbereid (nog geen AI-concept)"
    else:
        code = report_status or "unknown"
        label_en = str(report_status or "Unknown")
        label_nl = str(report_status or "Onbekend")
        label_pdf_nl = label_nl
    return {
        "code": code,
        "label_en": label_en,
        "label_nl": label_nl,
        "label_pdf_nl": label_pdf_nl,
        "approved": approved,
        "partial": partial and not approved,
    }


def ai_analysis_status_banner(snapshot: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    snap = snapshot or {}
    attached_ids = list(
        snap.get("attached_ai_analysis_ids")
        or (snap.get("available") or {}).get("completed_analysis_ids")
        or (snap.get("prompt_input") or {}).get("attached_ai_analysis_ids")
        or []
    )
    executed_flag = bool(snap.get("ai_analysis_executed"))
    status = snap.get("ai_analysis_status") or "not_executed"
    has_body = bool(body) and (
        body.get("six_answers") or body.get("chapters") or body.get("raw_response")
    )
    if attached_ids or (executed_flag and status == "completed_analyses_attached"):
        ids = ", ".join(str(i) for i in attached_ids) if attached_ids else "—"
        return {
            "code": "attached",
            "label_en": f"Post AI analyses attached ({ids}).",
            "show": True,
            "contradicts_not_run": False,
        }
    if has_body:
        return {
            "code": "report_draft_present",
            "label_en": "Client-report draft is present. Post-level Claude analyses may still be partial.",
            "show": True,
            "contradicts_not_run": False,
        }
    if status == "not_executed" or not executed_flag:
        return {
            "code": "not_executed",
            "label_en": "No completed post AI analyses attached for this period yet.",
            "show": True,
            "contradicts_not_run": False,
        }
    return {
        "code": status,
        "label_en": str(snap.get("ai_analysis_banner") or status),
        "show": bool(snap.get("ai_analysis_banner")),
        "contradicts_not_run": False,
    }


def _legend_lookup(snapshot: dict[str, Any]) -> dict[str, str]:
    legend = ((snapshot or {}).get("prompt_input") or {}).get("format_legend") or {}
    mapping: dict[str, str] = {}
    for kind in ("formats", "pillars", "hooks"):
        for item in legend.get(kind) or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            expl = str(item.get("explanation") or "").strip()
            # Short label from first sentence of explanation; never invent if empty.
            short = ""
            if expl:
                short = re.split(r"[.!?]\s+", expl, maxsplit=1)[0].strip()
                if len(short) > 90:
                    short = short[:87].rstrip() + "…"
            mapping[name.upper()] = short
            mapping[name] = short
    return mapping


def _direction_nl(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    return DIRECTION_LABEL_NL.get(raw.lower(), DIRECTION_LABEL_NL.get(raw, raw))


def _missing_item_nl(item: Any) -> str:
    text = str(item or "").strip()
    if not text:
        return ""
    if text in MISSING_DATA_NL:
        return MISSING_DATA_NL[text]
    # Keep already-Dutch / mixed registry messages; only translate known English stems.
    lowered = text.lower()
    if lowered.startswith("no matching trend report"):
        return "Geen passend trendrapport geselecteerd."
    if lowered.startswith("no targets recorded"):
        return "Geen targets vastgelegd."
    return text


def _location_label_nl(location: str) -> str:
    parts = [p.strip() for p in str(location or "").split("/") if p.strip()]
    if not parts:
        return ""
    labels = []
    for part in parts:
        labels.append(LOCATION_PATH_NL.get(part, LOCATION_PATH_NL.get(part.split(".")[0], part)))
    # Deduplicate while preserving order
    out: list[str] = []
    for label in labels:
        if label and label not in out:
            out.append(label)
    return " / ".join(out)


def _looks_like_metric_paren(inner: str) -> bool:
    text = str(inner or "").strip()
    if not text:
        return False
    if re.search(r"\d", text) and re.search(
        r"bereik|likes|views|comments|shares|saves|clicks|%|post\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return bool(re.search(r"\d{2,}\s*,\s*\d+", text))


def annotate_format_codes(text: str, legend_map: dict[str, str]) -> str:
    """Show official legend names next to format codes in display text only.

    Does not invent names. Avoids awkward nested parentheses by replacing AI
    nicknames with the legend label, or folding metrics into one parenthesis.
    """
    if not text or not legend_map:
        return text

    def repl(match: re.Match[str]) -> str:
        code = match.group(1)
        short = legend_map.get(code) or legend_map.get(code.upper())
        if not short:
            return match.group(0)
        inner = match.group(2)
        if inner is None:
            return f"{code} ({short})"
        inner_clean = inner.strip()
        if not inner_clean:
            return f"{code} ({short})"
        if inner_clean.casefold() == short.casefold():
            return f"{code} ({short})"
        if short.casefold() in inner_clean.casefold():
            # Already contains the official name; keep single pair as legend only.
            return f"{code} ({short})"
        if _looks_like_metric_paren(inner_clean):
            return f"{code} ({short}: {inner_clean})"
        # AI nickname / alternate gloss — display official legend name only.
        return f"{code} ({short})"

    return _FORMAT_CODE_WITH_PAREN_RE.sub(repl, text)


def find_format_legend_mismatches(
    body: dict[str, Any],
    legend_map: dict[str, str],
) -> list[dict[str, str]]:
    """Flag AI nicknames for format codes that differ from the saved client legend."""
    if not legend_map:
        return []
    sections: list[tuple[str, str]] = []
    answers = body.get("six_answers") if isinstance(body.get("six_answers"), dict) else {}
    for key, text in answers.items():
        if str(text or "").strip():
            sections.append((f"six_answers.{key}", str(text)))
    chapters = body.get("chapters") if isinstance(body.get("chapters"), dict) else {}
    for key, text in chapters.items():
        if str(text or "").strip():
            sections.append((f"chapters.{key}", str(text)))
    plan = body.get("action_plan") if isinstance(body.get("action_plan"), dict) else {}
    for key, value in plan.items():
        if isinstance(value, list):
            joined = "\n".join(str(x) for x in value if str(x).strip())
            if joined:
                sections.append((f"action_plan.{key}", joined))
        elif str(value or "").strip():
            sections.append((f"action_plan.{key}", str(value)))

    seen: set[tuple[str, str]] = set()
    flags: list[dict[str, str]] = []
    for location, text in sections:
        for match in _FORMAT_CODE_WITH_PAREN_RE.finditer(text):
            code = match.group(1)
            inner = (match.group(2) or "").strip()
            official = legend_map.get(code) or legend_map.get(code.upper())
            if not official or not inner:
                continue
            if _looks_like_metric_paren(inner):
                continue
            if inner.casefold() == official.casefold() or official.casefold() in inner.casefold():
                continue
            key = (code.upper(), inner.casefold())
            if key in seen:
                continue
            seen.add(key)
            flags.append(
                {
                    "kind": "format_legend_mismatch",
                    "location": location,
                    "note": (
                        f"Format {code.upper()} heet in de klantlegenda “{official}”, "
                        f"maar de AI noemt het “{inner}”. Gebruik de legendanaam; "
                        "verander geen postindelingen automatisch."
                    ),
                    "code": code.upper(),
                    "ai_label": inner,
                    "legend_label": official,
                }
            )
    return flags


def _metric_sum_line(block: dict[str, Any], *, reach: bool = False) -> str | None:
    """Format a known sum; never invent 0 for missing values."""
    if not isinstance(block, dict) or not block:
        return None
    raw_sum = block.get("sum")
    if raw_sum is None:
        return None
    known = block.get("known_count")
    missing = block.get("missing_count")
    parts = [_fmt_num(raw_sum)]
    if known is not None:
        note = f"op basis van {_fmt_num(known)} posts"
        if missing is not None and int(missing) > 0:
            note += f" ({_fmt_num(missing)} onbekend)"
        parts.append(note)
    if reach:
        parts.append("geen uniek maandbereik")
    return " · ".join(parts)


def _headline_metrics_nl(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """At most four calm figures for the reading view."""
    metrics = (snapshot or {}).get("metrics") or {}
    totals = metrics.get("totals") or {}
    comparison = (snapshot or {}).get("comparison") or {}
    rows: list[dict[str, str]] = []

    current_posts = metrics.get("post_count")
    if current_posts is None:
        current_posts = comparison.get("current_post_count")
    if current_posts is not None:
        rows.append({"key": "posts", "label": "Posts", "value": _fmt_num(current_posts)})

    reach_line = _metric_sum_line(
        totals.get("reach") if isinstance(totals.get("reach"), dict) else {},
        reach=True,
    )
    if reach_line:
        rows.append({"key": "reach", "label": "Bekend postbereik", "value": reach_line})

    likes_line = _metric_sum_line(totals.get("likes") if isinstance(totals.get("likes"), dict) else {})
    if likes_line:
        rows.append({"key": "likes", "label": "Likes", "value": likes_line})

    views_line = _metric_sum_line(totals.get("views") if isinstance(totals.get("views"), dict) else {})
    if views_line:
        rows.append({"key": "views", "label": "Views", "value": views_line})

    return rows[:4]


def _key_metrics_nl(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Full figure list for ‘View all figures’ (never invents missing as 0)."""
    metrics = (snapshot or {}).get("metrics") or {}
    totals = metrics.get("totals") or {}
    period = (snapshot or {}).get("period") or {}
    comparison = (snapshot or {}).get("comparison") or {}
    rows: list[dict[str, str]] = [
        {
            "label": "Huidige periode",
            "value": _period_label(period if isinstance(period, dict) else {}),
        },
        {
            "label": "Vergelijkingsperiode",
            "value": _compare_label(period if isinstance(period, dict) else {}),
        },
    ]
    current_posts = metrics.get("post_count")
    if current_posts is None:
        current_posts = comparison.get("current_post_count")
    if current_posts is not None:
        rows.append({"label": "Posts huidige periode", "value": _fmt_num(current_posts)})
    prev_posts = comparison.get("previous_post_count")
    if prev_posts is not None:
        rows.append({"label": "Posts vergelijkingsperiode", "value": _fmt_num(prev_posts)})
    metric_labels = {
        "reach": "Opgeteld bekend postbereik",
        "likes": "Likes (opgeteld bekend)",
        "views": "Views (opgeteld bekend)",
        "comments": "Comments (opgeteld bekend)",
    }
    for key, label in metric_labels.items():
        block = totals.get(key) if isinstance(totals.get(key), dict) else {}
        line = _metric_sum_line(block, reach=(key == "reach"))
        if line:
            rows.append({"label": label, "value": line})

    deltas = comparison.get("deltas") if isinstance(comparison.get("deltas"), dict) else {}
    metric_name = str(comparison.get("metric") or "reach")
    if deltas.get("sum"):
        d = deltas["sum"]
        if d.get("absolute") is not None:
            rows.append(
                {
                    "label": f"Verschil {metric_name} (som, bekend)",
                    "value": (
                        f"{_fmt_num(d.get('absolute'))} "
                        f"({_fmt_num(d.get('pct'))}% · "
                        f"{_direction_nl(d.get('direction_label') or d.get('direction'))}) "
                        f"· bruikbare posts nu {_fmt_num((comparison.get('current') or {}).get('known_count'))} / "
                        f"vorige {_fmt_num((comparison.get('previous') or {}).get('known_count'))}"
                    ),
                }
            )
    if deltas.get("average_over_known"):
        d = deltas["average_over_known"]
        if d.get("absolute") is not None:
            rows.append(
                {
                    "label": f"Verschil {metric_name} (gemiddelde over bekende posts)",
                    "value": (
                        f"{_fmt_num(d.get('absolute'))} "
                        f"({_fmt_num(d.get('pct'))}% · "
                        f"{_direction_nl(d.get('direction_label') or d.get('direction'))})"
                    ),
                }
            )
    if comparison.get("claim_significant_difference") is False:
        rows.append(
            {
                "label": "Significantie",
                "value": "Geen automatische significantieclaim; verschillen zijn beschrijvend.",
            }
        )
    return rows


def _short_summary(body: dict[str, Any], *, content_source: str) -> str:
    """Only return an explicit summary field — never invent one from other sections."""
    del content_source  # reserved for callers; approved vs concept does not invent text
    return str(body.get("summary") or "").strip()


def _review_item_map(review: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in (review or {}).get("item_feedback") or []:
        if isinstance(item, dict) and item.get("key"):
            out[str(item["key"])] = item
    return out


def _resolve_section_text(ai_text: str, review_item: dict[str, Any] | None) -> dict[str, Any]:
    """Apply saved edits; keep AI original separate. Feedback is never used as report text."""
    ai_text = str(ai_text or "").strip()
    item = review_item or {}
    edited = str(item.get("edited_text") or "").strip()
    decision = str(item.get("decision") or "")
    if edited:
        text = edited
        is_edited = edited != ai_text
    elif decision == "reject":
        text = ""
        is_edited = False
    else:
        text = ai_text
        is_edited = False
    return {
        "text": text,
        "ai_text": ai_text,
        "is_edited": is_edited,
        "edited_by": str(item.get("edited_by") or "").strip(),
        "edited_at": str(item.get("edited_at") or "").strip(),
        "feedback": str(item.get("feedback") or "").strip(),
        "review_key": str(item.get("key") or ""),
    }


def _enrich_review_point(item: dict[str, Any]) -> dict[str, str]:
    kind = str(item.get("kind") or "review")
    location = str(item.get("location") or "")
    note = str(item.get("note") or item.get("message") or "").strip()
    kind_nl = str(item.get("kind_nl") or REVIEW_KIND_NL.get(kind) or kind.replace("_", " "))
    location_nl = str(item.get("location_nl") or _location_label_nl(location))
    return {
        "kind": kind,
        "kind_nl": kind_nl,
        "location": location,
        "location_nl": location_nl,
        "note": note,
        "label_nl": kind_nl,
        "summary_nl": note,
        "code": str(item.get("code") or ""),
        "ai_label": str(item.get("ai_label") or ""),
        "legend_label": str(item.get("legend_label") or ""),
    }


def default_review_attention_points(
    body: dict[str, Any],
    *,
    legend_map: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Heuristic flags for human review — does not rewrite AI text."""
    flags: list[dict[str, Any]] = []
    stored = body.get("human_review_flags")
    if isinstance(stored, list) and stored:
        flags.extend(
            item
            for item in stored
            if isinstance(item, dict)
            and str(item.get("note") or item.get("message") or "").strip()
        )
    else:
        answers = body.get("six_answers") if isinstance(body.get("six_answers"), dict) else {}
        chapters = body.get("chapters") if isinstance(body.get("chapters"), dict) else {}
        plan = body.get("action_plan") if isinstance(body.get("action_plan"), dict) else {}
        blob_parts = [str(v) for v in answers.values()] + [str(v) for v in chapters.values()]
        for key in ("hoofdfocus", "waarom_nu", "planning_note"):
            blob_parts.append(str(plan.get(key) or ""))
        for key in ("actions", "stop_or_test_decisions", "watch_outs"):
            val = plan.get(key)
            if isinstance(val, list):
                blob_parts.extend(str(x) for x in val)
        blob = "\n".join(blob_parts).lower()

        if re.search(r"zonder format|missen een format|zonder.*hook|registratie", blob):
            if re.search(r"slecht|achter|stoppen met ongestructureerde|bleven achter", blob):
                flags.append(
                    {
                        "kind": "registration_vs_quality",
                        "location": "six_answers.slechter / six_answers.stoppen",
                        "note": (
                            "Ontbrekende format-/hook-registratie is geen bewijs van slechte content. "
                            "Controleer of de conclusie over contentkwaliteit of alleen over registratie gaat."
                        ),
                    }
                )
        if re.search(r"\baantoonbaar\b|\bbewezen\b|wordt in huidige vorm gestaakt|stoppen met", blob):
            flags.append(
                {
                    "kind": "overconfident_claim",
                    "location": "six_answers.stoppen / action_plan",
                    "note": (
                        "Formuleringen als “bewezen succesvol” of stoppen met een format zijn hier "
                        "nog onvoldoende onderbouwd. Vraagt menselijke afzwakking of periodedata."
                    ),
                }
            )
        if re.search(r"visueel|slide 1|openingsbeeld|gezicht", blob) and "hypothese" not in blob:
            flags.append(
                {
                    "kind": "visual_claim_without_media_review",
                    "location": "six_answers.verklaring / chapters.hooks_formats_testen",
                    "note": (
                        "Visuele verklaringen zonder beeldonderzoek zijn hypotheses. "
                        "Behandel ze zo tot er aparte beeldreview is."
                    ),
                }
            )
        if re.search(r"presteerde beter|presteerde slechter|beter|slechter", blob):
            if not re.search(r"vergelijkingsperiode|vorige periode|augustus|aug–sep|aug-sep", blob):
                flags.append(
                    {
                        "kind": "period_comparison_thin",
                        "location": "six_answers.beter / six_answers.slechter",
                        "note": (
                            "Beter/slechter vereist een onderbouwde periodevergelijking "
                            "(metric + bruikbare posts). Controleer of die vergelijking echt is meegenomen."
                        ),
                    }
                )

    mismatch_flags = find_format_legend_mismatches(body, legend_map or {})
    existing_notes = {
        str(item.get("note") or item.get("message") or "").strip().casefold() for item in flags
    }
    for item in mismatch_flags:
        note = str(item.get("note") or "").strip()
        if note and note.casefold() not in existing_notes:
            flags.append(item)
            existing_notes.add(note.casefold())

    return [_enrich_review_point(item) for item in flags if str(item.get("note") or "").strip()]


def build_client_report_presentation(
    conn,
    client_id: int,
    report: dict[str, Any],
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured readable view of one saved client report. Does not rewrite analysis text."""
    review = review or {}
    body = report.get("body") if isinstance(report.get("body"), dict) else {}
    snapshot = report.get("input_snapshot") if isinstance(report.get("input_snapshot"), dict) else {}
    client = get_client(conn, client_id)
    client_name = client.name if client else f"Client #{client_id}"
    status = presentation_status(
        body=body,
        review=review,
        report_status=str(report.get("status") or ""),
    )
    approved = status["approved"]
    final_text = str(review.get("final_version_text") or "").strip()
    content_source = "approved_final" if approved and final_text else "ai_concept"
    content_source_label_en = (
        "Human final version (approved)"
        if content_source == "approved_final"
        else "AI concept — not approved"
    )
    content_source_label_nl = (
        "Menselijke eindversie (goedgekeurd)"
        if content_source == "approved_final"
        else "AI-concept — niet goedgekeurd"
    )

    year = report.get("period_year") or (snapshot.get("period") or {}).get("year")
    month = report.get("period_month") or (snapshot.get("period") or {}).get("month")
    stored_title = str(report.get("title") or "").strip()
    technical = bool(
        stored_title
        and (
            stored_title.lower().startswith("client report")
            or stored_title.lower().startswith("created in")
            or "json-syntaxherstel" in stored_title.lower()
            or stored_title.lower().startswith("qa real")
        )
    )
    title_nl = (
        stored_title
        if stored_title and not technical
        else monthly_report_title_nl(client_name, int(year) if year else None, int(month) if month else None)
    )
    en_months = {
        1: "January",
        2: "February",
        3: "March",
        4: "April",
        5: "May",
        6: "June",
        7: "July",
        8: "August",
        9: "September",
        10: "October",
        11: "November",
        12: "December",
    }
    if year and month and 1 <= int(month) <= 12:
        title_en = f"{client_name} – analysis {en_months[int(month)]} {int(year)}"
    else:
        title_en = f"{client_name} – analysis"
    legend_map = _legend_lookup(snapshot)
    item_map = _review_item_map(review)
    document_sections: list[dict[str, Any]] = []

    def _warnings_for(review_key: str, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        matched = []
        for point in points:
            loc = str(point.get("location") or "")
            parts = [p.strip() for p in loc.replace(",", "/").split("/") if p.strip()]
            if any(part == review_key or part.startswith(f"{review_key}.") or review_key.startswith(part) for part in parts):
                matched.append(point)
        return matched

    six_answers = []
    answers = body.get("six_answers") if isinstance(body.get("six_answers"), dict) else {}
    for key, label_en, label_nl in SIX_ANSWER_SECTIONS:
        review_key = f"six_answers.{key}"
        resolved = _resolve_section_text(str(answers.get(key) or ""), item_map.get(review_key))
        text = resolved["text"]
        if not text and not resolved["ai_text"]:
            continue
        if not text:
            continue
        row = {
            "key": key,
            "review_key": review_key,
            "label_en": label_en,
            "label_nl": label_nl,
            "text": text,
            "text_display": annotate_format_codes(text, legend_map),
            "ai_text": resolved["ai_text"],
            "is_edited": resolved["is_edited"],
            "edited_by": resolved["edited_by"],
            "edited_at": resolved["edited_at"],
            "feedback": resolved["feedback"],
        }
        six_answers.append(row)
        document_sections.append({**row, "group": "analysis"})

    chapters = []
    chapter_map = body.get("chapters") if isinstance(body.get("chapters"), dict) else {}
    for key, label_en, label_nl in CHAPTER_SECTIONS:
        review_key = f"chapters.{key}"
        resolved = _resolve_section_text(str(chapter_map.get(key) or ""), item_map.get(review_key))
        text = resolved["text"]
        if not text:
            continue
        row = {
            "key": key,
            "review_key": review_key,
            "label_en": label_en,
            "label_nl": label_nl,
            "text": text,
            "text_display": annotate_format_codes(text, legend_map),
            "ai_text": resolved["ai_text"],
            "is_edited": resolved["is_edited"],
            "edited_by": resolved["edited_by"],
            "edited_at": resolved["edited_at"],
            "feedback": resolved["feedback"],
        }
        chapters.append(row)
        document_sections.append({**row, "group": "chapters"})

    action_plan_rows = []
    plan = body.get("action_plan") if isinstance(body.get("action_plan"), dict) else {}
    for key, label_en, label_nl in ACTION_PLAN_FIELDS:
        review_key = f"action_plan.{key}"
        value = plan.get(key)
        if isinstance(value, list):
            ai_items = [str(x).strip() for x in value if str(x).strip()]
            ai_text = "\n".join(f"• {x}" for x in ai_items)
        else:
            ai_items = []
            ai_text = str(value or "").strip()
        resolved = _resolve_section_text(ai_text, item_map.get(review_key))
        text = resolved["text"]
        if not text and not ai_text:
            continue
        if not text:
            continue
        if resolved["is_edited"] or not ai_items:
            items_out: list[str] = []
            items_display: list[str] = []
            text_out = text
            text_display = annotate_format_codes(text, legend_map)
        else:
            items_out = ai_items
            items_display = [annotate_format_codes(i, legend_map) for i in ai_items]
            text_out = ""
            text_display = ""
        row = {
            "key": key,
            "review_key": review_key,
            "label_en": label_en,
            "label_nl": label_nl,
            "items": items_out,
            "items_display": items_display,
            "text": text_out,
            "text_display": text_display,
            "ai_text": resolved["ai_text"],
            "is_edited": resolved["is_edited"],
            "edited_by": resolved["edited_by"],
            "edited_at": resolved["edited_at"],
            "feedback": resolved["feedback"],
        }
        action_plan_rows.append(row)
        document_sections.append({**row, "group": "action_plan"})

    # Optional staff addition shown only when text was saved.
    addition = item_map.get("addition.staff") or {}
    addition_text = str(addition.get("edited_text") or addition.get("human_text") or "").strip()
    if addition_text:
        add_row = {
            "key": "staff",
            "review_key": "addition.staff",
            "label_en": "Staff addition",
            "label_nl": "Eigen aanvulling",
            "text": addition_text,
            "text_display": annotate_format_codes(addition_text, legend_map),
            "ai_text": "",
            "is_edited": True,
            "edited_by": str(addition.get("edited_by") or "").strip(),
            "edited_at": str(addition.get("edited_at") or "").strip(),
            "feedback": str(addition.get("feedback") or "").strip(),
            "items": [],
            "items_display": [],
        }
        document_sections.append({**add_row, "group": "addition"})

    missing_raw = list(snapshot.get("missing") or [])
    missing = [_missing_item_nl(x) for x in missing_raw if str(x).strip()]
    unassessable_raw = [str(x) for x in (body.get("unassessable") or []) if str(x).strip()]
    unassessable = [_missing_item_nl(x) for x in unassessable_raw]
    grounding = body.get("source_grounding") if isinstance(body.get("source_grounding"), dict) else {}
    period = snapshot.get("period") or {
        "year": report.get("period_year"),
        "month": report.get("period_month"),
    }
    summary = _short_summary(body, content_source=content_source)
    show_summary = bool(summary)

    review_points = default_review_attention_points(body, legend_map=legend_map)
    for section in document_sections:
        section["warnings"] = _warnings_for(str(section.get("review_key") or ""), review_points)
    corrections_open = bool(review_points) and content_source != "approved_final"

    format_glossary = []
    for code in sorted({k for k in legend_map if re.fullmatch(r"[A-Za-z0-9]+", k) and k.upper() == k}):
        short = legend_map.get(code) or ""
        if short:
            format_glossary.append({"code": code, "label": short})

    # Editable slots for sections that exist in review items but have no AI text yet
    # (e.g. empty action fields) — still expose via review item_feedback in the UI.
    editable_keys = [
        str(i.get("key"))
        for i in (review.get("item_feedback") or [])
        if isinstance(i, dict)
        and str(i.get("key") or "") not in {"action_plan.human_approval"}
    ]

    return {
        "report_id": report.get("id"),
        "report_type": report.get("report_type"),
        "title": title_nl,
        "title_en": title_en,
        "title_ui": title_en,
        "title_raw": report.get("title") or "Client report",
        "client_id": client_id,
        "client_name": client_name,
        "period_label": _period_label(period if isinstance(period, dict) else {}),
        "compare_label": _compare_label(period if isinstance(period, dict) else {}),
        "period_year": year,
        "period_month": month,
        "version": report.get("version"),
        "created_at": _display_timestamp(report.get("prepared_at") or report.get("created_at")),
        "executed_at": _display_timestamp(report.get("executed_at")),
        "prompt_version": report.get("prompt_version"),
        "status": status,
        "content_source": content_source,
        "content_source_label_en": content_source_label_en,
        "content_source_label_nl": content_source_label_nl,
        "summary": summary,
        "show_summary": show_summary,
        "approved_final_text": final_text if content_source == "approved_final" else "",
        "concept_text": final_text if content_source != "approved_final" else "",
        "headline_metrics": _headline_metrics_nl(snapshot),
        "key_metrics": _key_metrics_nl(snapshot),
        "six_answers": six_answers,
        "chapters": chapters,
        "action_plan": action_plan_rows,
        "document_sections": document_sections,
        "editable_keys": editable_keys,
        "missing_data": missing,
        "missing_data_raw": missing_raw,
        "missing_sources": unassessable,
        "missing_sources_raw": unassessable_raw,
        "source_grounding_ok": grounding.get("ok"),
        "ai_analysis_banner": ai_analysis_status_banner(snapshot, body),
        "review_attention_points": review_points,
        "content_corrections_open": corrections_open,
        "format_glossary": format_glossary[:40],
        "human_review": {
            "can_review": bool(review.get("can_review")),
            "is_approved": approved,
            "review_status": review.get("review_status") or "",
            "review_status_label": review.get("review_status_label") or "",
            "reviewer_name": review.get("reviewer_name") or "",
            "approved_at": (review.get("record") or {}).get("approved_at") or review.get("approved_at"),
            "final_version_text": final_text,
            "item_count": len(review.get("item_feedback") or []),
            "previous_approved_count": len(review.get("previous_approved") or []),
        },
        "has_readable_content": bool(
            six_answers or chapters or action_plan_rows or final_text or document_sections
        ),
        "technical": {
            "body": body,
            "usage": report.get("usage") or {},
            "estimate": report.get("estimate") or {},
            "notes": report.get("notes") or [],
            "error_text": report.get("error_text") or "",
            "json_syntax_recovery": body.get("json_syntax_recovery"),
            "context_preview": snapshot.get("context_preview"),
            "prompt_input": snapshot.get("prompt_input"),
            "raw_response_present": bool(body.get("raw_response")),
            "human_review_flags": body.get("human_review_flags") or [],
            "review_attention_technical": [
                {
                    "kind": p.get("kind"),
                    "location": p.get("location"),
                    "note": p.get("note"),
                    "code": p.get("code") or None,
                }
                for p in review_points
            ],
            "missing_data_raw": missing_raw,
            "missing_sources_raw": unassessable_raw,
            "previous_approved": review.get("previous_approved") or [],
        },
    }


def attach_presentation_to_payload(conn, client_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    report = payload.get("report") or {}
    if report.get("report_type") != "client":
        payload["presentation"] = None
        return payload
    payload["presentation"] = build_client_report_presentation(
        conn,
        client_id,
        report,
        review=payload.get("review") or {},
    )
    return payload


def comparison_prompt_block(period_bundle: dict[str, Any]) -> dict[str, Any]:
    """Compact comparison facts that must be present in client-report prompt input."""
    comparison = period_bundle.get("comparison") or {}
    metrics = period_bundle.get("metrics") or {}
    period = period_bundle.get("period") or {}
    by_platform = metrics.get("by_platform") or {}
    current = comparison.get("current") if isinstance(comparison.get("current"), dict) else {}
    previous = comparison.get("previous") if isinstance(comparison.get("previous"), dict) else {}
    return {
        "current_period": {
            "label": period.get("label") or _period_label(period),
            "start": period.get("start"),
            "end": period.get("end"),
            "post_count": comparison.get("current_post_count") or metrics.get("post_count"),
        },
        "comparison_period": {
            "label": period.get("compare_label") or _compare_label(period),
            "start": period.get("previous_start"),
            "end": period.get("previous_end"),
            "post_count": comparison.get("previous_post_count"),
        },
        "metric": comparison.get("metric") or "reach",
        "platforms_in_period": by_platform,
        "usable_posts": {
            "current_known": current.get("known_count"),
            "current_missing": current.get("missing_count"),
            "previous_known": previous.get("known_count"),
            "previous_missing": previous.get("missing_count"),
        },
        "deltas": comparison.get("deltas"),
        "claim_significant_difference": comparison.get("claim_significant_difference"),
        "note": comparison.get("note"),
        "rules": [
            "State platform, metric and usable post counts for each comparison.",
            "Do not treat missing format/pillar/hook registration as proof of poor content.",
            "No significance claims without a suitable analysis.",
        ],
    }
