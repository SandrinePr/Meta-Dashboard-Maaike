"""Safe AI configuration status for Maaike. Never returns secrets or starts a request."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from dotenv import load_dotenv


def public_ai_status() -> dict:
    """Read AI_* from the environment. Opening a page must not call a provider."""
    load_dotenv(override=False)
    base_url = os.getenv("AI_BASE_URL", "").strip()
    api_key = os.getenv("AI_API_KEY", "").strip()
    model = os.getenv("AI_MODEL", "").strip()
    host = urlparse(base_url).netloc if base_url else ""
    from maaike.claude_analysis import claude_connection_status, load_analysis_prompt_bundle

    from maaike.prompt_files import social_agent_status

    claude = claude_connection_status()
    prompts = load_analysis_prompt_bundle()
    prompt_paths = social_agent_status()
    gemini_ok = bool(base_url and api_key and model)
    return {
        "configured": bool(claude.get("configured") or gemini_ok),
        "active_provider": (
            "Anthropic Claude (postfeedback) + Google Gemini (rapporten)"
            if claude.get("configured") and gemini_ok
            else ("Anthropic Claude" if claude.get("configured") else ("Google Gemini Developer API" if gemini_ok else ""))
        ),
        "has_base_url": bool(base_url),
        "base_host": host,
        "has_api_key": bool(api_key),
        "model": model or "",
        "gemini": {
            "provider": "Google Gemini Developer API",
            "configured": gemini_ok,
            "model": model or "",
            "has_api_key": bool(api_key),
            "base_host": host,
            "used_for": [
                "Klantrapport execute",
                "Trendrapport execute",
                "AI Trial (intern)",
            ],
        },
        "claude": {
            **claude,
            "optional": False,
            "used_for": ["Postfeedback Prepare/Execute in Logs / Media & insight"],
            "required_for_reports": False,
            "required_for_post_feedback": True,
        },
        "analysis_prompts": {
            "prompt_version": prompts["prompt_version"],
            "ready": prompts["ready"],
            "missing_files": prompts["missing_files"],
            "files": prompts["files"],
            "data_expectations": prompts.get("data_expectations") or {},
            "root": prompt_paths.get("root"),
            "using_tracked": prompt_paths.get("using_tracked"),
        },
        "notes": [
            "Postfeedback (Prepare/Execute): Claude via CLAUDE_API_KEY (of ANTHROPIC_API_KEY).",
            "Klantrapport en trendrapport: Gemini via AI_BASE_URL / AI_API_KEY / AI_MODEL.",
            "Bewerkbare prompts: Settings → AI Connections → Promptinstellingen (opgeslagen in SQLite).",
            "Promptbestanden komen uit maaike/prompts/social_agent (meegeleverd in de deploy).",
            "Deze pagina start geen AI-aanvraag.",
        ],
    }
