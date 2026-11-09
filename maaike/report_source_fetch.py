"""Fetch report source page content over HTTP — no AI, no search billing."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "MaaikeTrendPrep/1.0 (+local research; Red Rock Agency; no AI fetch)"
)
MAX_BYTES = 800_000
TIMEOUT = 25


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if t == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if t == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text[:300]
        self._chunks.append(text)


def _now_date() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


def fetch_source_url(url: str, *, max_excerpt_chars: int = 3500) -> dict[str, Any]:
    """GET a URL and extract readable text. Never invents content."""
    cleaned = (url or "").strip()
    base: dict[str, Any] = {
        "url": cleaned,
        "fetch_status": "not_attempted",
        "content_fetched": False,
        "fetched_at": None,
        "http_status": None,
        "title_from_page": None,
        "excerpt": "",
        "content_chars": 0,
        "error": None,
        "counted_as_read_source": False,
    }
    if not cleaned:
        base["fetch_status"] = "invalid_url"
        base["error"] = "Lege URL."
        return base
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        base["fetch_status"] = "invalid_url"
        base["error"] = "Alleen http(s)-URL's."
        return base
    try:
        resp = requests.get(
            cleaned,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        base["http_status"] = int(resp.status_code)
        base["fetched_at"] = datetime.now(tz=timezone.utc).isoformat()
        if resp.status_code >= 400:
            base["fetch_status"] = "unreachable"
            base["error"] = f"HTTP {resp.status_code}"
            return base
        raw = resp.content[:MAX_BYTES]
        ctype = ""
        for enc in (resp.encoding, "utf-8", "latin-1"):
            if not enc:
                continue
            try:
                ctype = raw.decode(enc, errors="replace")
                break
            except LookupError:
                continue
        if not ctype.strip():
            base["fetch_status"] = "empty_body"
            base["error"] = "Lege response-body."
            return base
        extractor = _TextExtractor()
        try:
            extractor.feed(ctype)
        except Exception:
            # Fall back to crude strip
            text = re.sub(r"<[^>]+>", " ", ctype)
        else:
            text = " ".join(extractor._chunks)
        text = re.sub(r"\s+", " ", text).strip()
        excerpt = text[:max_excerpt_chars]
        base.update(
            {
                "fetch_status": "fetched",
                "content_fetched": True,
                "title_from_page": extractor.title or None,
                "excerpt": excerpt,
                "content_chars": len(text),
                "counted_as_read_source": bool(excerpt),
            }
        )
        return base
    except requests.Timeout:
        base["fetch_status"] = "timeout"
        base["error"] = "Timeout bij ophalen."
        base["fetched_at"] = datetime.now(tz=timezone.utc).isoformat()
        return base
    except requests.RequestException as exc:
        base["fetch_status"] = "unreachable"
        base["error"] = str(exc)[:400]
        base["fetched_at"] = datetime.now(tz=timezone.utc).isoformat()
        return base


def enrich_source_record(item: dict[str, Any], *, fetch: bool = True) -> dict[str, Any]:
    """Normalize a source dict; optionally fetch page content."""
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    published = str(item.get("published_at") or "").strip() or None
    consulted = str(item.get("consulted_at") or "").strip() or _now_date()
    finding = str(item.get("supported_finding") or item.get("finding") or "").strip()
    certainty = str(item.get("certainty") or "").strip() or None
    limitations = str(item.get("limitations") or "").strip() or None
    historical_ok = item.get("historical_ok")
    out = {
        "title": title or (urlparse(url).netloc if url else "Bron"),
        "url": url,
        "published_at": published,
        "consulted_at": consulted,
        "excerpt": str(item.get("excerpt") or "").strip(),
        "source_kind": str(item.get("source_kind") or "manual"),
        "supported_finding": finding or None,
        "certainty": certainty,
        "limitations": limitations,
        "historical_ok": historical_ok,
        "content_fetched": False,
        "fetch_status": "not_attempted",
        "fetched_at": None,
        "counted_as_read_source": False,
    }
    existing_excerpt = out["excerpt"]
    if fetch and url:
        fetched = fetch_source_url(url)
        out["fetch_status"] = fetched["fetch_status"]
        out["content_fetched"] = bool(fetched["content_fetched"])
        out["fetched_at"] = fetched["fetched_at"]
        out["http_status"] = fetched.get("http_status")
        out["fetch_error"] = fetched.get("error")
        if fetched.get("title_from_page") and (not title or title == urlparse(url).netloc):
            out["title"] = fetched["title_from_page"]
        if fetched.get("excerpt"):
            # Prefer freshly fetched text; keep manual excerpt as note if different
            out["excerpt"] = fetched["excerpt"]
            if existing_excerpt and existing_excerpt not in fetched["excerpt"]:
                out["manual_excerpt_note"] = existing_excerpt[:500]
        out["content_chars"] = fetched.get("content_chars") or len(out["excerpt"])
        out["counted_as_read_source"] = bool(out["excerpt"]) and out["content_fetched"]
    else:
        out["counted_as_read_source"] = bool(existing_excerpt)
        out["fetch_status"] = "manual_excerpt_only" if existing_excerpt else "url_only_not_read"
        out["content_fetched"] = False
    return out
