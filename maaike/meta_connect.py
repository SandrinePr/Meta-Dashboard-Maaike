"""Meta login for one Maaike client. Tokens stay on the server.

Nothing in this module is called automatically. A screen calls it only after
the user chooses Koppelen met Meta. A client becomes connected only after
the selected Page and its Instagram account answer a check request.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from dotenv import load_dotenv

from maaike.repository import (
    Client,
    ClientInputError,
    get_client,
    load_page_secret,
    mark_link_failed,
    mark_link_rechecked,
    save_verified_link,
)

LOGIN_SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "read_insights",
    "instagram_basic",
    "instagram_manage_insights",
)
_RATE_LIMIT_CODES = frozenset({4, 17, 32, 613})
_PLACEHOLDERS = frozenset(
    {
        "",
        "your_meta_app_id",
        "your_app_secret_here",
        "your_meta_app_secret",
    }
)
_GRAPH_VERSION = re.compile(r"^v\d+\.\d+$")
_TOKEN_IN_TEXT = re.compile(
    r"(access_token|client_secret|fb_exchange_token|code)=([^&\s\"']+)",
    re.IGNORECASE,
)
_APP_TOKEN = re.compile(r"EAA[A-Za-z0-9]+")


class MetaConnectError(RuntimeError):
    """A Meta call failed. The message is safe to show."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class MetaRateLimitError(MetaConnectError):
    """Meta asked the sync to stop. Do not retry in a loop."""


@dataclass(frozen=True, slots=True)
class OAuthReadiness:
    ready: bool
    redirect_uri: str | None
    uses_configuration: bool
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PageOption:
    page_id: str
    page_name: str
    ig_user_id: str | None
    ig_username: str | None
    page_token: str

    @property
    def selectable(self) -> bool:
        return bool(self.ig_user_id and self.page_token and self.page_name)

    def __repr__(self) -> str:
        return f"PageOption(page_name={self.page_name!r}, selectable={self.selectable})"


@dataclass(frozen=True, slots=True)
class PendingLogin:
    user_token: str
    expires_at: str | None
    pages: tuple[PageOption, ...]

    def __repr__(self) -> str:
        return f"PendingLogin(pages={len(self.pages)})"


