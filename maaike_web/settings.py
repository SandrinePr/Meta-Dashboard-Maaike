"""URLs for the React app and this API. Secrets stay out of the frontend."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from dotenv import load_dotenv

_DEFAULT_FRONTEND = "http://127.0.0.1:5173"
_DEFAULT_BACKEND = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class WebSettings:
    frontend_url: str
    backend_url: str
    cors_origins: tuple[str, ...]
    oauth_redirect_uri: str
    session_secret: str

    def public(self) -> dict[str, str | list[str]]:
        """Values the browser may see. The session secret is not included."""
        return {
            "frontend_url": self.frontend_url,
            "backend_url": self.backend_url,
            "cors_origins": list(self.cors_origins),
            "oauth_redirect_uri": self.oauth_redirect_uri,
        }


def load_settings() -> WebSettings:
    load_dotenv(override=False)
    frontend = _trim_url(os.getenv("MAAIKE_FRONTEND_URL", ""), _DEFAULT_FRONTEND)
    backend = _trim_url(os.getenv("MAAIKE_BACKEND_URL", ""), _DEFAULT_BACKEND)
    raw_origins = os.getenv("MAAIKE_CORS_ORIGINS", "").strip()
    if raw_origins:
        configured = tuple(part.strip().rstrip("/") for part in raw_origins.split(",") if part.strip())
    else:
        configured = (frontend,)
    origins = _with_loopback_aliases(configured)
    redirect = os.getenv("MAAIKE_WEB_OAUTH_REDIRECT_URI", "").strip()
    if not redirect:
        redirect = f"{backend}/api/meta/callback"
    session_secret = os.getenv("MAAIKE_SESSION_SECRET", "").strip() or secrets.token_urlsafe(32)
    return WebSettings(
        frontend_url=frontend,
        backend_url=backend,
        cors_origins=origins,
        oauth_redirect_uri=redirect,
        session_secret=session_secret,
    )


def _trim_url(value: str, default: str) -> str:
    text = value.strip() or default
    return text.rstrip("/")


def _with_loopback_aliases(origins: tuple[str, ...]) -> tuple[str, ...]:
    """Allow both 127.0.0.1 and localhost for the same scheme/port."""
    ordered: list[str] = []
    seen: set[str] = set()
    for origin in origins:
        candidates = [origin]
        if "://127.0.0.1" in origin:
            candidates.append(origin.replace("://127.0.0.1", "://localhost", 1))
        elif "://localhost" in origin:
            candidates.append(origin.replace("://localhost", "://127.0.0.1", 1))
        for item in candidates:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
    return tuple(ordered)
