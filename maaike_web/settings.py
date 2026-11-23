"""URLs for the React app and this API. Secrets stay out of the frontend."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from dotenv import load_dotenv

_DEFAULT_FRONTEND = "https://127.0.0.1:5173"
_DEFAULT_BACKEND = "https://127.0.0.1:8000"


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


def _render_external_url() -> str:
    """Render injects RENDER_EXTERNAL_URL (https://…onrender.com) on web services."""
    return os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")


def _is_loopback(url: str) -> bool:
    lower = (url or "").lower()
    return "://127.0.0.1" in lower or "://localhost" in lower


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _stale_onrender_host(url: str, render_url: str) -> bool:
    """True when url points at a different *.onrender.com host than this service."""
    if not url or not render_url:
        return False
    host = _host(url)
    render_host = _host(render_url)
    if not host or not render_host or host == render_host:
        return False
    return host.endswith(".onrender.com") and render_host.endswith(".onrender.com")


def load_settings() -> WebSettings:
    load_dotenv(override=False)
    render_url = _render_external_url()
    frontend = _trim_url(os.getenv("MAAIKE_FRONTEND_URL", ""), "")
    backend = _trim_url(os.getenv("MAAIKE_BACKEND_URL", ""), "")
    if not frontend:
        frontend = render_url or _DEFAULT_FRONTEND
    if not backend:
        backend = render_url or _DEFAULT_BACKEND
    # On Render, never keep a leftover localhost or wrong onrender host from a copied .env.
    if render_url and (_is_loopback(frontend) or _stale_onrender_host(frontend, render_url)):
        frontend = render_url
    if render_url and (_is_loopback(backend) or _stale_onrender_host(backend, render_url)):
        backend = render_url
    raw_origins = os.getenv("MAAIKE_CORS_ORIGINS", "").strip()
    if raw_origins:
        configured = tuple(part.strip().rstrip("/") for part in raw_origins.split(",") if part.strip())
    else:
        configured = (frontend,)
    origins = _with_loopback_aliases(configured)
    redirect = os.getenv("MAAIKE_WEB_OAUTH_REDIRECT_URI", "").strip().rstrip("/")
    # Prefer the live service URL: empty, localhost leftovers, or a different onrender host.
    if (
        not redirect
        or (render_url and _is_loopback(redirect))
        or (render_url and _stale_onrender_host(redirect, render_url))
    ):
        redirect = f"{backend}/api/meta/callback"
    elif not redirect.endswith("/api/meta/callback"):
        # Keep an explicit full callback if set; otherwise force the known path on backend.
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
        if origin.startswith("http://"):
            candidates.append("https://" + origin[len("http://") :])
        elif origin.startswith("https://"):
            candidates.append("http://" + origin[len("https://") :])
        for item in candidates:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
    return tuple(ordered)