def redact(text: str, *secrets: str) -> str:
    """Remove tokens and app secrets from a message before it is stored or shown."""
    cleaned = str(text or "")
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[verborgen]")
    cleaned = _TOKEN_IN_TEXT.sub(r"\1=[verborgen]", cleaned)
    cleaned = _APP_TOKEN.sub("[verborgen]", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned[:400]


def normalize_redirect_uri(raw: str | None) -> str | None:
    """Keep scheme, host and path. Drop a query string so the code is not part of the callback."""
    if not raw:
        return None
    parts = urlsplit(raw.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    path = parts.path or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def readiness(redirect_uri: str | None) -> OAuthReadiness:
    """Say whether a login can be started. Does not call Meta."""
    load_dotenv(override=False)
    redirect = normalize_redirect_uri(redirect_uri)
    missing: list[str] = []
    if not _credential("MAAIKE_META_APP_ID"):
        missing.append(
            "Zet MAAIKE_META_APP_ID in het lokale .env-bestand. "
            "Gebruik een bestaande Red Rock-app, niet de TAOL-app."
        )
    if not _credential("MAAIKE_META_APP_SECRET"):
        missing.append(
            "Zet MAAIKE_META_APP_SECRET in het lokale .env-bestand. "
            "Plak het geheim nergens in het scherm en gebruik niet het TAOL-geheim."
        )
    if redirect is None:
        missing.append(
            "Zet MAAIKE_OAUTH_REDIRECT_URI op het exacte adres van dit dashboard, "
            "of open het dashboard zodat dat adres bekend is."
        )
    config_id = os.getenv("MAAIKE_META_LOGIN_CONFIG_ID", "").strip()
    return OAuthReadiness(
        ready=not missing,
        redirect_uri=redirect,
        uses_configuration=bool(config_id),
        missing=tuple(missing),
    )


def build_login_url(*, redirect_uri: str, state: str) -> str:
    """Build the Facebook dialog URL. The app secret is not a parameter."""
    ready = readiness(redirect_uri)
    if not ready.ready or ready.redirect_uri is None:
        raise MetaConnectError("Meta-login is nog niet ingesteld.")
    app_id = _credential("MAAIKE_META_APP_ID")
    if not app_id or not state.strip():
        raise MetaConnectError("Meta-login is nog niet ingesteld.")
    params = {
        "client_id": app_id,
        "redirect_uri": ready.redirect_uri,
        "state": state,
        "response_type": "code",
    }
    config_id = os.getenv("MAAIKE_META_LOGIN_CONFIG_ID", "").strip()
    if config_id:
        params["config_id"] = config_id
    else:
        params["scope"] = ",".join(LOGIN_SCOPES)
    return f"https://www.facebook.com/{_graph_version()}/dialog/oauth?{urlencode(params)}"


def collect_pages(*, code: str, redirect_uri: str) -> PendingLogin:
    """Exchange the callback code and list pages. Does not store anything."""
    ready = readiness(redirect_uri)
    if not ready.ready or ready.redirect_uri is None:
        raise MetaConnectError("Meta-login is nog niet ingesteld.")
    if not code.strip():
        raise MetaConnectError("Meta stuurde geen geldige login terug.")
    user_token, expires_at = _long_lived_user_token(code.strip(), ready.redirect_uri)
    pages = _page_options(user_token)
    return PendingLogin(user_token=user_token, expires_at=expires_at, pages=tuple(pages))


def confirm_selected_page(conn, client_id: int, pending: PendingLogin, option: PageOption) -> str:
    """Check the chosen Page with Meta, then store the link."""
    if not option.selectable or option.ig_user_id is None:
        raise MetaConnectError("Choose a Facebook page with a professional Instagram account.")
    payload = _get_json(
        f"https://graph.facebook.com/{_graph_version()}/{option.page_id}",
        {
            "fields": "id,name,instagram_business_account{id,username}",
            "access_token": option.page_token,
        },
        secrets=(option.page_token, pending.user_token),
    )
    checked = verified_choice(payload, option)
    if checked.ig_user_id is None:
        raise MetaConnectError("Het Instagram-account kon niet worden gecontroleerd.")
    try:
        save_verified_link(
            conn,
            client_id,
            page_id=checked.page_id,
            page_name=checked.page_name,
            ig_user_id=checked.ig_user_id,
            ig_username=checked.ig_username,
            user_token=pending.user_token,
            page_token=option.page_token,
            user_expires_at=pending.expires_at,
        )
    except ClientInputError as exc:
        raise MetaConnectError(str(exc)) from exc
    return checked.page_name


def record_failed_attempt(
    conn,
    client_id: int,
    exc: MetaConnectError,
    *,
    replace_verified: bool = False,
) -> None:
    """Store a failure without tokens. A verified link stays unless this check replaces it."""
    client = get_client(conn, client_id)
    if client is None:
        return
    if client.meta_status == "connected" and client.meta_connected_at and not replace_verified:
        return
    status = classify_access_failure(exc.code, str(exc))
    mark_link_failed(conn, client_id, status=status, detail=public_failure_detail(status, str(exc)))


def recheck_stored_link(conn, client_id: int) -> str:
    """Check a stored page token. The caller decides what a failure does to the status."""
    loaded = load_page_secret(conn, client_id)
    if loaded is None:
        raise MetaConnectError("Er is geen opgeslagen koppeling om te controleren.")
    page_id, ig_user_id, page_token = loaded
    option = PageOption(
        page_id=page_id,
        page_name="",
        ig_user_id=ig_user_id,
        ig_username=None,
        page_token=page_token,
    )
    payload = _get_json(
        f"https://graph.facebook.com/{_graph_version()}/{page_id}",
        {
            "fields": "id,name,instagram_business_account{id,username}",
            "access_token": page_token,
        },
        secrets=(page_token,),
    )
    checked = verified_choice(payload, option)
    mark_link_rechecked(
        conn,
        client_id,
        page_name=checked.page_name,
        ig_username=checked.ig_username,
    )
    return checked.page_name


def verified_choice(payload: object, expected: PageOption) -> PageOption:
    """Accept a Graph payload only when the Page and Instagram account match."""
    if not isinstance(payload, dict):
        raise MetaConnectError("The page could not be verified.")
    page_id = str(payload.get("id") or "").strip()
    page_name = str(payload.get("name") or "").strip() or expected.page_name.strip()
    if not page_name:
        raise MetaConnectError("The page could not be verified.")
    ig = payload.get("instagram_business_account")
    ig_id = ""
    ig_username = None
    if isinstance(ig, dict):
        ig_id = str(ig.get("id") or "").strip()
        ig_username = str(ig.get("username") or "").strip() or None
    if page_id != expected.page_id or not expected.ig_user_id or ig_id != expected.ig_user_id:
        raise MetaConnectError("The page or Instagram account did not match verification.")
    return PageOption(
        page_id=page_id,
        page_name=page_name,
        ig_user_id=ig_id,
        ig_username=ig_username or expected.ig_username,
        page_token=expected.page_token,
    )


def classify_access_failure(code: int | None, message: str) -> str:
    lowered = message.lower()
    if code == 190 and any(
        phrase in lowered
        for phrase in (
            "not authorized",
            "has not authorized",
            "logged out",
            "session is invalid",
            "invalidated",
            "removed",
        )
    ):
        return "revoked"
    if code == 190:
        return "expired"
    return "error"


def public_failure_detail(status: str, message: str) -> str:
    if status == "expired":
        return "De toegang is verlopen. Koppel opnieuw."
    if status == "revoked":
        return "De toegang is ingetrokken. Koppel opnieuw."
    cleaned = redact(message)
    if not cleaned or cleaned == "[verborgen]":
        return "Meta weigerde de koppeling."
    return cleaned


def pages_from_accounts(rows: object) -> list[PageOption]:
    """Turn a /me/accounts payload into choices. Rows without a page token are dropped."""
    if not isinstance(rows, list):
        return []
    options: list[PageOption] = []
    for row in rows:
        option = _page_option(row)
        if option is not None:
            options.append(option)
    return options


def _long_lived_user_token(code: str, redirect_uri: str) -> tuple[str, str | None]:
    app_id = _credential("MAAIKE_META_APP_ID")
    app_secret = _credential("MAAIKE_META_APP_SECRET")
    if not app_id or not app_secret:
        raise MetaConnectError("Meta-login is nog niet ingesteld.")
    short_payload = _get_json(
        f"https://graph.facebook.com/{_graph_version()}/oauth/access_token",
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "client_secret": app_secret,
            "code": code,
        },
        secrets=(app_secret, code),
    )
    short_token = str(short_payload.get("access_token") or "").strip()
    if not short_token:
        raise MetaConnectError("Meta gaf geen toegang terug.")
    long_payload = _get_json(
        f"https://graph.facebook.com/{_graph_version()}/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_token,
        },
        secrets=(app_secret, short_token),
    )
    long_token = str(long_payload.get("access_token") or "").strip()
    if not long_token:
        raise MetaConnectError("Meta gaf geen langere toegang terug.")
    return long_token, _expiry_from_payload(long_payload)


