"""Canva Connect: OAuth (PKCE) + PDF export for strategy proposals.

App type for Red Rock: **private or public** user-delegated app (authorization
code + PKCE + refresh). A **service** app cannot open a user's private designs
on their behalf and needs paid API credits — wrong fit for Maaike's workflow.

Only scope requested for import: ``design:content:read`` (PDF export).
Tokens live in sqlite table ``canva_oauth_secrets`` (excluded from JSON backups).
Never log or return raw tokens.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from dotenv import load_dotenv

log = logging.getLogger("maaike.canva")

CANVA_API = "https://api.canva.com/rest/v1"
CANVA_AUTHORIZE = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = f"{CANVA_API}/oauth/token"
DESIGN_ID_RE = re.compile(r"/design/([A-Za-z0-9_-]+)", re.IGNORECASE)

REQUIRED_SCOPES = ("design:content:read",)
# Minimal set — do not request write or brand-template scopes for this flow.
REQUEST_SCOPES = " ".join(REQUIRED_SCOPES)

APP_TYPE_NL = (
    "Gebruik een Canva Connect-app met gebruikerskoppeling (OAuth + PKCE). "
    "Kies Public (‘Anyone on Canva’) als Red Rock geen Canva Enterprise heeft. "
    "Private (‘Restricted to your Canva team’) kan alleen op Enterprise en moet door "
    "een Canva-teambeheerder worden goedgekeurd. Geen service-app."
)

ADMIN_STEPS_NL = (
    "Canva-beheerder (Developer Portal → Your apps → Create app): "
    "1) Kies Public (‘Anyone on Canva’) óf Private (‘Restricted to your Canva team’ — alleen "
    "Enterprise; goedkeuring via Canva Team admin in Team settings → Apps). "
    "2) Outside Canva → Configuration → Scopes → alleen design:content: Read "
    "(design:content:read). "
    "3) Outside Canva → Redirect URLs → voeg exact toe: {redirect}. "
    "4) Outside Canva → Configuration → Credentials → client ID + genereer client secret; "
    "zet die in Render (service hamster) als CANVA_CLIENT_ID en CANVA_CLIENT_SECRET. "
    "5) In HAMSTER → Klant inrichten → Canva-account koppelen (OAuth)."
)


class CanvaAccessError(ValueError):
    """Missing credentials, OAuth failure, or Canva refused access."""


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(timezone.utc).isoformat()


def extract_design_id(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("Plak een Canva-link.")
    match = DESIGN_ID_RE.search(cleaned)
    if not match:
        bare = cleaned.strip("/")
        if re.fullmatch(r"[A-Za-z0-9_-]{6,}", bare) and "://" not in bare:
            return bare
        raise ValueError("Geen Canva-design-id gevonden in de link.")
    return match.group(1)


def is_canva_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in {"canva.com", "www.canva.com"} or host.endswith(".canva.com")


def _env(name: str, default: str = "") -> str:
    load_dotenv(override=False)
    return (os.getenv(name) or default).strip()


def canva_client_id() -> str:
    return _env("CANVA_CLIENT_ID")


def canva_client_secret() -> str:
    return _env("CANVA_CLIENT_SECRET")


def canva_redirect_uri() -> str:
    explicit = _env("CANVA_REDIRECT_URI")
    if explicit:
        return explicit.rstrip("/")
    backend = (
        _env("MAAIKE_BACKEND_URL")
        or _env("RENDER_EXTERNAL_URL")
        or "https://hamster-8zgq.onrender.com"
    ).rstrip("/")
    return f"{backend}/api/canva/callback"


def canva_app_configured() -> bool:
    return bool(canva_client_id() and canva_client_secret())


def legacy_access_token() -> str:
    """Optional static token for emergency/dev; prefer OAuth + refresh."""
    return _env("CANVA_ACCESS_TOKEN")


def ensure_canva_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS canva_oauth_secrets (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            access_token TEXT NOT NULL DEFAULT '',
            refresh_token TEXT NOT NULL DEFAULT '',
            token_type TEXT NOT NULL DEFAULT 'Bearer',
            scope TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT '',
            connected_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            canva_user_hint TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS canva_oauth_pending (
            state TEXT PRIMARY KEY,
            code_verifier TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """
    )


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    if len(verifier) < 43:
        verifier = (verifier + secrets.token_urlsafe(32))[:96]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return verifier, challenge


