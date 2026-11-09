"""Read optional AI settings. The API key is never returned for display."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class AiConfig:
    base_url: str
    api_key: str
    model: str


def load_ai_config() -> AiConfig:
    load_dotenv()
    return AiConfig(
        base_url=os.getenv("AI_BASE_URL", "").strip(),
        api_key=os.getenv("AI_API_KEY", "").strip(),
        model=os.getenv("AI_MODEL", "").strip(),
    )


def is_configured(config: AiConfig | None = None) -> bool:
    cfg = config or load_ai_config()
    return bool(cfg.base_url and cfg.api_key and cfg.model)


def public_ai_status(config: AiConfig | None = None) -> dict[str, str | bool]:
    """Safe status for the settings page. Never includes the API key or full URL."""
    cfg = config or load_ai_config()
    host = ""
    if cfg.base_url:
        host = urlparse(cfg.base_url).netloc
    return {
        "configured": is_configured(cfg),
        "has_base_url": bool(cfg.base_url),
        "base_host": host,
        "has_api_key": bool(cfg.api_key),
        "model": cfg.model,
    }


def chat_completions_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return cleaned + "/chat/completions"