def _page_options(user_token: str) -> list[PageOption]:
    payload = _get_json(
        f"https://graph.facebook.com/{_graph_version()}/me/accounts",
        {
            "fields": "id,name,access_token,instagram_business_account{id,username}",
            "limit": "50",
            "access_token": user_token,
        },
        secrets=(user_token,),
    )
    rows = list(payload.get("data") or [])
    paging = payload.get("paging") if isinstance(payload.get("paging"), dict) else {}
    next_url = paging.get("next") if isinstance(paging, dict) else None
    for _ in range(3):
        if not isinstance(next_url, str) or not next_url.startswith("https://graph.facebook.com/"):
            break
        page = _get_json(next_url, None, secrets=(user_token,))
        rows.extend(page.get("data") or [])
        paging = page.get("paging") if isinstance(page.get("paging"), dict) else {}
        next_url = paging.get("next") if isinstance(paging, dict) else None
    return pages_from_accounts(rows)


def _page_option(row: object) -> PageOption | None:
    if not isinstance(row, dict):
        return None
    page_id = str(row.get("id") or "").strip()
    page_name = str(row.get("name") or "").strip()
    page_token = str(row.get("access_token") or "").strip()
    if not page_id or not page_name or not page_token:
        return None
    ig = row.get("instagram_business_account")
    ig_id = None
    ig_username = None
    if isinstance(ig, dict):
        ig_id = str(ig.get("id") or "").strip() or None
        ig_username = str(ig.get("username") or "").strip() or None
    return PageOption(
        page_id=page_id,
        page_name=page_name,
        ig_user_id=ig_id,
        ig_username=ig_username,
        page_token=page_token,
    )


