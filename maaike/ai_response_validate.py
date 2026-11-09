"""Canonical AI answer shapes + validation before marking analysis success.

Aligned with Maaike instructions (post performance guidelines + report structure).
Does not call paid AI. Local/mock fixtures must be labeled; they do not prove Claude runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# --- Canonical formats (documented for prompts + parsers) -------------------

POST_ANALYSIS_FORMAT = {
    "type": "post_analysis",
    "label": "Postanalyse (Performance-analyse)",
    "required_object_keys": [
        "observations",
        "proposed_format_code",
        "format_rationale",
        "format_uncertainty",
        "proposed_pillar",
        "proposed_hook",
        "ai_insight",
        "ai_action",
        "hypotheses",
        "unassessable",
        "limitations_acknowledged",
    ],
    "notes": (
        "observations: [{evidence_ref, fact}]. "
        "proposed_format_code mag 'Geen passend bestaand format' / 'Niet vast te stellen' zijn. "
        "Minimaal één inhoudelijke observation OF een inhoudelijke unassessable-reden; "
        "ai_insight en ai_action niet leeg tenzij unassessable de beperking uitlegt."
    ),
}

CLIENT_REPORT_FORMAT = {
    "type": "client_report",
    "label": "Klantrapport — zes performancevragen + opbouw + actieplan",
    "six_answer_keys": ["beter", "slechter", "verklaring", "herhalen", "stoppen", "testen"],
    "chapter_keys": [
        "input_brainstorm",
        "per_kanaal",
        "seo_serp",
        "concurrenten",
        "hooks_formats_testen",
        "laten_liggen_aanscherpen",
    ],
    "action_plan_keys": [
        "planning_note",
        "hoofdfocus",
        "waarom_nu",
        "actions",
        "stop_or_test_decisions",
        "watch_outs",
    ],
    "notes": (
        "JSON met six_answers{beter,slechter,verklaring,herhalen,stoppen,testen}, "
        "chapters{...zes klantrapport-hoofdstukken}, action_plan{...Actieplan-werkwijze}, "
        "optioneel fully_researched, unassessable[], partial. "
        "Menselijke review/goedkeuring blijft verplicht vóór planning."
    ),
}

TREND_REPORT_FORMAT = {
    "type": "trend_report",
    "label": "Trendrapport — chapters + distinctions",
    "chapter_keys": [
        "positionering",
        "managementsamenvatting",
        "belangrijkste_trends",
        "platform_verschuivingen",
        "contentkansen",
        "zoekclusters",
        "conclusie",
    ],
    "required_chapters_for_usable": ["managementsamenvatting", "conclusie"],
    "distinction_keys": ["facts", "trends", "suggestions"],
    "notes": (
        "JSON met chapters{}, distinctions{facts,trends,suggestions}, "
        "fully_researched, claims_with_citations[], unassessable[]."
    ),
}

# Aliases → canonical chapter keys (accept legacy mock / model variants)
_CHAPTER_ALIASES = {
    "positionering": "positionering",
    "korte_positionering": "positionering",
    "managementsamenvatting": "managementsamenvatting",
    "management_summary": "managementsamenvatting",
    "belangrijkste_trends": "belangrijkste_trends",
    "trends": "belangrijkste_trends",
    "platform_verschuivingen": "platform_verschuivingen",
    "platform_shifts": "platform_verschuivingen",
    "platformverschuivingen": "platform_verschuivingen",
    "contentkansen": "contentkansen",
    "content_opportunities": "contentkansen",
    "zoekclusters": "zoekclusters",
    "search_clusters": "zoekclusters",
    "conclusie": "conclusie",
    "conclusion": "conclusie",
    "conclusie_en_prioriteiten": "conclusie",
}

_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "niet vast te stellen",
        "onbekend",
        "—",
        "-",
        "n/a",
        "none",
        "null",
        "(leeg)",
        "todo",
    }
)

_MIN_ANSWER_CHARS = 12
_MIN_INSIGHT_CHARS = 8

NOT_RESEARCHED_PHRASE = "Niet onderzocht / onvoldoende gegevens"
_HONEST_MISSING_SOURCE_RE = re.compile(
    r"niet\s+onderzocht|onvoldoende\s+gegevens|niet\s+echt\s+onderzocht|"
    r"bronnen?\s+ontbreken|signalen\s+ontbreken|niet\s+verzonnen",
    re.IGNORECASE,
)
_AHREFS_CLAIM_RE = re.compile(r"\bahrefs\b", re.IGNORECASE)
_SEO_ASSERT_RE = re.compile(
    r"\bahrefs\b|\bserp\b|zoekvolume|keyword\s*difficulty|\bKD\b\s*(onder|under|<)|"
    r"seo[-\s]?en[-\s]?serp|seo[-\s]?optimalisatie",
    re.IGNORECASE,
)
_COMPETITOR_ASSERT_RE = re.compile(
    r"concurrentieanalyse|concurrentenanalyse|best\s+practices?\s+van\s+concurrent|"
    r"spelers\s+die\s+consistent|concurrent(?:en)?\s+(?:tonen|laten|bouwen|doen)",
    re.IGNORECASE,
)
_TREND_ASSERT_RE = re.compile(
    r"\btrendrapport\b|markttrend|volgens\s+(?:het\s+)?trend|"
    r"externe\s+trends?\s+(?:tonen|laten|wijzen)",
    re.IGNORECASE,
)


def available_sources_from_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Derive which research domains were actually supplied (instructions/examples never count)."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    available = snap.get("available") if isinstance(snap.get("available"), dict) else {}
    sources = snap.get("sources") if isinstance(snap.get("sources"), list) else []
    manual_kinds = " ".join(
        str((s or {}).get("source_kind") or (s or {}).get("title") or (s or {}).get("url") or "").lower()
        for s in sources
    )
    seo = bool(available.get("seo_sources_supplied")) or any(
        k in manual_kinds for k in ("seo", "serp", "ahrefs", "search console")
    )
    ahrefs = bool(available.get("ahrefs_sources_supplied")) or ("ahrefs" in manual_kinds)
    competitors = bool(available.get("competitor_sources_supplied")) or any(
        k in manual_kinds for k in ("concurrent", "competitor")
    )
    return {
        "seo_sources_supplied": seo,
        "ahrefs_sources_supplied": ahrefs,
        "competitor_sources_supplied": competitors,
        "trend_linked": bool(
            available.get("trend_linked")
            or snap.get("linked_trend")
            or (snap.get("prompt_input") or {}).get("linked_trend_report")
        ),
        "manual_sources_count": len(sources),
        "instructions_and_examples_are_not_sources": True,
        "missing_source_phrase": NOT_RESEARCHED_PHRASE,
    }


def text_acknowledges_missing_source(text: str) -> bool:
    return bool(_HONEST_MISSING_SOURCE_RE.search(text or ""))


def audit_unfounded_source_claims(
    data: dict[str, Any],
    *,
    available_sources: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Flag Ahrefs/SEO/competitor/trend claims that lack supplied sources and honesty markers."""
    sources = available_sources or {
        "seo_sources_supplied": False,
        "ahrefs_sources_supplied": False,
        "competitor_sources_supplied": False,
        "trend_linked": False,
        "instructions_and_examples_are_not_sources": True,
    }
    findings: list[dict[str, Any]] = []
    chapters = data.get("chapters") if isinstance(data.get("chapters"), dict) else {}
    answers = data.get("six_answers") if isinstance(data.get("six_answers"), dict) else {}
    blobs: list[tuple[str, str]] = []
    for key, value in chapters.items():
        blobs.append((f"chapters.{key}", str(value or "")))
    for key, value in answers.items():
        blobs.append((f"six_answers.{key}", str(value or "")))
    plan = data.get("action_plan") if isinstance(data.get("action_plan"), dict) else {}
    for key, value in plan.items():
        if isinstance(value, list):
            blobs.append((f"action_plan.{key}", " ".join(str(x) for x in value)))
        else:
            blobs.append((f"action_plan.{key}", str(value or "")))

    for loc, text in blobs:
        if not text.strip():
            continue
        honest = text_acknowledges_missing_source(text)
        if _AHREFS_CLAIM_RE.search(text) and not sources.get("ahrefs_sources_supplied") and not honest:
            findings.append(
                {
                    "location": loc,
                    "kind": "ahrefs",
                    "reason": (
                        "Ahrefs-claim zonder aangeleverde Ahrefs-bron. "
                        f"Gebruik “{NOT_RESEARCHED_PHRASE}” of lever de bron."
                    ),
                }
            )
        if (
            loc.startswith("chapters.seo_serp") or _SEO_ASSERT_RE.search(text)
        ) and not sources.get("seo_sources_supplied") and not sources.get("ahrefs_sources_supplied"):
            if loc.startswith("chapters.seo_serp") and not honest:
                findings.append(
                    {
                        "location": loc,
                        "kind": "seo_serp",
                        "reason": (
                            "SEO/SERP-hoofdstuk zonder aangeleverde SEO-bronnen en zonder "
                            f"“{NOT_RESEARCHED_PHRASE}”."
                        ),
                    }
                )
            elif _SEO_ASSERT_RE.search(text) and not honest and not loc.startswith("chapters.seo_serp"):
                findings.append(
                    {
                        "location": loc,
                        "kind": "seo_serp",
                        "reason": "SEO/SERP/Ahrefs-bewering buiten aangeleverde bronnen.",
                    }
                )
        if (
            loc.startswith("chapters.concurrenten") or _COMPETITOR_ASSERT_RE.search(text)
        ) and not sources.get("competitor_sources_supplied"):
            if not honest and (
                loc.startswith("chapters.concurrenten") or _COMPETITOR_ASSERT_RE.search(text)
            ):
                # Avoid duplicate for same loc from both chapter rule and assert regex
                if not any(f["location"] == loc and f["kind"] == "concurrenten" for f in findings):
                    findings.append(
                        {
                            "location": loc,
                            "kind": "concurrenten",
                            "reason": (
                                "Concurrent-/best-practiceclaim zonder aangeleverde concurrentbronnen "
                                f"en zonder “{NOT_RESEARCHED_PHRASE}”."
                            ),
                        }
                    )
        if _TREND_ASSERT_RE.search(text) and not sources.get("trend_linked") and not honest:
            findings.append(
                {
                    "location": loc,
                    "kind": "trend",
                    "reason": (
                        "Trendclaim zonder gekoppeld trendrapport/bron en zonder "
                        f"“{NOT_RESEARCHED_PHRASE}”."
                    ),
                }
            )
    return findings


