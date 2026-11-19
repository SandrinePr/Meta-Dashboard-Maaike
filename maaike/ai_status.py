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
        "configured": gemini_ok,
        "active_provider": "Google Gemini Developer API" if gemini_ok else "",
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
                "Postanalyse (Prepare/Execute in Logs / Media & insight)",
                "Klantrapport execute",
                "Trendrapport execute",
                "AI Trial",
            ],
        },
        "claude": {
            **claude,
            "optional": True,
            "used_for": ["Optionele Single Claude post analysis (Settings)"],
            "required_for_reports": False,
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
            "Actieve route voor analyse- en rapportknoppen: Gemini via AI_BASE_URL / AI_API_KEY / AI_MODEL.",
            "Claude is optioneel en niet vereist voor klantrapporten of standaard postanalyse.",
            "Promptbestanden komen uit maaike/prompts/social_agent (meegeleverd in de deploy).",
            "Deze pagina start geen AI-aanvraag.",
        ],
    }
