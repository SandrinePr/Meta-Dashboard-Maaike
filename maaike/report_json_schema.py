"""Gemini responseSchema helpers for report JSON — no paid calls."""

from __future__ import annotations

from typing import Any


def client_report_response_schema() -> dict[str, Any]:
    """OpenAPI-like schema for native Gemini responseSchema / responseJsonSchema."""
    six = {
        "type": "OBJECT",
        "properties": {
            "beter": {"type": "STRING"},
            "slechter": {"type": "STRING"},
            "verklaring": {"type": "STRING"},
            "herhalen": {"type": "STRING"},
            "stoppen": {"type": "STRING"},
            "testen": {"type": "STRING"},
        },
        "required": ["beter", "slechter", "verklaring", "herhalen", "stoppen", "testen"],
    }
    chapters = {
        "type": "OBJECT",
        "properties": {
            "input_brainstorm": {"type": "STRING"},
            "per_kanaal": {"type": "STRING"},
            "seo_serp": {"type": "STRING"},
            "concurrenten": {"type": "STRING"},
            "hooks_formats_testen": {"type": "STRING"},
            "laten_liggen_aanscherpen": {"type": "STRING"},
        },
        "required": [
            "input_brainstorm",
            "per_kanaal",
            "seo_serp",
            "concurrenten",
            "hooks_formats_testen",
            "laten_liggen_aanscherpen",
        ],
    }
    action_plan = {
        "type": "OBJECT",
        "properties": {
            "planning_note": {"type": "STRING"},
            "hoofdfocus": {"type": "STRING"},
            "waarom_nu": {"type": "STRING"},
            "actions": {"type": "ARRAY", "items": {"type": "STRING"}},
            "stop_or_test_decisions": {"type": "ARRAY", "items": {"type": "STRING"}},
            "watch_outs": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": [
            "planning_note",
            "hoofdfocus",
            "waarom_nu",
            "actions",
            "stop_or_test_decisions",
            "watch_outs",
        ],
    }
    return {
        "type": "OBJECT",
        "properties": {
            "six_answers": six,
            "chapters": chapters,
            "action_plan": action_plan,
            "fully_researched": {"type": "BOOLEAN"},
            "unassessable": {"type": "ARRAY", "items": {"type": "STRING"}},
            "partial": {"type": "BOOLEAN"},
        },
        "required": ["six_answers", "chapters", "action_plan"],
    }


def trend_report_response_schema() -> dict[str, Any]:
    """OpenAPI-like schema for trend report JSON via Gemini responseSchema."""
    chapters = {
        "type": "OBJECT",
        "properties": {
            "positionering": {"type": "STRING"},
            "managementsamenvatting": {"type": "STRING"},
            "belangrijkste_trends": {"type": "STRING"},
            "platform_verschuivingen": {"type": "STRING"},
            "contentkansen": {"type": "STRING"},
            "zoekclusters": {"type": "STRING"},
            "conclusie": {"type": "STRING"},
        },
        "required": [
            "positionering",
            "managementsamenvatting",
            "belangrijkste_trends",
            "platform_verschuivingen",
            "contentkansen",
            "zoekclusters",
            "conclusie",
        ],
    }
    distinctions = {
        "type": "OBJECT",
        "properties": {
            "facts": {"type": "ARRAY", "items": {"type": "STRING"}},
            "trends": {"type": "ARRAY", "items": {"type": "STRING"}},
            "suggestions": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["facts", "trends", "suggestions"],
    }
    citation = {
        "type": "OBJECT",
        "properties": {
            "claim": {"type": "STRING"},
            "source_url": {"type": "STRING"},
        },
        "required": ["claim", "source_url"],
    }
    return {
        "type": "OBJECT",
        "properties": {
            "chapters": chapters,
            "distinctions": distinctions,
            "claims_with_citations": {"type": "ARRAY", "items": citation},
            "fully_researched": {"type": "BOOLEAN"},
            "partial": {"type": "BOOLEAN"},
            "unassessable": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["chapters", "distinctions", "claims_with_citations", "partial"],
    }


def structured_output_capability(*, enable_google_search: bool) -> dict[str, Any]:
    """Whether this call path can request application/json + responseSchema."""
    if enable_google_search:
        return {
            "supported": False,
            "reason": (
                "Gemini Grounding with Google Search is not combined with responseSchema "
                "in this app; structured JSON is disabled while search tools are on."
            ),
            "response_mime_type": None,
        }
    return {
        "supported": True,
        "reason": (
            "Native generateContent supports generationConfig.responseMimeType="
            "application/json and responseSchema when google_search is off."
        ),
        "response_mime_type": "application/json",
        "schema_name": "client_or_trend_report_v2_1",
    }
