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

    claude = claude_connection_status()
    prompts = load_analysis_prompt_bundle()
    return {
        "configured": bool(base_url and api_key and model),
        "has_base_url": bool(base_url),
        "base_host": host,
        "has_api_key": bool(api_key),
        "model": model or "",
        "gemini": {
            "provider": "Google Gemini Developer API",
            "configured": bool(base_url and api_key and model),
            "model": model or "",
            "has_api_key": bool(api_key),
            "base_host": host,
        },
        "claude": claude,
        "analysis_prompts": {
            "prompt_version": prompts["prompt_version"],
            "ready": prompts["ready"],
            "missing_files": prompts["missing_files"],
            "files": prompts["files"],
            "data_expectations": prompts.get("data_expectations") or {},
        },
        "notes": [
            "AI Connections shows API links (Gemini + Claude). No key values.",
            "This page does not start an AI request.",
            "Claude analyses use Maaike's Social Agent prompt files.",
            "Without CLAUDE_API_KEY / ANTHROPIC_API_KEY Claude stays off; set them in .env (server).",
        ],
    }
