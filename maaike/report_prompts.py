"""Load real Social Agent report instructions. Never invent missing prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SOCIAL_AGENT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports" / "redrock" / "social_agent"
VOORBEELD_DIR = SOCIAL_AGENT_DIR / "voorbeeldrapporten"
PROMPT_VERSION = "maaike-rapporten-v2.2"
CLIENT_ANALYSIS_SUPPLEMENT = "aanvullingen/klantrapport-analyse-regels-v2.2.txt"

TREND_FILE = "Trendrapport - opbouw en aanpak.txt"
CLIENT_FILE = "Klantrapport - opbouw en aanpak.txt"
RAPPORTBOUW_FILE = "Rapportopbouw - werkwijze.txt"
ROLE_FILE = "Role - Algemene instructies.txt"
QUALITY_FILE = "Kwaliteitsstandaard.txt"
ACTIEPLAN_FILE = "Actieplan - werkwijze.txt"
STYLE_NOTES_FILE = "voorbeeldrapporten/_style_notes.md"
TREND_EXAMPLE_PDF = "voorbeeldrapporten/Social Trend Radar - Voorbeeld rapport.pdf"
CLIENT_EXAMPLE_PDF = "voorbeeldrapporten/Maandelijks klant rapport - Voorbeeld.pdf"


def _read(name: str) -> str:
    path = SOCIAL_AGENT_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def internet_search_capability() -> dict[str, Any]:
    """Native Gemini Grounding with Google Search (same AI_API_KEY); no extra provider."""
    from maaike.gemini_native import search_capability

    return search_capability()


def load_report_instruction_bundle(report_type: str) -> dict[str, Any]:
    trend = _read(TREND_FILE)
    client = _read(CLIENT_FILE)
    bouw = _read(RAPPORTBOUW_FILE)
    role = _read(ROLE_FILE)
    quality = _read(QUALITY_FILE)
    actieplan = _read(ACTIEPLAN_FILE)
    style_notes = _read(STYLE_NOTES_FILE)
    client_supplement = _read(CLIENT_ANALYSIS_SUPPLEMENT) if report_type == "client" else ""
    search = internet_search_capability()
    trend_example = (SOCIAL_AGENT_DIR / TREND_EXAMPLE_PDF).exists()
    client_example = (SOCIAL_AGENT_DIR / CLIENT_EXAMPLE_PDF).exists()

    if report_type == "trend":
        primary = trend
        primary_label = TREND_FILE.replace(".txt", ".docx")
        required_sources = [
            "Externe trends/platformupdates (websearch / Frankwatching / Social Media Today / officiële platformbronnen)",
            "Google Trends / AnswerThePublic / Ahrefs waar relevant",
            "Handmatig toegevoegde bronnen met titel, URL, publicatiedatum, raadpleegdatum",
        ]
        chapters = [
            "Titelpagina of openingsblok",
            "Korte positionering van deze editie",
            "Managementsamenvatting",
            "Belangrijkste trends en ontwikkelingen",
            "Platform- en formatverschuivingen",
            "Contentkansen voor maand x+2",
            "Zoekclusters en opvallende richtingen",
            "Conclusie en prioriteiten",
            "Bronoverzicht",
        ]
        chapter_keys = [
            "positionering",
            "managementsamenvatting",
            "belangrijkste_trends",
            "platform_verschuivingen",
            "contentkansen",
            "zoekclusters",
            "conclusie",
        ]
    elif report_type == "client":
        primary = client
        primary_label = CLIENT_FILE.replace(".txt", ".docx")
        required_sources = [
            "Klantstrategie / startantwoorden in dashboard",
            "Post performance en formats uit Logs/Excel",
            "AI-analyses + menselijke feedback/eindconclusies (indien aanwezig)",
            "Passend trendrapport (of expliciet gedeeltelijk zonder)",
            "SEO/SERP/Ahrefs/websearch alleen indien als bron aangeleverd — anders: Niet onderzocht / onvoldoende gegevens",
            "Concurrentensignalen alleen indien aangeleverd — anders: Niet onderzocht / onvoldoende gegevens",
            "Instructies/voorbeeldrapporten tellen niet als onderzoeksbron",
        ]
        chapters = [
            "Input van brainstorm voor planning MAAND JAAR",
            "Wat dit betekent per kanaal",
            "SEO en SERP",
            "Concurrenten en best practices",
            "Hooks en formats om te testen",
            "Wat laten liggen of aanscherpen",
        ]
        chapter_keys = [
            "input_brainstorm",
            "per_kanaal",
            "seo_serp",
            "concurrenten",
            "hooks_formats_testen",
            "laten_liggen_aanscherpen",
        ]
    else:
        raise ValueError(f"Onbekend rapporttype: {report_type}")

    system_parts = [
        "Je werkt voor Red Rock Agency. Gebruik uitsluitend de meegeleverde instructies en data.",
        "Verzin geen cijfers. Onderscheid feiten, trends/verbanden en hypotheses/suggesties.",
        "Claim geen internetonderzoek als dat niet is uitgevoerd. Claim geen significant verschil zonder onderbouwing.",
        "Gebruik altijd de naam Red Rock Agency.",
        "Voorbeeld-PDF’s mogen alleen stijl/dichtheid/hoofdstukvolgorde inspireren — nooit voorbeeldcijfers of klantconclusies overnemen.",
        "BRONREGELS (hard):",
        "- Instructies, rapportopbouw, rolteksten, kwaliteitsstandaard, actieplan-werkwijze en voorbeeldrapporten zijn GEEN onderzoeksbronnen.",
        "- Geen claims over Ahrefs, SEO/SERP, concurrenten of trends zonder bijbehorende aangeleverde bronnen in de invoersnapshot.",
        '- Ontbrekende bronnen expliciet benoemen als: "Niet onderzocht / onvoldoende gegevens".',
        "- Verzin geen bevindingen om verplichte hoofdstukken te vullen; liever die zin dan verzonnen onderzoek.",
        "",
        f"=== {primary_label} ===",
        primary[:16000] if primary else "(bestand ontbreekt)",
        "",
        f"=== {RAPPORTBOUW_FILE.replace('.txt', '.docx')} ===",
        bouw[:10000] if bouw else "(bestand ontbreekt)",
        "",
        f"=== {ROLE_FILE.replace('.txt', '.docx')} ===",
        role[:8000] if role else "(bestand ontbreekt)",
        "",
        f"=== {QUALITY_FILE.replace('.txt', '.docx')} ===",
        quality[:6000] if quality else "(bestand ontbreekt)",
    ]
    if report_type == "client":
        system_parts.extend(
            [
                "",
                f"=== {ACTIEPLAN_FILE.replace('.txt', '.docx')} ===",
                (
                    "Actieplan is de vertaallaag NA klantrapport/analyse naar concrete volgende stappen. "
                    "Lever een action_plan-blok; menselijke review/goedkeuring blijft verplicht vóór planning. "
                    "Geen Ahrefs/SEO/concurrent-/trendclaims in het actieplan zonder aangeleverde bronnen."
                ),
                actieplan[:10000] if actieplan else "(bestand ontbreekt)",
            ]
        )
        if client_supplement:
            system_parts.extend(
                [
                    "",
                    f"=== Backend-aanvulling ({CLIENT_ANALYSIS_SUPPLEMENT}) ===",
                    "Oorspronkelijke Maaike-bronbestanden blijven leidend; onderstaande regels zijn een "
                    "versieerbare aanvulling op analyse-taal en vergelijkingen.",
                    client_supplement[:8000],
                ]
            )
    if style_notes:
        system_parts.extend(["", f"=== {STYLE_NOTES_FILE} ===", style_notes[:4000]])

    supporting = {
        "rapportopbouw": {"file": RAPPORTBOUW_FILE, "chars": len(bouw), "loaded": bool(bouw)},
        "role": {"file": ROLE_FILE, "chars": len(role), "loaded": bool(role)},
        "quality": {"file": QUALITY_FILE, "chars": len(quality), "loaded": bool(quality)},
        "style_notes": {"file": STYLE_NOTES_FILE, "chars": len(style_notes), "loaded": bool(style_notes)},
        "trend_example_pdf": {"file": TREND_EXAMPLE_PDF, "loaded": trend_example},
        "client_example_pdf": {"file": CLIENT_EXAMPLE_PDF, "loaded": client_example},
    }
    if report_type == "client":
        supporting["actieplan"] = {
            "file": ACTIEPLAN_FILE,
            "chars": len(actieplan),
            "loaded": bool(actieplan),
            "role": "After client report insights → concrete next steps; human approval required.",
        }
        supporting["analysis_supplement"] = {
            "file": CLIENT_ANALYSIS_SUPPLEMENT,
            "chars": len(client_supplement),
            "loaded": bool(client_supplement),
            "role": "Versioned backend rules; does not replace original Maaike source files.",
        }

    missing = [
        name
        for name, body in (
            (primary_label, primary),
            (RAPPORTBOUW_FILE, bouw),
            (ROLE_FILE, role),
            (QUALITY_FILE, quality),
        )
        if not body
    ]
    if report_type == "client" and not actieplan:
        missing.append(ACTIEPLAN_FILE)
    if report_type == "client" and not client_supplement:
        missing.append(CLIENT_ANALYSIS_SUPPLEMENT)

    return {
        "prompt_version": PROMPT_VERSION,
        "report_type": report_type,
        "primary_file": primary_label,
        "primary_chars": len(primary),
        "primary_loaded": bool(primary),
        "supporting_files": supporting,
        "required_sources": required_sources,
        "chapters": chapters,
        "chapter_keys": chapter_keys,
        "includes_action_plan": report_type == "client",
        "internet_search": search,
        "system_text": "\n".join(system_parts),
        "system_chars": sum(len(p) for p in system_parts),
        "missing_instructions": missing,
        "not_invented": True,
        "clusters_excluded": True,
        "clusters_note": "Geen apart cluster-promptbestand gevonden; clusters blijven buiten deze stap.",
    }