def _basic_auth_header() -> dict[str, str]:
    client_id = canva_client_id()
    client_secret = canva_client_secret()
    if not client_id or not client_secret:
        raise CanvaAccessError(
            "CANVA_CLIENT_ID / CANVA_CLIENT_SECRET ontbreken op de server. "
            + ADMIN_STEPS_NL.format(redirect=canva_redirect_uri())
        )
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return {
        "Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def start_oauth(conn) -> dict[str, Any]:
    """Create PKCE challenge, store verifier server-side, return authorize URL."""
    ensure_canva_tables(conn)
    if not canva_app_configured():
        raise CanvaAccessError(
            "Canva-app nog niet geconfigureerd. "
            + ADMIN_STEPS_NL.format(redirect=canva_redirect_uri())
        )
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    redirect = canva_redirect_uri()
    now = _now()
    expires = now + timedelta(minutes=15)
    conn.execute(
        """
        INSERT OR REPLACE INTO canva_oauth_pending
            (state, code_verifier, redirect_uri, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (state, verifier, redirect, _iso(now), _iso(expires)),
    )
    # Drop stale pending rows
    conn.execute(
        "DELETE FROM canva_oauth_pending WHERE expires_at < ?",
        (_iso(now),),
    )
    params = {
        "code_challenge": challenge,
        "code_challenge_method": "s256",
        "scope": REQUEST_SCOPES,
        "response_type": "code",
        "client_id": canva_client_id(),
        "state": state,
        "redirect_uri": redirect,
    }
    return {
        "authorize_url": f"{CANVA_AUTHORIZE}?{urlencode(params)}",
        "state": state,
        "redirect_uri": redirect,
        "scopes": list(REQUIRED_SCOPES),
        "app_type_nl": APP_TYPE_NL,
    }


def _token_request(form: dict[str, str]) -> dict[str, Any]:
    response = requests.post(
        CANVA_TOKEN_URL,
        headers=_basic_auth_header(),
        data=form,
        timeout=45,
    )
    if response.status_code >= 400:
        # Never echo client secret; redact tokens if Canva echoes them.
        detail = _safe_error_body(response)
        raise CanvaAccessError(f"Canva token-endpoint weigerde (HTTP {response.status_code}): {detail}")
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise CanvaAccessError("Canva gaf geen access_token terug.")
    return payload


def _safe_error_body(response: requests.Response) -> str:
    try:
        data = response.json()
        msg = str(data.get("message") or data.get("error_description") or data.get("error") or "")
    except Exception:
        msg = (response.text or "")[:200]
    return redact_secrets(msg)


def redact_secrets(text: str, *extra: str) -> str:
    cleaned = str(text or "")
    for secret in (canva_client_secret(), legacy_access_token(), *extra):
        if secret and secret in cleaned:
            cleaned = cleaned.replace(secret, "[redacted]")
    # Common JWT-ish / bearer fragments
    cleaned = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1[redacted]", cleaned, flags=re.I)
    return cleaned


def _store_tokens(conn, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_canva_tables(conn)
    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or "").strip()
    if not access:
        raise CanvaAccessError("Lege access_token van Canva.")
    expires_in = int(payload.get("expires_in") or 14400)
    # Refresh slightly before expiry
    expires_at = _now() + timedelta(seconds=max(60, expires_in - 120))
    scope = str(payload.get("scope") or REQUEST_SCOPES)
    now = _iso(_now())
    existing = conn.execute(
        "SELECT connected_at FROM canva_oauth_secrets WHERE id = 1"
    ).fetchone()
    connected_at = str(existing["connected_at"] if existing and existing["connected_at"] else now)
    conn.execute(
        """
        INSERT INTO canva_oauth_secrets (
            id, access_token, refresh_token, token_type, scope,
            expires_at, connected_at, updated_at, canva_user_hint
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, '')
        ON CONFLICT(id) DO UPDATE SET
            access_token = excluded.access_token,
            refresh_token = CASE
                WHEN excluded.refresh_token != '' THEN excluded.refresh_token
                ELSE canva_oauth_secrets.refresh_token
            END,
            token_type = excluded.token_type,
            scope = excluded.scope,
            expires_at = excluded.expires_at,
            updated_at = excluded.updated_at
        """,
        (
            access,
            refresh,
            str(payload.get("token_type") or "Bearer"),
            scope,
            _iso(expires_at),
            connected_at,
            now,
        ),
    )
    return connection_status(conn)


def complete_oauth(conn, *, code: str, state: str) -> dict[str, Any]:
    ensure_canva_tables(conn)
    row = conn.execute(
        "SELECT code_verifier, redirect_uri, expires_at FROM canva_oauth_pending WHERE state = ?",
        (state,),
    ).fetchone()
    if not row:
        raise CanvaAccessError("Ongeldige of verlopen Canva OAuth-state. Start opnieuw met ‘Canva-account koppelen’.")
    if str(row["expires_at"] or "") < _iso(_now()):
        conn.execute("DELETE FROM canva_oauth_pending WHERE state = ?", (state,))
        raise CanvaAccessError("Canva OAuth-sessie verlopen. Start opnieuw met ‘Canva-account koppelen’.")
    verifier = str(row["code_verifier"] or "")
    redirect = str(row["redirect_uri"] or canva_redirect_uri())
    conn.execute("DELETE FROM canva_oauth_pending WHERE state = ?", (state,))
    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect,
        }
    )
    status = _store_tokens(conn, payload)
    log.info("Canva OAuth connected (scopes=%s, expires=%s)", status.get("scope"), status.get("expires_at"))
    return status


def disconnect_oauth(conn) -> dict[str, Any]:
    ensure_canva_tables(conn)
    conn.execute("DELETE FROM canva_oauth_secrets WHERE id = 1")
    conn.execute("DELETE FROM canva_oauth_pending")
    return connection_status(conn)


def connection_status(conn=None) -> dict[str, Any]:
    redirect = canva_redirect_uri()
    base = {
        "app_configured": canva_app_configured(),
        "app_type_nl": APP_TYPE_NL,
        "required_scopes": list(REQUIRED_SCOPES),
        "redirect_uri": redirect,
        "admin_steps_nl": ADMIN_STEPS_NL.format(redirect=redirect),
        "legacy_token_present": bool(legacy_access_token()),
        "connected": False,
        "token_present": False,
        "expires_at": "",
        "scope": "",
        "refresh_available": False,
    }
    if conn is None:
        return base
    ensure_canva_tables(conn)
    row = conn.execute(
        """
        SELECT access_token, refresh_token, expires_at, scope, connected_at, updated_at
        FROM canva_oauth_secrets WHERE id = 1
        """
    ).fetchone()
    if not row or not str(row["access_token"] or "").strip():
        if legacy_access_token():
            return {
                **base,
                "connected": True,
                "token_present": True,
                "scope": REQUEST_SCOPES,
                "source": "CANVA_ACCESS_TOKEN",
                "refresh_available": False,
            }
        return base
    return {
        **base,
        "connected": True,
        "token_present": True,
        "expires_at": str(row["expires_at"] or ""),
        "scope": str(row["scope"] or ""),
        "connected_at": str(row["connected_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
        "refresh_available": bool(str(row["refresh_token"] or "").strip()),
        "source": "oauth",
    }


def _parse_expires(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def refresh_access_token(conn, *, force: bool = False) -> str:
    """Return a valid access token, refreshing when expired. Refresh tokens are single-use."""
    ensure_canva_tables(conn)
    row = conn.execute(
        "SELECT access_token, refresh_token, expires_at FROM canva_oauth_secrets WHERE id = 1"
    ).fetchone()
    if not row:
        legacy = legacy_access_token()
        if legacy:
            return legacy
        raise CanvaAccessError(
            "Geen Canva-koppeling. Koppel eerst via OAuth of gebruik PDF-import. "
            + ADMIN_STEPS_NL.format(redirect=canva_redirect_uri())
        )
    access = str(row["access_token"] or "").strip()
    refresh = str(row["refresh_token"] or "").strip()
    expires = _parse_expires(str(row["expires_at"] or ""))
    still_valid = bool(access) and expires and expires > _now() + timedelta(seconds=30)
    if still_valid and not force:
        return access
    if not refresh:
        if access and not force:
            # Expired without refresh — surface clearly for tests/UI
            raise CanvaAccessError(
                "Canva access token is verlopen en er is geen refresh_token. "
                "Koppel Canva opnieuw via ‘Canva-account koppelen’."
            )
        legacy = legacy_access_token()
        if legacy:
            return legacy
        raise CanvaAccessError(
            "Canva-token verlopen zonder refresh. Koppel opnieuw of gebruik PDF-import."
        )
    try:
        payload = _token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "scope": REQUEST_SCOPES,
            }
        )
    except CanvaAccessError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CanvaAccessError(f"Canva tokenvernieuwing mislukt: {redact_secrets(str(exc))}") from exc
    _store_tokens(conn, payload)
    log.info("Canva access token refreshed (expires_in=%s)", payload.get("expires_in"))
    return str(payload["access_token"])


def get_valid_access_token(conn=None, *, access_token: str | None = None) -> str:
    if access_token and str(access_token).strip():
        return str(access_token).strip()
    if conn is not None:
        return refresh_access_token(conn)
    legacy = legacy_access_token()
    if legacy:
        return legacy
    raise CanvaAccessError(
        "Geen Canva-token. Koppel Canva via OAuth of zet tijdelijk CANVA_ACCESS_TOKEN. "
        "PDF-import blijft beschikbaar."
    )


def canva_connect_status(conn=None) -> dict[str, Any]:
    status = connection_status(conn)
    requirements = (
        status["admin_steps_nl"]
        if not status.get("app_configured")
        else (
            "Canva-app staat klaar. Koppel een Canva-gebruiker die het ontwerp mag openen "
            f"(scope {REQUEST_SCOPES}), of gebruik PDF-import."
            if not status.get("connected")
            else "Canva-koppeling actief."
        )
    )
    return {
        **status,
        "configured": bool(status.get("app_configured") and status.get("connected")),
        "token_present": bool(status.get("token_present")),
        "requirements_nl": requirements,
        "api_base": CANVA_API,
        "export_format": "pdf",
        "link_import_available": bool(status.get("connected") or legacy_access_token()),
    }


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _raise_canva_http(response: requests.Response, *, design_id: str) -> None:
    status = response.status_code
    try:
        payload = response.json()
    except Exception:
        payload = {}
    code = str(payload.get("code") or "")
    message = redact_secrets(str(payload.get("message") or response.text or "").strip())
    if status in {401, 403} or code in {"permission_denied", "unauthorized", "forbidden"}:
        raise CanvaAccessError(
            "Canva weigerde toegang tot dit ontwerp "
            f"(HTTP {status}{f', {code}' if code else ''}). "
            f"De gekoppelde Canva-gebruiker moet het ontwerp mogen openen "
            f"(scope {REQUEST_SCOPES}). Design-id: {design_id}. {message}".strip()
        )
    if status == 404 or code == "design_not_found":
        raise CanvaAccessError(
            f"Canva-ontwerp niet gevonden (HTTP {status}). Controleer de link/design-id {design_id}."
        )
    raise CanvaAccessError(
        f"Canva API-fout (HTTP {status}{f', {code}' if code else ''}): {message or 'onbekend'}"
    )


def create_pdf_export_job(design_id: str, *, token: str) -> dict[str, Any]:
    response = requests.post(
        f"{CANVA_API}/exports",
        headers=_auth_headers(token),
        json={"design_id": design_id, "format": {"type": "pdf"}},
        timeout=45,
    )
    if response.status_code >= 400:
        _raise_canva_http(response, design_id=design_id)
    return response.json()


def get_export_job(job_id: str, *, token: str) -> dict[str, Any]:
    response = requests.get(
        f"{CANVA_API}/exports/{job_id}",
        headers=_auth_headers(token),
        timeout=45,
    )
    if response.status_code >= 400:
        _raise_canva_http(response, design_id=job_id)
    return response.json()


def export_design_pdf_bytes(
    design_id: str,
    *,
    token: str,
    poll_seconds: float = 1.0,
    max_wait_seconds: float = 60.0,
) -> bytes:
    """Export a Canva design as PDF via Connect and return the file bytes."""
    created = create_pdf_export_job(design_id, token=token)
    job = created.get("job") if isinstance(created.get("job"), dict) else created
    job_id = str(job.get("id") or "").strip()
    if not job_id:
        raise CanvaAccessError("Canva gaf geen export-job-id terug.")

    deadline = time.monotonic() + max_wait_seconds
    status = str(job.get("status") or "in_progress")
    urls: list[str] = list(job.get("urls") or [])
    while status == "in_progress" and time.monotonic() < deadline:
        time.sleep(poll_seconds)
        polled = get_export_job(job_id, token=token)
        job = polled.get("job") if isinstance(polled.get("job"), dict) else polled
        status = str(job.get("status") or "")
        urls = list(job.get("urls") or [])

    if status != "success":
        error = job.get("error") if isinstance(job.get("error"), dict) else {}
        err_code = str(error.get("code") or "")
        err_msg = redact_secrets(str(error.get("message") or ""))
        raise CanvaAccessError(
            f"Canva-export mislukt (status={status or 'onbekend'}"
            f"{f', {err_code}' if err_code else ''}). {err_msg}".strip()
        )
    if not urls:
        raise CanvaAccessError("Canva-export slaagde zonder download-URL.")

    download = requests.get(urls[0], timeout=90)
    if download.status_code >= 400:
        raise CanvaAccessError(f"Canva-PDF download mislukt (HTTP {download.status_code}).")
    data = download.content or b""
    if not data:
        raise CanvaAccessError("Canva-PDF download was leeg.")
    return data


# Back-compat alias used by older call sites
def canva_access_token() -> str:
    return legacy_access_token()
