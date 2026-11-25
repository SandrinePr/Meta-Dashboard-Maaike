"""Role-based access for HAMSTER (admin / editor / viewer).

Credentials (HTTP Basic Auth):
  - Admin:  MAAIKE_BASIC_AUTH_USER / MAAIKE_BASIC_AUTH_PASSWORD
  - Editor: MAAIKE_EDITOR_AUTH_USER / MAAIKE_EDITOR_AUTH_PASSWORD  (Jet/Mo)
  - Viewer: MAAIKE_VIEWER_AUTH_USER / MAAIKE_VIEWER_AUTH_PASSWORD  (read-focused)

When no Basic Auth password is set, the app stays open and uses
MAAIKE_DEFAULT_ROLE (default: admin). Production should set admin (and
editor) passwords so roles are enforced for every request.
"""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request
from starlette.responses import Response

Role = Literal["admin", "editor", "viewer"]

_VALID_ROLES = frozenset({"admin", "editor", "viewer"})

# Paths always open (health, OAuth callback, cron wake-up).
PUBLIC_PATHS = frozenset(
    {
        "/api/health",
        "/api/meta/callback",
        "/api/canva/callback",
        "/api/report-planning/monthly-trend/trigger",
    }
)

# Technical admin APIs — require role=admin (also when hit via direct URL).
_ADMIN_API_PREFIXES = (
    "/api/ai-status",
    "/api/persist-status",
    "/api/persist/",
    "/api/prompt-settings",
    "/api/export/package.json",
    "/api/import/",
    "/api/report-planning",
)

_ADMIN_API_EXACT = frozenset(
    {
        "/api/export/package.json",
        "/api/ai-status",
        "/api/persist-status",
    }
)


@dataclass(frozen=True, slots=True)
class AuthIdentity:
    username: str
    role: Role
    auth_enabled: bool
    role_enforced: bool


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def load_auth_accounts() -> list[tuple[str, str, Role]]:
    """Return (username, password, role) for every configured Basic Auth account."""
    accounts: list[tuple[str, str, Role]] = []
    admin_user = _env("MAAIKE_BASIC_AUTH_USER", "maaike") or "maaike"
    admin_password = _env("MAAIKE_BASIC_AUTH_PASSWORD")
    if admin_password:
        accounts.append((admin_user, admin_password, "admin"))

    editor_user = _env("MAAIKE_EDITOR_AUTH_USER", "editor") or "editor"
    editor_password = _env("MAAIKE_EDITOR_AUTH_PASSWORD")
    if editor_password:
        accounts.append((editor_user, editor_password, "editor"))

    viewer_user = _env("MAAIKE_VIEWER_AUTH_USER", "viewer") or "viewer"
    viewer_password = _env("MAAIKE_VIEWER_AUTH_PASSWORD")
    if viewer_password:
        accounts.append((viewer_user, viewer_password, "viewer"))

    return accounts


def default_open_role() -> Role:
    raw = _env("MAAIKE_DEFAULT_ROLE", "admin").lower() or "admin"
    return raw if raw in _VALID_ROLES else "admin"  # type: ignore[return-value]


def parse_basic_auth(header: str | None) -> tuple[str, str] | None:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1].strip()).decode("utf-8")
    except Exception:
        return None
    user, _, pwd = decoded.partition(":")
    return user, pwd


def match_account(username: str, password: str, accounts: list[tuple[str, str, Role]]) -> AuthIdentity | None:
    for user, pwd, role in accounts:
        if secrets.compare_digest(username, user) and secrets.compare_digest(password, pwd):
            return AuthIdentity(
                username=user,
                role=role,
                auth_enabled=True,
                role_enforced=True,
            )
    return None


def resolve_identity(request: Request) -> AuthIdentity | Response:
    """Return identity or a 401 Response when Basic Auth is required but missing/wrong."""
    accounts = load_auth_accounts()
    path = request.url.path.rstrip("/") or "/"
    if path in PUBLIC_PATHS or path == "/api/health":
        # Public routes still get a neutral identity for downstream code.
        return AuthIdentity(
            username="",
            role=default_open_role(),
            auth_enabled=bool(accounts),
            role_enforced=False,
        )

    if not accounts:
        return AuthIdentity(
            username="open",
            role=default_open_role(),
            auth_enabled=False,
            role_enforced=False,
        )

    parsed = parse_basic_auth(request.headers.get("authorization"))
    if parsed:
        identity = match_account(parsed[0], parsed[1], accounts)
        if identity is not None:
            return identity

    return Response(
        content="Authenticatie vereist.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="HAMSTER"'},
        media_type="text/plain",
    )


def path_requires_admin(path: str) -> bool:
    cleaned = path.rstrip("/") or "/"
    if cleaned in _ADMIN_API_EXACT:
        return True
    for prefix in _ADMIN_API_PREFIXES:
        if cleaned == prefix.rstrip("/") or cleaned.startswith(prefix):
            return True
    # AI trial + Claude analyse tooling
    if "/ai-trial" in cleaned:
        return True
    if cleaned.endswith("/claude-analyze") or "/analysis/execute" in cleaned or "/analysis/mock" in cleaned:
        return True
    return False


def path_requires_editor_or_admin(path: str, method: str) -> bool:
    """Mutations that viewers must not perform."""
    method = method.upper()
    if method in {"GET", "HEAD", "OPTIONS"}:
        return False
    cleaned = path.rstrip("/") or "/"
    if cleaned.startswith("/api/"):
        # Viewers may not mutate anything under /api except public cron (already open).
        return True
    return False


def identity_from_request(request: Request) -> AuthIdentity:
    identity = getattr(request.state, "identity", None)
    if isinstance(identity, AuthIdentity):
        return identity
    return AuthIdentity(
        username="open",
        role=default_open_role(),
        auth_enabled=False,
        role_enforced=False,
    )


def require_admin(request: Request) -> AuthIdentity:
    identity = identity_from_request(request)
    if identity.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Dit scherm of deze actie is alleen voor technisch beheer. Vraag een beheerder om hulp.",
        )
    return identity


def require_editor_or_admin(request: Request) -> AuthIdentity:
    identity = identity_from_request(request)
    if identity.role not in {"admin", "editor"}:
        raise HTTPException(
            status_code=403,
            detail="Je hebt geen rechten voor deze actie. Vraag een editor of beheerder.",
        )
    return identity


def session_payload(identity: AuthIdentity) -> dict:
    return {
        "username": identity.username or None,
        "role": identity.role,
        "auth_enabled": identity.auth_enabled,
        "role_enforced": identity.role_enforced,
        "can_tech_admin": identity.role == "admin",
        "can_edit_clients": identity.role in {"admin", "editor"},
        "can_delete_clients": identity.role == "admin",
        "labels": {
            "admin": "Technisch beheer",
            "editor": "Editor (Jet/Mo)",
            "viewer": "Gewone gebruiker",
        },
        "note_nl": (
            "Rollen worden afgedwongen via HTTP Basic Auth (beheerder / editor / viewer)."
            if identity.role_enforced
            else (
                "Let op: er is geen Basic Auth-wachtwoord gezet. Iedereen op dit netwerk heeft "
                f"nu de standaardrol “{identity.role}” (MAAIKE_DEFAULT_ROLE). Zet "
                "MAAIKE_BASIC_AUTH_PASSWORD (en optioneel MAAIKE_EDITOR_AUTH_PASSWORD) voor echte rolcontrole."
            )
        ),
    }