@dataclass
class ValidationResult:
    ok: bool
    usable: bool
    analysis_type: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized: dict[str, Any] | None = None
    raw_text: str = ""
    raw_parsed: Any = None
    user_message: str = ""
    test_label: str = ""  # e.g. LOCAL_TEST — not a real Claude run

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "usable": self.usable,
            "analysis_type": self.analysis_type,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "normalized": self.normalized,
            "raw_text_excerpt": (self.raw_text or "")[:4000],
            "user_message": self.user_message,
            "test_label": self.test_label,
            "formats": {
                "post": POST_ANALYSIS_FORMAT,
                "client_report": CLIENT_REPORT_FORMAT,
                "trend_report": TREND_REPORT_FORMAT,
            }.get(self.analysis_type),
        }


def extract_json_object(text: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a JSON object from model text. Returns (data, error)."""
    raw = (text or "").strip()
    if not raw:
        return None, "Leeg antwoord: geen tekst om te parsen."
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data, None
        return None, "JSON is geen object (verwacht {...})."
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None, "Geen JSON-object gevonden in het antwoord."
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            return None, f"Ongeldige JSON: {exc}"
        if isinstance(data, dict):
            return data, None
        return None, "Geëxtraheerde JSON is geen object."


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    text = str(value).strip().lower()
    return text in _PLACEHOLDER_VALUES


def _nonempty_text(value: Any, *, min_chars: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < min_chars or _is_placeholder(text):
        return ""
    return text


def _chapter_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [str(x).strip() for x in value if str(x).strip()]
        return "\n".join(parts)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def normalize_trend_chapters(chapters: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {k: "" for k in TREND_REPORT_FORMAT["chapter_keys"]}
    for raw_key, value in (chapters or {}).items():
        key = str(raw_key or "").strip()
        canon = _CHAPTER_ALIASES.get(key) or _CHAPTER_ALIASES.get(key.lower())
        if not canon:
            # Keep unknown keys under warnings path; still store as-is for inspection
            out[key] = value
            continue
        text = _chapter_text(value)
        if text and not _nonempty_text(out.get(canon), min_chars=1):
            out[canon] = text if not isinstance(value, (list, dict)) else value
        elif text and isinstance(out.get(canon), str) and not str(out.get(canon) or "").strip():
            out[canon] = text
        elif text and not out.get(canon):
            out[canon] = value
    return out


def validate_post_analysis(
    data: Any,
    *,
    raw_text: str = "",
    role: str | None = None,
    limitations: list[str] | None = None,
    test_label: str = "",
) -> ValidationResult:
    """Validate post AI JSON. usable=False → must not be stored as completed analysis."""
    result = ValidationResult(
        ok=False,
        usable=False,
        analysis_type="post_analysis",
        raw_text=raw_text or "",
        raw_parsed=data,
        test_label=test_label,
    )
    if data is None:
        result.errors.append("Geen parseerbaar JSON-antwoord.")
        result.user_message = "AI-antwoord onbruikbaar: leeg of niet als JSON te lezen."
        return result
    if not isinstance(data, dict):
        result.errors.append("Antwoord is geen JSON-object.")
        result.user_message = "AI-antwoord onbruikbaar: verwacht een JSON-object."
        return result

    observations: list[dict[str, str]] = []
    for item in data.get("observations") or []:
        if not isinstance(item, dict):
            result.warnings.append("Observation overgeslagen (geen object).")
            continue
        ref = str(item.get("evidence_ref") or "").strip()
        fact = str(item.get("fact") or "").strip()
        if ref and fact and not _is_placeholder(fact):
            observations.append({"evidence_ref": ref, "fact": fact})

    hypotheses = [str(x).strip() for x in (data.get("hypotheses") or []) if str(x).strip()]
    unassessable = [str(x).strip() for x in (data.get("unassessable") or []) if str(x).strip()]
    ack = [str(x).strip() for x in (data.get("limitations_acknowledged") or []) if str(x).strip()]
    for lim in limitations or []:
        if lim and lim not in ack:
            ack.append(lim)

    format_code = str(data.get("proposed_format_code") or "").strip()
    if role == "image" and format_code.upper().startswith("C"):
        format_code = "Geen passend bestaand format"
        result.warnings.append("Image-rol: C-formatcode geneutraliseerd naar 'Geen passend bestaand format'.")

    normalized = {
        "observations": observations,
        "proposed_format_code": format_code or "Niet vast te stellen",
        "format_rationale": str(data.get("format_rationale") or "").strip(),
        "format_uncertainty": str(data.get("format_uncertainty") or "").strip() or "onbekend",
        "proposed_pillar": str(data.get("proposed_pillar") or "").strip() or "Niet vast te stellen",
        "proposed_hook": str(data.get("proposed_hook") or "").strip() or "Niet vast te stellen",
        "ai_insight": str(data.get("ai_insight") or "").strip(),
        "ai_action": str(data.get("ai_action") or "").strip(),
        "hypotheses": hypotheses,
        "unassessable": unassessable,
        "limitations_acknowledged": ack,
    }
    result.normalized = normalized

    missing_keys = [k for k in POST_ANALYSIS_FORMAT["required_object_keys"] if k not in data]
    if missing_keys:
        # Allow missing limitations_acknowledged / hypotheses if other content is strong
        critical = [k for k in missing_keys if k not in {"hypotheses", "unassessable", "limitations_acknowledged"}]
        if critical:
            result.errors.append(f"Verplichte velden ontbreken: {', '.join(critical)}.")

    has_obs = bool(observations)
    has_unassessable = any(_nonempty_text(u, min_chars=8) for u in unassessable)
    insight_ok = bool(_nonempty_text(normalized["ai_insight"], min_chars=_MIN_INSIGHT_CHARS))
    action_ok = bool(_nonempty_text(normalized["ai_action"], min_chars=_MIN_INSIGHT_CHARS))
    rationale_ok = bool(_nonempty_text(normalized["format_rationale"], min_chars=3))

    if not has_obs and not has_unassessable:
        result.errors.append(
            "Geen bruikbare observations en geen inhoudelijke unassessable-toelichting."
        )
    if not insight_ok and not has_unassessable:
        result.errors.append("ai_insight ontbreekt of is leeg/placeholder.")
    if not action_ok and not has_unassessable:
        result.errors.append("ai_action ontbreekt of is leeg/placeholder.")
    if not rationale_ok and not has_unassessable:
        result.warnings.append("format_rationale is leeg.")

    # All-placeholder shell
    core_blank = (
        _is_placeholder(normalized["proposed_format_code"])
        and _is_placeholder(normalized["proposed_pillar"])
        and _is_placeholder(normalized["proposed_hook"])
        and not insight_ok
        and not action_ok
        and not has_obs
    )
    if core_blank:
        result.errors.append("Antwoord bevat alleen lege of placeholder-waarden.")

    if result.errors:
        result.user_message = (
            "AI-postanalyse onbruikbaar en niet als geslaagd opgeslagen. "
            + " ".join(result.errors[:3])
        )
        return result

    result.ok = True
    result.usable = True
    result.user_message = "Postanalyse voldoet aan het vaste antwoordformaat."
    return result


def validate_client_report_body(
    data: Any,
    *,
    raw_text: str = "",
    test_label: str = "",
    require_all_answers: bool = True,
    available_sources: dict[str, Any] | None = None,
    require_source_honesty: bool = True,
) -> ValidationResult:
    result = ValidationResult(
        ok=False,
        usable=False,
        analysis_type="client_report",
        raw_text=raw_text or "",
        raw_parsed=data,
        test_label=test_label,
    )
    if data is None or not isinstance(data, dict):
        result.errors.append("Geen JSON-object voor klantrapport.")
        result.user_message = "Klantrapport-antwoord onbruikbaar: verwacht JSON met six_answers."
        return result

    answers_in = data.get("six_answers")
    if not isinstance(answers_in, dict):
        # Try parse from raw_text if body only has raw_text (live Gemini prose path)
        if raw_text or data.get("raw_text"):
            parsed, err = extract_json_object(raw_text or str(data.get("raw_text") or ""))
            if parsed and isinstance(parsed.get("six_answers"), dict):
                answers_in = parsed["six_answers"]
                data = {**data, **parsed}
            elif err:
                result.errors.append(
                    "Geen six_answers-blok. " + (err or "Proza zonder JSON is niet voldoende.")
                )
                result.user_message = (
                    "Klantrapport onbruikbaar: AI-antwoord bevat geen geldige six_answers-JSON. "
                    "Oorspronkelijke tekst is bewaard ter controle."
                )
                result.normalized = {
                    "label": data.get("label") or "",
                    "raw_response": (raw_text or data.get("raw_text") or "")[:50000],
                    "analysis_usable": False,
                    "validation_errors": list(result.errors),
                }
                return result
        else:
            result.errors.append("Veld six_answers ontbreekt of is geen object.")
            result.user_message = "Klantrapport onbruikbaar: six_answers ontbreekt."
            return result

    keys = CLIENT_REPORT_FORMAT["six_answer_keys"]
    normalized_answers: dict[str, str] = {}
    missing: list[str] = []
    thin: list[str] = []
    for key in keys:
        text = _nonempty_text(answers_in.get(key), min_chars=_MIN_ANSWER_CHARS)
        if not text:
            if key not in answers_in:
                missing.append(key)
            else:
                thin.append(key)
            normalized_answers[key] = str(answers_in.get(key) or "").strip()
        else:
            normalized_answers[key] = text

    if require_all_answers and missing:
        result.errors.append(f"Ontbrekende six_answers-sleutels: {', '.join(missing)}.")
    if require_all_answers and thin:
        result.errors.append(
            f"Te korte of lege antwoorden (min. {_MIN_ANSWER_CHARS} tekens): {', '.join(thin)}."
        )
    if not any(_nonempty_text(v, min_chars=_MIN_ANSWER_CHARS) for v in normalized_answers.values()):
        result.errors.append("Alle six_answers zijn leeg of onbruikbaar.")

    chapters_in = data.get("chapters") if isinstance(data.get("chapters"), dict) else {}
    normalized_chapters: dict[str, str] = {}
    missing_chapters: list[str] = []
    for key in CLIENT_REPORT_FORMAT["chapter_keys"]:
        text = _nonempty_text(chapters_in.get(key), min_chars=_MIN_ANSWER_CHARS)
        normalized_chapters[key] = str(chapters_in.get(key) or "").strip()
        if require_all_answers and not text:
            missing_chapters.append(key)
    if require_all_answers and missing_chapters:
        result.errors.append(
            "Ontbrekende of te korte chapters: " + ", ".join(missing_chapters) + "."
        )
    elif chapters_in and not any(
        _nonempty_text(v, min_chars=_MIN_ANSWER_CHARS) for v in normalized_chapters.values()
    ):
        result.warnings.append("chapters aanwezig maar alle secties leeg/kort.")

    plan_in = data.get("action_plan") if isinstance(data.get("action_plan"), dict) else {}
    normalized_plan: dict[str, Any] = {}
    for key in CLIENT_REPORT_FORMAT["action_plan_keys"]:
        value = plan_in.get(key)
        if key in {"actions", "stop_or_test_decisions", "watch_outs"}:
            if isinstance(value, list):
                items = [str(x).strip() for x in value if str(x).strip()]
            elif value:
                items = [str(value).strip()]
            else:
                items = []
            normalized_plan[key] = items
        else:
            normalized_plan[key] = str(value or "").strip()
    if require_all_answers:
        if not _nonempty_text(normalized_plan.get("planning_note"), min_chars=8):
            result.errors.append("action_plan.planning_note ontbreekt of is te kort.")
        if not _nonempty_text(normalized_plan.get("hoofdfocus"), min_chars=8):
            result.errors.append("action_plan.hoofdfocus ontbreekt of is te kort.")
        if not (normalized_plan.get("actions") or []):
            result.errors.append("action_plan.actions moet 1–5 concrete stappen bevatten.")
        elif len(normalized_plan["actions"]) > 5:
            result.warnings.append("action_plan.actions heeft meer dan 5 items; trim bij review.")
    result.warnings.append(
        "Actieplan vereist menselijke controle/goedkeuring vóór gebruik in planning."
    )

    unassessable = [str(x).strip() for x in (data.get("unassessable") or []) if str(x).strip()]
    source_audit = audit_unfounded_source_claims(
        {
            "six_answers": normalized_answers,
            "chapters": normalized_chapters,
            "action_plan": normalized_plan,
        },
        available_sources=available_sources,
    )
    if source_audit:
        msg = (
            "Ongefundeerde bronclaims (Ahrefs/SEO/SERP/concurrenten/trends zonder aangeleverde bron). "
            f"Ontbrekende bronnen benoemen als “{NOT_RESEARCHED_PHRASE}”. "
            "Instructies en voorbeeldrapporten gelden niet als onderzoeksbron; "
            "verzin geen bevindingen om verplichte hoofdstukken te vullen."
        )
        if require_source_honesty:
            result.errors.append(msg)
            for finding in source_audit[:8]:
                result.errors.append(f"{finding['location']}: {finding['reason']}")
        else:
            result.warnings.append(msg)
            for finding in source_audit[:8]:
                result.warnings.append(f"{finding['location']}: {finding['reason']}")

    normalized = {
        "label": str(data.get("label") or "").strip(),
        "six_answers": normalized_answers,
        "chapters": normalized_chapters,
        "action_plan": normalized_plan,
        "requires_human_approval": True,
        "fully_researched": bool(data.get("fully_researched")) if "fully_researched" in data else None,
        "partial": bool(data.get("partial")) if "partial" in data else False,
        "unassessable": unassessable,
        "python_metrics_echo": data.get("python_metrics_echo"),
        "raw_response": (raw_text or data.get("raw_text") or "")[:50000],
        "analysis_usable": False,
        "source_grounding": {
            "ok": not source_audit,
            "requires_human_review": bool(source_audit),
            "unfounded_claims": source_audit,
            "missing_source_phrase": NOT_RESEARCHED_PHRASE,
            "instructions_and_examples_are_not_sources": True,
            "available_sources": available_sources
            or {
                "seo_sources_supplied": False,
                "ahrefs_sources_supplied": False,
                "competitor_sources_supplied": False,
                "trend_linked": False,
            },
        },
    }
    if source_audit:
        normalized["partial"] = True
    # Preserve extra keys for inspection without treating them as success alone
    for extra in ("ai_vs_human", "distinctions"):
        if extra in data:
            normalized[extra] = data[extra]
    result.normalized = normalized

    if result.errors:
        result.user_message = (
            "Klantrapport-analyse onbruikbaar en niet als geslaagd opgeslagen. "
            + " ".join(result.errors[:3])
        )
        return result

    normalized["analysis_usable"] = True
    result.ok = True
    result.usable = True
    result.user_message = (
        "Klantrapport voldoet aan six_answers + chapters + action_plan "
        "(menselijke goedkeuring nog vereist)."
    )
    return result


def validate_trend_report_body(
    data: Any,
    *,
    raw_text: str = "",
    test_label: str = "",
    require_core_chapters: bool = True,
) -> ValidationResult:
    result = ValidationResult(
        ok=False,
        usable=False,
        analysis_type="trend_report",
        raw_text=raw_text or "",
        raw_parsed=data,
        test_label=test_label,
    )
    if data is None or not isinstance(data, dict):
        result.errors.append("Geen JSON-object voor trendrapport.")
        result.user_message = "Trendrapport-antwoord onbruikbaar: verwacht JSON met chapters."
        return result

    working = dict(data)
    if not isinstance(working.get("chapters"), dict):
        parsed, err = extract_json_object(raw_text or str(working.get("raw_text") or ""))
        if parsed and isinstance(parsed.get("chapters"), dict):
            working = {**working, **parsed}
        elif not isinstance(working.get("chapters"), dict):
            result.errors.append(
                "Veld chapters ontbreekt. " + (err or "Proza zonder chapters-JSON is niet voldoende.")
            )
            result.user_message = (
                "Trendrapport onbruikbaar: geen geldige chapters-JSON. "
                "Oorspronkelijke tekst is bewaard ter controle."
            )
            result.normalized = {
                "label": working.get("label") or "",
                "raw_response": (raw_text or working.get("raw_text") or "")[:50000],
                "analysis_usable": False,
                "validation_errors": list(result.errors),
            }
            return result

    chapters = normalize_trend_chapters(working.get("chapters") or {})
    distinctions_in = working.get("distinctions") if isinstance(working.get("distinctions"), dict) else {}
    distinctions = {
        "facts": [str(x).strip() for x in (distinctions_in.get("facts") or []) if str(x).strip()],
        "trends": [str(x).strip() for x in (distinctions_in.get("trends") or []) if str(x).strip()],
        "suggestions": [
            str(x).strip() for x in (distinctions_in.get("suggestions") or []) if str(x).strip()
        ],
    }

    if require_core_chapters:
        for key in TREND_REPORT_FORMAT["required_chapters_for_usable"]:
            if not _nonempty_text(_chapter_text(chapters.get(key)), min_chars=_MIN_ANSWER_CHARS):
                result.errors.append(f"Chapter “{key}” ontbreekt of is te kort.")

    if not any(
        _nonempty_text(_chapter_text(chapters.get(k)), min_chars=_MIN_ANSWER_CHARS)
        for k in TREND_REPORT_FORMAT["chapter_keys"]
    ):
        result.errors.append("Alle chapters zijn leeg of onbruikbaar.")

    normalized = {
        "label": str(working.get("label") or "").strip(),
        "chapters": chapters,
        "distinctions": distinctions,
        "fully_researched": bool(working.get("fully_researched"))
        if "fully_researched" in working
        else None,
        "claims_with_citations": working.get("claims_with_citations")
        if isinstance(working.get("claims_with_citations"), list)
        else [],
        "sources_used": working.get("sources_used") if isinstance(working.get("sources_used"), list) else [],
        "unassessable": [str(x).strip() for x in (working.get("unassessable") or []) if str(x).strip()],
        "not_web_research": bool(working.get("not_web_research")),
        "not_web_research_complete": bool(working.get("not_web_research_complete")),
        "raw_response": (raw_text or working.get("raw_text") or "")[:50000],
        "analysis_usable": False,
    }
    result.normalized = normalized

    if result.errors:
        result.user_message = (
            "Trendrapport-analyse onbruikbaar en niet als geslaagd opgeslagen. "
            + " ".join(result.errors[:3])
        )
        return result

    normalized["analysis_usable"] = True
    result.ok = True
    result.usable = True
    result.user_message = "Trendrapport voldoet aan chapters/distinctions-formaat."
    return result


def validate_report_body(
    report_type: str,
    data: Any,
    *,
    raw_text: str = "",
    test_label: str = "",
    available_sources: dict[str, Any] | None = None,
    require_source_honesty: bool = True,
) -> ValidationResult:
    if report_type == "client":
        return validate_client_report_body(
            data,
            raw_text=raw_text,
            test_label=test_label,
            available_sources=available_sources,
            require_source_honesty=require_source_honesty,
        )
    if report_type == "trend":
        return validate_trend_report_body(data, raw_text=raw_text, test_label=test_label)
    result = ValidationResult(
        ok=False,
        usable=False,
        analysis_type="unknown",
        errors=[f"Onbekend rapporttype: {report_type}"],
        user_message=f"Onbekend rapporttype: {report_type}",
        test_label=test_label,
    )
    return result


def failed_body_envelope(
    *,
    label: str,
    raw_text: str,
    raw_parsed: Any,
    validation: ValidationResult,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store failed/unusable analysis with original answer for human inspection."""
    body: dict[str, Any] = {
        "label": label,
        "analysis_usable": False,
        "validation": {
            "ok": False,
            "usable": False,
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "user_message": validation.user_message,
            "analysis_type": validation.analysis_type,
            "test_label": validation.test_label,
        },
        "raw_response": (raw_text or validation.raw_text or "")[:50000],
        "raw_parsed": raw_parsed if isinstance(raw_parsed, (dict, list, str, int, float, type(None))) else str(raw_parsed),
    }
    if extra:
        body.update(extra)
    return body


def format_specs() -> dict[str, Any]:
    return {
        "post_analysis": POST_ANALYSIS_FORMAT,
        "client_report": CLIENT_REPORT_FORMAT,
        "trend_report": TREND_REPORT_FORMAT,
        "note": (
            "Lokale mock-/fixture-antwoorden bewijzen geen echte Claude-uitvoering. "
            "Label testresultaten met LOCAL_TEST / MOCK."
        ),
    }
