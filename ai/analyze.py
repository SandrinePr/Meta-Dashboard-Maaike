"""Optional explanation call. Runs only when AI_BASE_URL, AI_API_KEY and AI_MODEL are set."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import requests

from ai.config import chat_completions_url, is_configured, load_ai_config

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

NOT_CONFIGURED_MESSAGE = (
    "AI is nog niet ingesteld. Automatische samenvatting en adviezen zijn niet beschikbaar. "
    "De cijfers hierboven zijn berekend uit opgeslagen metingen."
)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    status: str
    summary: str | None
    advice: list[str]
    model: str | None
    message: str


def can_request_analysis(ai_status: str, *, configured: bool) -> bool:
    """True only for an explicit new call. A stored analysis is never requested again."""
    return configured and ai_status in {"not_configured", "error"}


def parse_analysis_text(text: str) -> tuple[str, list[str]] | None:
    cleaned = _FENCE.sub("", text.strip())
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    advice = payload.get("advice")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(advice, list) or len(advice) != 3:
        return None
    lines = []
    for item in advice:
        if not isinstance(item, str) or not item.strip():
            return None
        lines.append(item.strip())
    return summary.strip(), lines


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "[verborgen]")
    return text


def run_analysis(
    snapshot: dict,
    *,
    system_prompt: str,
    user_prompt: str,
) -> AnalysisResult:
    """One chat call, or a clear not-configured result. No retries."""
    config = load_ai_config()
    if not is_configured(config):
        return AnalysisResult(
            status="not_configured",
            summary=None,
            advice=[],
            model=None,
            message=NOT_CONFIGURED_MESSAGE,
        )

    if "{snapshot_json}" in user_prompt:
        user_text = user_prompt.replace(
            "{snapshot_json}",
            json.dumps(snapshot, ensure_ascii=False),
        )
    else:
        user_text = (
            user_prompt.rstrip()
            + "\n\nCijfers (JSON):\n"
            + json.dumps(snapshot, ensure_ascii=False)
        )

    try:
        response = requests.post(
            chat_completions_url(config.base_url),
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.model,
                "temperature": 0.2,
                "max_tokens": 900,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("AI-analyse mislukt: %s", _redact(str(exc), config.api_key)[:300])
        return AnalysisResult(
            status="error",
            summary=None,
            advice=[],
            model=config.model,
            message=(
                "De AI-aanroep is mislukt. De cijfers van dit rapport blijven staan. "
                "Er is geen adviestekst opgeslagen."
            ),
        )

    if not isinstance(content, str):
        return AnalysisResult(
            status="error",
            summary=None,
            advice=[],
            model=config.model,
            message=(
                "Het AI-antwoord had niet de afgesproken vorm. "
                "Er is niets als advies opgeslagen."
            ),
        )
    parsed = parse_analysis_text(content)
    if parsed is None:
        return AnalysisResult(
            status="error",
            summary=None,
            advice=[],
            model=config.model,
            message=(
                "Het AI-antwoord had niet de afgesproken vorm. "
                "Er is niets als advies opgeslagen."
            ),
        )
    summary, advice = parsed
    return AnalysisResult(
        status="stored",
        summary=summary,
        advice=advice,
        model=config.model,
        message="Analyse opgeslagen.",
    )
