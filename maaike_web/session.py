"""Login state kept in this process. The cookie only carries a random id."""

from __future__ import annotations

import secrets
import threading
import time

from itsdangerous import BadSignature, URLSafeTimedSerializer

from maaike.meta_connect import PendingLogin

COOKIE_NAME = "maaike_session"
_LOCK = threading.Lock()
_STORE: dict[str, dict] = {}
_OAUTH_BY_STATE: dict[str, dict] = {}
_OAUTH_TTL_SECONDS = 600
_COOKIE_MAX_AGE = 8 * 60 * 60


def clear_store() -> None:
    with _LOCK:
        _STORE.clear()
        _OAUTH_BY_STATE.clear()


def signer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="maaike-web-session")


def read_session_id(cookie: str | None, secret: str) -> str | None:
    if not cookie:
        return None
    try:
        value = signer(secret).loads(cookie, max_age=_COOKIE_MAX_AGE)
    except BadSignature:
        return None
    if not isinstance(value, str) or not value:
        return None
    return value


def cookie_value(session_id: str, secret: str) -> str:
    return signer(secret).dumps(session_id)


def ensure_session(cookie: str | None, secret: str) -> tuple[str, str | None]:
    """Return the session id and a cookie value when the browser needs a new one."""
    current = read_session_id(cookie, secret)
    with _LOCK:
        if current and current in _STORE:
            return current, None
        session_id = current or secrets.token_urlsafe(32)
        _STORE.setdefault(session_id, {"created": time.time()})
    if current:
        return session_id, None
    return session_id, cookie_value(session_id, secret)


def arm_login(session_id: str, client_id: int, redirect_uri: str, *, popup: bool = False) -> str:
    state = secrets.token_urlsafe(32)
    expires = time.time() + _OAUTH_TTL_SECONDS
    with _LOCK:
        record = _STORE.setdefault(session_id, {"created": time.time()})
        record["oauth_state"] = state
        record["oauth_client_id"] = client_id
        record["oauth_redirect"] = redirect_uri
        record["oauth_expires"] = expires
        record["oauth_popup"] = bool(popup)
        record["state_used"] = False
        record["pending"] = None
        record["pending_client_id"] = None
        record["pending_expires"] = 0
        _OAUTH_BY_STATE[state] = {
            "session_id": session_id,
            "client_id": int(client_id),
            "redirect_uri": redirect_uri,
            "popup": bool(popup),
            "expires": expires,
            "used": False,
        }
    return state


def take_popup_flag(session_id: str | None) -> bool:
    """Read whether the current Meta attempt asked for a popup return."""
    with _LOCK:
        record = _STORE.get(session_id or "")
        if record is None:
            return False
        return bool(record.get("oauth_popup"))


def popup_for_state(state: str) -> bool:
    with _LOCK:
        entry = _OAUTH_BY_STATE.get(state or "")
        if entry is None:
            return False
        return bool(entry.get("popup"))


def take_callback(cookie_session_id: str | None, state: str) -> tuple[int, str, bool, str]:
    """Accept a callback once. State is required; cookie must match when present."""
    from maaike.meta_connect import MetaConnectError

    with _LOCK:
        entry = _OAUTH_BY_STATE.get(state or "")
        expired = entry is None or time.time() > float(entry.get("expires") or 0)
        if entry is None or entry.get("used") or expired or not state:
            raise MetaConnectError(
                "Deze Meta-login hoort niet bij deze sessie. Start het koppelen opnieuw."
            )
        armed_sid = str(entry["session_id"])
        # Cookie present for a different session → reject (keeps OAuth CSRF protection).
        # Cookie absent (common after Meta → callback) → bind back to the armed session.
        if cookie_session_id and cookie_session_id != armed_sid:
            raise MetaConnectError(
                "Deze Meta-login hoort niet bij deze sessie. Start het koppelen opnieuw."
            )
        entry["used"] = True
        record = _STORE.setdefault(armed_sid, {"created": time.time()})
        record["state_used"] = True
        record["oauth_state"] = None
        record["oauth_popup"] = False
        client_id = int(entry["client_id"])
        redirect_uri = str(entry["redirect_uri"])
        popup = bool(entry["popup"])
    return client_id, redirect_uri, popup, armed_sid


def store_pending(session_id: str, client_id: int, pending: PendingLogin) -> None:
    with _LOCK:
        record = _STORE.setdefault(session_id, {"created": time.time()})
        record["pending"] = pending
        record["pending_client_id"] = client_id
        record["pending_expires"] = time.time() + _OAUTH_TTL_SECONDS


def pending_for(session_id: str, client_id: int) -> PendingLogin | None:
    with _LOCK:
        record = _STORE.get(session_id)
        if record is None or record.get("pending_client_id") != client_id:
            return None
        if time.time() > float(record.get("pending_expires") or 0):
            record["pending"] = None
            record["pending_client_id"] = None
            return None
        pending = record.get("pending")
    return pending if isinstance(pending, PendingLogin) else None


def clear_pending(session_id: str) -> None:
    with _LOCK:
        record = _STORE.get(session_id)
        if record is None:
            return
        record["pending"] = None
        record["pending_client_id"] = None
        record["pending_expires"] = 0


def pages_public(pending: PendingLogin) -> dict:
    """Page names for the screen. Tokens stay in the pending object."""
    selectable = []
    blocked = []
    for page in pending.pages:
        if page.selectable:
            if page.ig_username:
                label = f"{page.page_name} (@{page.ig_username})"
            else:
                label = page.page_name
            selectable.append(
                {
                    "index": len(selectable),
                    "label": label,
                    "page_name": page.page_name,
                    "ig_username": page.ig_username,
                }
            )
        else:
            blocked.append(
                {
                    "page_name": page.page_name,
                    "reason": "Geen professioneel Instagram-account gekoppeld.",
                }
            )
    return {
        "selectable": selectable,
        "blocked": blocked,
        "empty": not pending.pages,
    }


def selectable_page(pending: PendingLogin, index: int):
    pages = [page for page in pending.pages if page.selectable]
    if index < 0 or index >= len(pages):
        return None
    return pages[index]
