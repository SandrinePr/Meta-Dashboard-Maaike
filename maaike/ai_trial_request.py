"""Build the AI request package for the Red Rock post-analysis trial (no network call)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SOCIAL_AGENT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports" / "redrock" / "social_agent"
PROMPT_VERSION = "maaike-postanalyse-trial-v2"

# Formats sheet groups: C* = Carrousel/post (multi-slide); R* = Reel; LZ* = LinkedIn zakelijk.
FORMAT_FAMILY = {
    "image": {
        "eligible_prefixes": (),  # no dedicated single-image codes in the legend
        "instruction": (
            "Voor een enkele afbeelding bestaan in de Red Rock-legenda geen aparte image-only formatcodes. "
            "C-codes beschrijven carrousel/post-opzetten met meerdere slides — wijs die niet automatisch toe "
            "aan één afbeelding. Antwoord met 'Geen passend bestaand format' of 'Niet vast te stellen' "
            "tenzij bewijs overtuigend een bestaande definitie dekt."
        ),
    },
    "carousel": {
        "eligible_prefixes": ("C",),
        "instruction": "Gebruik alleen C-codes (C01–C13) uit de legenda wanneer slides en opbouw matchen.",
    },
    "reel": {
        "eligible_prefixes": ("R",),
        "instruction": "Gebruik alleen R-codes (R01–R14) uit de legenda. Thumbnail ≠ volledige reel.",
    },
}


def _read_txt(name: str) -> str:
    path = SOCIAL_AGENT_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_instruction_bundle() -> dict[str, Any]:
    """Load real Social Agent texts used for this trial. No invented prompts."""
    performance = _read_txt("Performance-analyse richtlijnen.txt")
    role = _read_txt("Role - Algemene instructies.txt")
    quality = _read_txt("Kwaliteitsstandaard.txt")
    return {
        "prompt_version": PROMPT_VERSION,
        "included": {
            "postanalyse": {
                "file": "Performance-analyse richtlijnen.docx",
                "chars": len(performance),
                "used": bool(performance),
            },
            "algemene_rol": {
                "file": "Role - Algemene instructies.docx",
                "chars": len(role),
                "used": bool(role),
            },
            "kwaliteit": {
                "file": "Kwaliteitsstandaard.docx",
                "chars": len(quality),
                "used": bool(quality),
            },
        },
        "excluded_for_this_trial": [
            "Trendrapport - opbouw en aanpak.docx (niet uitvoeren)",
            "Klantrapport - opbouw en aanpak.docx (niet uitvoeren)",
            "Cluster-prompt (niet gevonden)",
        ],
        "system_text": _system_text(role, quality, performance),
        "sources_on_disk": [p.name for p in SOCIAL_AGENT_DIR.glob("*.txt")],
    }


def _system_text(role: str, quality: str, performance: str) -> str:
    parts = [
        "Je werkt voor Red Rock Agency als social-analysehulp in Meta Dashboard 2.0.",
        "Gebruik uitsluitend de meegeleverde instructies en formatlegenda. Verzin geen formatcodes.",
        "Houd drie lagen strikt uit elkaar:",
        "1) Zichtbare details = alleen wat je in meegestuurde beelden/frames/caption ziet (met evidence_ref).",
        "2) Meetbare cijfers = alleen de meegeleverde metrics; citeer ze als cijfers, niet als bewijs voor beeldoorzaak.",
        "3) Hypotheses = mogelijke verklaringen; markeer ze als hypothese en zet ze in hypotheses[], nooit als feit in ai_insight.",
        "Lage likes/comments/saves bewijzen niet dat het format (bijv. statische afbeelding) de oorzaak was.",
        "Schrijf in ai_insight geen causale claim van metrics → beeldvorm zonder apart bewijs; noem cijfers als feiten en oorzaken als hypothese.",
        "Verzin geen beoordelingsformule voor goed/gemiddeld/slecht.",
        "Als bewijs ontbreekt: 'Niet vast te stellen' of 'Geen passend bestaand format'.",
        "Je krijgt géén Excel-beoordeling, Excel-insight of Excel-actie — die zijn voor latere vergelijking.",
        "",
        "=== Role - Algemene instructies ===",
        role[:12000] if role else "(bestand ontbreekt)",
        "",
        "=== Kwaliteitsstandaard ===",
        quality[:8000] if quality else "(bestand ontbreekt)",
        "",
        "=== Performance-analyse richtlijnen ===",
        performance[:14000] if performance else "(bestand ontbreekt)",
    ]
    return "\n".join(parts)


def filter_formats_for_role(
    role: str,
    all_formats: list[dict[str, str]],
) -> dict[str, Any]:
    family = FORMAT_FAMILY.get(role) or {
        "eligible_prefixes": (),
        "instruction": "Geen formatfamilie bekend voor deze contentsoort.",
    }
    prefixes = family["eligible_prefixes"]
    eligible = []
    for item in all_formats:
        code = str(item.get("code") or "")
        if not prefixes:
            continue
        if any(code.startswith(p) for p in prefixes) and code[0].isalpha():
            # C13 etc. — also reject LinkedIn LZ* unless prefix matches
            if code.startswith("LZ"):
                continue
            eligible.append(item)
    return {
        "role": role,
        "instruction": family["instruction"],
        "eligible_formats": eligible,
        "eligible_count": len(eligible),
        "not_auto_assign_carousel_to_image": role == "image",
    }


def build_user_prompt(
    *,
    role: str,
    post: dict[str, Any],
    media_prep: dict[str, Any],
    format_pack: dict[str, Any],
    pillars: list[str],
    metrics: dict[str, Any],
) -> str:
    lines = [
        f"Analyseer deze Red Rock-post voor formatvoorstel (rol={role}).",
        f"content_kind={post.get('content_kind')}",
        f"platform={post.get('platform')}",
        f"permalink={post.get('permalink')}",
        f"published_at={post.get('published_at')}",
        "",
        "CAPTION:",
        post.get("caption") or "(leeg)",
        "",
        "MEDIA VOOR DIT VERZOEK:",
        f"coverage={media_prep.get('coverage')}",
        f"images_for_model={len(media_prep.get('images_for_model') or [])}",
        f"full_video_to_model={media_prep.get('full_video_to_model')}",
        f"audio_to_model={media_prep.get('audio_to_model')}",
    ]
    for img in media_prep.get("images_for_model") or []:
        ts = img.get("timestamp_s")
        ts_bit = f" @ {ts}s" if ts is not None else ""
        lines.append(f"- {img.get('role')}{ts_bit}: local path {img.get('path')} ({img.get('bytes')} bytes)")
    if media_prep.get("missing"):
        lines.append("ONTBREKEND: " + "; ".join(media_prep["missing"]))
    if media_prep.get("limitations"):
        lines.append("BEPERKINGEN:")
        for lim in media_prep["limitations"]:
            lines.append(f"- {lim}")
    lines.extend(
        [
            "",
            "MEETGEGEVENS (feitelijk uit post-record; géén Excel-beoordeling):",
            str(metrics),
            "",
            "CONTENTPIJLERS (bestaande legenda):",
            ", ".join(pillars) or "(geen)",
            "",
            "FORMATREGELS:",
            format_pack.get("instruction") or "",
            "ELIGIBLE FORMATS:",
        ]
    )
    for fmt in format_pack.get("eligible_formats") or []:
        lines.append(f"- {fmt.get('code')}: {fmt.get('explanation')}")
    if not format_pack.get("eligible_formats"):
        lines.append("(geen eligible formatcodes voor deze contentsoort)")
    lines.extend(
        [
            "",
            "Antwoord als JSON-object met exact deze velden:",
            "observations (array van {evidence_ref, fact}; minstens één inhoudelijk item OF vul unassessable),",
            "proposed_format_code (string of 'Geen passend bestaand format' / 'Niet vast te stellen'),",
            "format_rationale, format_uncertainty,",
            "proposed_pillar, proposed_hook,",
            "ai_insight, ai_action (inhoudelijk; geen lege placeholders),",
            "hypotheses (array; duidelijk als hypothese),",
            "unassessable (array),",
            "limitations_acknowledged (array).",
            "In observations: alleen zichtbare feiten (beeld/caption) of letterlijke metric-feiten — geen oorzaakclaims.",
            "In ai_insight: scheid zichtbaar / cijfers / hypothese in de tekst (bijv. 'Zichtbaar: … Cijfers: … Hypothese: …').",
            "Voorbeeld fout: 'weinig interactie, dus het statische beeld werkte niet' → dat is een onbewezen causale claim.",
            "Voorbeeld goed: 'Cijfers: 0 comments. Hypothese: een carrousel of reel kán meer interactie geven — niet bewezen.'",
            "Ongeldige/lege JSON wordt niet als geslaagde analyse opgeslagen.",
            "Geen gezamenlijk oordeel met mens. Geen Excel-velden overschrijven.",
        ]
    )
    return "\n".join(lines)


def build_request_package(
    *,
    role: str,
    post: dict[str, Any],
    media_prep: dict[str, Any],
    all_formats: list[dict[str, str]],
    pillars: list[str],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    bundle = load_instruction_bundle()
    format_pack = filter_formats_for_role(role, all_formats)
    user = build_user_prompt(
        role=role,
        post=post,
        media_prep=media_prep,
        format_pack=format_pack,
        pillars=pillars,
        metrics=metrics,
    )
    return {
        "prompt_version": PROMPT_VERSION,
        "provider_expected": "Google Gemini Developer API",
        "model_expected_from_env": True,
        "not_claude": True,
        "instruction_bundle": {
            "included": bundle["included"],
            "excluded_for_this_trial": bundle["excluded_for_this_trial"],
            "system_chars": len(bundle["system_text"]),
            "user_chars": len(user),
        },
        "messages_preview": {
            "system_excerpt": bundle["system_text"][:500] + ("…" if len(bundle["system_text"]) > 500 else ""),
            "user_full": user,
        },
        "system_text": bundle["system_text"],
        "user_text": user,
        "format_pack": format_pack,
        "media_attachments_planned": media_prep.get("images_for_model") or [],
        "excel_assessment_included": False,
        "excel_insight_included": False,
        "excel_action_included": False,
    }
