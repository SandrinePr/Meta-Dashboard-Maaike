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
from starlette.responses import JSONResponse, Response

Role = Literal["admin", "editor", "viewer", "guest"]

_VALID_ROLES = frozenset({"admin", "editor", "viewer", "guest"})

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


def guest_identity(*, auth_enabled: bool) -> AuthIdentity:
    """Someone who opened the site without a HAMSTER login."""
    return AuthIdentity(
        username="",
        role="guest",
        auth_enabled=auth_enabled,
        role_enforced=auth_enabled,
    )


def resolve_identity(request: Request) -> AuthIdentity | Response:
    """Anyone with the link can use HAMSTER. No login screen and no browser popup.

    A valid Basic Auth header still selects admin, editor or viewer when those
    accounts exist. Without that header everyone gets the open role.
    """
    accounts = load_auth_accounts()
    open_user = AuthIdentity(
        username="open",
        role="viewer",
        auth_enabled=False,
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
    return AuthIdentity(
        username="open",
        role="viewer",
        auth_enabled=True,
        role_enforced=True,
    )


def path_requires_admin(path: str) -> bool:
    """Kept for callers. Feature access is no longer split by role."""
    return False


def path_requires_editor_or_admin(path: str, method: str) -> bool:
    """Kept for callers. Mutations are available to everyone inside the app."""
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
    """App access is already resolved. Technisch beheer is not a separate role."""
    return identity_from_request(request)


def require_editor_or_admin(request: Request) -> AuthIdentity:
    """App access is already resolved. Editing is not a separate role."""
    return identity_from_request(request)


def session_payload(identity: AuthIdentity) -> dict:
    return {
        "username": identity.username or None,
        "role": identity.role,
        "auth_enabled": identity.auth_enabled,
        "role_enforced": False,
        "can_tech_admin": True,
        "can_edit_clients": True,
        "can_delete_clients": True,
        "login_required": False,
        "labels": {
            "admin": "HAMSTER",
            "editor": "HAMSTER",
            "viewer": "HAMSTER",
            "guest": "HAMSTER",
        },
        "note_nl": "Iedereen in HAMSTER gebruikt dezelfde functies. Toegang tot de app zelf blijft apart.",
    }
