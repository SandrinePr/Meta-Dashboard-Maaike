"""Canva Connect (official REST) helpers for reading design content.

HAMSTER only stores a Canva design URL per client today. Direct strategy import
requires a user OAuth access token with design:content:read so we can export the
design (PDF) and map text into empty strategy fields — same review flow as PDF/Figma.

No paid AI is used.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

CANVA_API = "https://api.canva.com/rest/v1"
DESIGN_ID_RE = re.compile(r"/design/([A-Za-z0-9_-]+)", re.IGNORECASE)

REQUIRED_SCOPES = ("design:content:read",)
OPTIONAL_SCOPES = ("design:meta:read",)

ACCESS_REQUIREMENTS_NL = (
    "Directe Canva-import vereist een Canva Connect-integratie met OAuth "
    "(authorization code) van een Canva-gebruiker die het ontwerp mag openen, "
    f"met scope {', '.join(REQUIRED_SCOPES)} "
    f"(optioneel ook {', '.join(OPTIONAL_SCOPES)}). "
    "Zet het user access token in CANVA_ACCESS_TOKEN op de server. "
    "Een losse Canva-URL zonder deze koppeling is niet genoeg; gebruik dan PDF-import."
)


class CanvaAccessError(ValueError):
    """Missing credentials or Canva refused access to the design."""


def extract_design_id(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("Plak een Canva-link.")
    match = DESIGN_ID_RE.search(cleaned)
    if not match:
        # Bare design id pasted by accident
        bare = cleaned.strip("/")
        if re.fullmatch(r"[A-Za-z0-9_-]{6,}", bare) and "://" not in bare:
            return bare
        raise ValueError("Geen Canva-design-id gevonden in de link.")
    return match.group(1)


def canva_access_token() -> str:
    load_dotenv(override=False)
    return (os.getenv("CANVA_ACCESS_TOKEN") or "").strip()


def canva_connect_status() -> dict[str, Any]:
    token = canva_access_token()
    return {
        "configured": bool(token),
        "token_present": bool(token),
        "required_scopes": list(REQUIRED_SCOPES),
        "optional_scopes": list(OPTIONAL_SCOPES),
        "requirements_nl": ACCESS_REQUIREMENTS_NL,
        "api_base": CANVA_API,
        "export_format": "pdf",
    }


def _auth_headers(token: str | None = None) -> dict[str, str]:
    access = (token or canva_access_token()).strip()
    if not access:
        raise CanvaAccessError(ACCESS_REQUIREMENTS_NL)
    return {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json",
    }


def _raise_canva_http(response: requests.Response, *, design_id: str) -> None:
    status = response.status_code
    try:
        payload = response.json()
    except Exception:
        payload = {}
    code = str(payload.get("code") or "")
    message = str(payload.get("message") or response.text or "").strip()
    if status in {401, 403} or code in {"permission_denied", "unauthorized", "forbidden"}:
        raise CanvaAccessError(
            "Canva weigerde toegang tot dit ontwerp "
            f"(HTTP {status}{f', {code}' if code else ''}). "
            "De Canva-gebruiker achter CANVA_ACCESS_TOKEN moet het ontwerp mogen openen "
            f"en scope {', '.join(REQUIRED_SCOPES)} hebben. "
            f"Design-id: {design_id}. "
            + (message or "")
        )
    if status == 404 or code == "design_not_found":
        raise CanvaAccessError(
            f"Canva-ontwerp niet gevonden (HTTP {status}). Controleer de link/design-id {design_id}."
        )
    raise CanvaAccessError(
        f"Canva API-fout (HTTP {status}{f', {code}' if code else ''}): {message or 'onbekend'}"
    )


def get_design_meta(design_id: str, *, token: str | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{CANVA_API}/designs/{design_id}",
        headers=_auth_headers(token),
        timeout=45,
    )
    if response.status_code >= 400:
        _raise_canva_http(response, design_id=design_id)
    return response.json()


def create_pdf_export_job(design_id: str, *, token: str | None = None) -> dict[str, Any]:
    response = requests.post(
        f"{CANVA_API}/exports",
        headers=_auth_headers(token),
        json={"design_id": design_id, "format": {"type": "pdf"}},
        timeout=45,
    )
    if response.status_code >= 400:
        _raise_canva_http(response, design_id=design_id)
    return response.json()


def get_export_job(job_id: str, *, token: str | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{CANVA_API}/exports/{job_id}",
        headers=_auth_headers(token),
        timeout=45,
    )
    if response.status_code >= 400:
        # design_id unknown here; keep generic
        _raise_canva_http(response, design_id=job_id)
    return response.json()


def export_design_pdf_bytes(
    design_id: str,
    *,
    token: str | None = None,
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
        err_msg = str(error.get("message") or "")
        raise CanvaAccessError(
            f"Canva-export mislukt (status={status or 'onbekend'}"
            f"{f', {err_code}' if err_code else ''}). {err_msg}".strip()
        )
    if not urls:
        raise CanvaAccessError("Canva-export slaagde zonder download-URL.")

    download = requests.get(urls[0], timeout=90)
    if download.status_code >= 400:
        raise CanvaAccessError(
            f"Canva-PDF download mislukt (HTTP {download.status_code})."
        )
    data = download.content or b""
    if not data:
        raise CanvaAccessError("Canva-PDF download was leeg.")
    return data


def is_canva_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in {"canva.com", "www.canva.com"} or host.endswith(".canva.com")