def _expiry_from_payload(payload: dict) -> str | None:
    raw = payload.get("expires_in")
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    moment = datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)
    return moment.isoformat()


def graph_version() -> str:
    """Graph version for Maaike. This does not read the TAOL app or its tokens."""
    return _graph_version()


def graph_get(url: str, params: dict | None, *, secrets: tuple[str, ...]) -> dict:
    """One Graph request. A rate limit stops the caller; this function does not retry."""
    try:
        return _get_json(url, params, secrets=secrets)
    except MetaConnectError as exc:
        if exc.code in _RATE_LIMIT_CODES:
            raise MetaRateLimitError(
                "Meta beperkt het aantal verzoeken. Het ophalen is gestopt. "
                "Al opgeslagen posts blijven bewaard. Probeer het later opnieuw.",
                code=exc.code,
            ) from exc
        raise


def _get_json(url: str, params: dict | None, *, secrets: tuple[str, ...]) -> dict:
    try:
        response = requests.get(url, params=params, timeout=_timeout())
    except requests.RequestException:
        raise MetaConnectError("Meta was unreachable.") from None
    try:
        payload = response.json()
    except ValueError:
        raise MetaConnectError("Meta gaf geen leesbaar antwoord.") from None
    if not isinstance(payload, dict):
        raise MetaConnectError("Meta gaf geen leesbaar antwoord.")
    error = payload.get("error")
    if response.ok and not isinstance(error, dict):
        return payload
    code = None
    message = "Meta weigerde het verzoek."
    if isinstance(error, dict):
        raw_code = error.get("code")
        try:
            code = int(raw_code)
        except (TypeError, ValueError):
            code = None
        message = str(error.get("message") or message)
    raise MetaConnectError(redact(message, *secrets), code=code)


def _credential(name: str) -> str | None:
    load_dotenv(override=False)
    value = os.getenv(name, "").strip()
    if value in _PLACEHOLDERS:
        return None
    return value


def _graph_version() -> str:
    load_dotenv(override=False)
    value = os.getenv("MAAIKE_META_GRAPH_API_VERSION", "").strip() or "v25.0"
    if not _GRAPH_VERSION.fullmatch(value):
        return "v25.0"
    return value


def _timeout() -> float:
    raw = os.getenv("REQUEST_TIMEOUT_SECONDS", "").strip()
    try:
        value = float(raw)
    except ValueError:
        return 30.0
    if value <= 0 or value > 60:
        return 30.0
    return value


def safe_client_status(client: Client) -> str:
    """Re-export the display rule so screens do not invent their own success text."""
    from maaike.repository import connection_label

    return connection_label(client)
