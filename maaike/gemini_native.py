"""Native Gemini Developer API helpers (generateContent + Google Search grounding).

Uses the same AI_API_KEY as the OpenAI-compatible route. Grounding with Google Search
is NOT available on the OpenAI-compat /chat/completions path — this module calls
generativelanguage.googleapis.com/v1beta/models/{model}:generateContent.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from maaike.ai_trial import OFFICIAL_RATES

SEARCH_RATE = {
    "currency": "USD",
    "free_queries_per_month": 5000,
    "paid_per_1000_queries": 14.0,
    "paid_per_query": 0.014,
    "daily_cap_rpd": 1500,
    "rate_date": "2026-10-30",
    "source_url": "https://ai.google.dev/gemini-api/docs/pricing",
    "docs_url": "https://ai.google.dev/gemini-api/docs/google-search",
    "notes": (
        "Gemini 3+ Grounding with Google Search: 5.000 gratis zoekrequests/maand "
        "(gedeeld), daarna $14 / 1.000 requests; daglimiet 1.500 RPD. "
        "Facturatie per door het model uitgevoerde zoekquery."
    ),
}

NATIVE_GENERATE_HOST = "generativelanguage.googleapis.com"


def load_native_config() -> dict[str, Any]:
    load_dotenv(override=False)
    api_key = os.getenv("AI_API_KEY", "").strip()
    model = os.getenv("AI_MODEL", "").strip() or OFFICIAL_RATES["model"]
    return {
        "api_key": api_key,
        "model": model,
        "has_api_key": bool(api_key),
        "native_endpoint": f"https://{NATIVE_GENERATE_HOST}/v1beta/models/{model}:generateContent",
        "openai_compat_base": os.getenv("AI_BASE_URL", "").strip(),
    }


def search_capability() -> dict[str, Any]:
    """Public status: grounding available when Gemini API key + model are set."""
    cfg = load_native_config()
    available = bool(cfg["has_api_key"] and cfg["model"].startswith("gemini"))
    return {
        "available": available,
        "provider": "Google Gemini Developer API (native generateContent)",
        "model": cfg["model"],
        "exact_model_id": cfg["model"],
        "route": "native_generate_content_google_search",
        "openai_compat_supports_grounding": False,
        "tools": ["google_search"] if available else [],
        "citations": "url_citation / groundingMetadata.groundingChunks when search runs",
        "missing_setting": None if available else "AI_API_KEY (and AI_MODEL=gemini-*) in .env",
        "search_pricing": SEARCH_RATE,
        "token_pricing": OFFICIAL_RATES,
        "hard_search_budget_guaranteed": False,
        "hard_budget_note": (
            "A maximum budget can be used as an estimate gate before the request. "
            "The number of search queries is set on the model during the call; that is not a hard "
            "mid-flight cost limit."
        ),
        "reason": (
            "Native Gemini Grounding with Google Search via generateContent + tools.google_search, "
            "same AI_API_KEY. OpenAI-compatible chat/completions does not support this grounding."
            if available
            else "AI_API_KEY or Gemini model missing; no search route active."
        ),
        "structured_json": {
            "supported_without_search": True,
            "combined_with_google_search": False,
            "generation_config_fields": ["responseMimeType", "responseSchema"],
            "note": (
                "For client reports (no search) the execute path can set "
                "responseMimeType=application/json and a responseSchema. "
                "Not enabled together with tools.google_search."
            ),
        },
        "note": (
            "Web pages/documents are source material, not application instructions. "
            "Only sources actually consulted (citations/grounding) are stored."
        ),
        "manual_sources_supported": True,
    }


def estimate_search_cost_usd(query_count_low: int, query_count_high: int) -> dict[str, Any]:
    """Estimate search-tool cost; free-tier remaining unknown → band includes $0 and paid."""
    low_paid = query_count_low * SEARCH_RATE["paid_per_query"]
    high_paid = query_count_high * SEARCH_RATE["paid_per_query"]
    return {
        "assumed_queries": {"low": query_count_low, "high": query_count_high, "known": False},
        "estimated_search_cost_usd": {
            "low_if_free_quota": 0.0,
            "high_if_fully_paid": round(high_paid, 5),
            "paid_band_if_no_free_quota": {"low": round(low_paid, 5), "high": round(high_paid, 5)},
        },
        "free_quota_remaining_known": False,
        "rate": SEARCH_RATE,
        "note": "Remaining free search quota is unknown; show both $0 and the paid band.",
    }


def _parse_grounding(body: dict[str, Any]) -> dict[str, Any]:
    """Extract search queries and consulted sources from generateContent response."""
    candidates = body.get("candidates") or []
    if not candidates:
        return {"queries": [], "sources": [], "citations": [], "text": ""}
    cand = candidates[0] if isinstance(candidates[0], dict) else {}
    parts = ((cand.get("content") or {}).get("parts")) or []
    texts = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
    text = "\n".join(t for t in texts if t)
    meta = cand.get("groundingMetadata") or {}
    queries = list(meta.get("webSearchQueries") or [])
    sources = []
    for chunk in meta.get("groundingChunks") or []:
        if not isinstance(chunk, dict):
            continue
        web = chunk.get("web") or {}
        uri = str(web.get("uri") or "").strip()
        title = str(web.get("title") or "").strip() or (urlparse(uri).netloc if uri else "")
        if uri or title:
            sources.append(
                {
                    "title": title or "Bron",
                    "url": uri,
                    "published_at": None,
                    "source_kind": "gemini_grounding",
                    "consulted": True,
                }
            )
    citations = []
    for support in meta.get("groundingSupports") or []:
        if not isinstance(support, dict):
            continue
        segment = support.get("segment") or {}
        citations.append(
            {
                "text": str(segment.get("text") or ""),
                "start_index": segment.get("startIndex"),
                "end_index": segment.get("endIndex"),
                "chunk_indices": support.get("groundingChunkIndices") or [],
            }
        )
    usage = body.get("usageMetadata") or {}
    return {
        "queries": queries,
        "sources": sources,
        "citations": citations,
        "text": text,
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount"),
            "completion_tokens": usage.get("candidatesTokenCount"),
            "total_tokens": usage.get("totalTokenCount"),
            "thoughts_tokens": usage.get("thoughtsTokenCount"),
            "reported": bool(usage),
        },
        "finish_reason": cand.get("finishReason"),
    }


def generate_content(
    *,
    system_text: str,
    user_text: str,
    enable_google_search: bool,
    max_output_tokens: int = 4096,
    timeout_s: int = 180,
    response_mime_type: str | None = None,
    response_schema: dict[str, Any] | None = None,
    model: str | None = None,
    thinking_level: str | None = None,
) -> dict[str, Any]:
    """One native generateContent call. No automatic retries.

    Optional ``model`` overrides AI_MODEL for this single call only.
    Optional ``thinking_level`` sets generationConfig.thinkingConfig.thinkingLevel.
    """
    cfg = load_native_config()
    if not cfg["has_api_key"]:
        raise ValueError("AI_API_KEY ontbreekt — native Gemini-aanvraag niet mogelijk.")
    model_id = (model or cfg["model"] or "").strip()
    if not model_id:
        raise ValueError("AI_MODEL ontbreekt.")
    if enable_google_search and (response_mime_type or response_schema):
        raise ValueError(
            "Gestructureerde JSON-uitvoer (responseSchema) wordt niet gecombineerd "
            "met Google Search in deze route."
        )
    url = f"https://{NATIVE_GENERATE_HOST}/v1beta/models/{model_id}:generateContent"
    generation_config: dict[str, Any] = {
        "maxOutputTokens": max_output_tokens,
        "temperature": 0.3,
    }
    if thinking_level:
        generation_config["thinkingConfig"] = {
            "thinkingLevel": str(thinking_level).strip().lower()
        }
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type
    if response_schema:
        generation_config["responseSchema"] = response_schema
    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": generation_config,
    }
    if enable_google_search:
        payload["tools"] = [{"google_search": {}}]
    try:
        response = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": cfg["api_key"],
            },
            json=payload,
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "http_status": None,
            "error": f"Netwerkfout zonder herhaling: {exc.__class__.__name__}",
            "error_code": None,
            "error_status": None,
            "provider_error": None,
            "endpoint": url,
            "retries": 0,
            "model": model_id,
            "thinking_level": thinking_level,
            "grounding": {"queries": [], "sources": [], "citations": [], "text": "", "usage": {}},
            "raw_keys": [],
        }
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        err = body.get("error") if isinstance(body, dict) else None
        message = ""
        error_code = None
        error_status = None
        if isinstance(err, dict):
            message = str(err.get("message") or "")
            error_code = err.get("code")
            error_status = err.get("status")
        return {
            "ok": False,
            "http_status": response.status_code,
            "error": message or f"HTTP {response.status_code} van Gemini (geen herhaling).",
            "error_code": error_code,
            "error_status": error_status,
            "provider_error": err if isinstance(err, dict) else None,
            "endpoint": url,
            "retries": 0,
            "model": model_id,
            "thinking_level": thinking_level,
            "grounding": _parse_grounding(body) if isinstance(body, dict) else {},
            "raw_keys": list(body.keys()) if isinstance(body, dict) else [],
        }
    grounding = _parse_grounding(body)
    return {
        "ok": True,
        "http_status": response.status_code,
        "error": None,
        "model": model_id,
        "thinking_level": thinking_level,
        "endpoint": url,
        "retries": 0,
        "grounding": grounding,
        "raw_keys": list(body.keys()) if isinstance(body, dict) else [],
        "enable_google_search": enable_google_search,
    }
