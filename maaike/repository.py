"""Clients, legend items and posts stored only in Maaike's database."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

UNSET_LABEL = "—"
CONNECTED = "connected"
NOT_CONNECTED = "not_connected"
_TABLES = {
    "format": "content_formats",
    "pillar": "content_pillars",
    "hook": "content_hooks",
}
_FAILURE_STATUSES = frozenset({"not_connected", "expired", "revoked", "error"})


class LegendInputError(ValueError):
    """A legend name or explanation cannot be stored as given."""


class DuplicateLegendName(LegendInputError):
    """The name already exists for this client."""


class ClientInputError(ValueError):
    """A client name cannot be stored as given."""


class DuplicateClientName(ClientInputError):
    """Another client already uses this name."""


@dataclass(frozen=True, slots=True)
class Client:
    """Public client fields. Tokens are never selected into this object."""

    client_id: int
    name: str
    meta_status: str
    meta_status_detail: str | None
    meta_page_name: str | None
    meta_ig_username: str | None
    meta_connected_at: str | None
    meta_token_expires_at: str | None
    meta_last_checked_at: str | None
    last_fetch_status: str | None = None
    last_fetch_detail: str | None = None
    last_fetch_at: str | None = None
    last_fetch_from: str | None = None
    last_fetch_until: str | None = None
    last_fetch_instagram: int | None = None
    last_fetch_facebook: int | None = None


@dataclass(frozen=True, slots=True)
class LegendItem:
    item_id: int
    name: str
    explanation: str


@dataclass(frozen=True, slots=True)
class StoredPost:
    post_id: int
    platform: str
    published_at: str
    content_kind: str | None
    permalink: str | None
    views: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    saves: int | None
    clicks: int | None
    last_synced_at: str | None
    format_id: int | None
    format_name: str | None
    pillar_id: int | None
    pillar_name: str | None
    hook: str
    external_id: str = ""
    account_name: str | None = None
    caption: str | None = None
    media_urls: str | None = None
    reach: int | None = None
    previous_metrics: tuple[str, ...] = ()
    platform_label: str | None = None
    source_origin: str | None = None
    rating_text: str | None = None
    rating_source_label: str | None = None
    insight_text: str | None = None
    action_text: str | None = None
    format_code_raw: str | None = None
    content_soort_raw: str | None = None


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _table(kind: str) -> str:
    try:
        return _TABLES[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown legend type: {kind}") from exc


def _clean_name(name: str, *, empty_message: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise LegendInputError(empty_message)
    if cleaned == UNSET_LABEL:
        raise LegendInputError(
            "Choose a different name. The — character means ‘no selection’ in the post overview."
        )
    if len(cleaned) > 120:
        raise LegendInputError("The name may be at most 120 characters.")
    return cleaned


def _clean_explanation(explanation: str) -> str:
    cleaned = explanation.strip()
    if len(cleaned) > 5000:
        raise LegendInputError("The explanation may be at most 5000 characters.")
    return cleaned


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _previous_metrics(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part for part in str(value).split(",") if part)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def list_clients(conn: sqlite3.Connection) -> list[Client]:
    rows = conn.execute(
        """
        SELECT
            id, name, meta_status, meta_status_detail, meta_page_name,
            meta_ig_username, meta_connected_at, meta_token_expires_at,
            meta_last_checked_at, last_fetch_status, last_fetch_detail,
            last_fetch_at, last_fetch_from, last_fetch_until,
            last_fetch_instagram, last_fetch_facebook
        FROM clients
        ORDER BY name COLLATE NOCASE, id
        """
    ).fetchall()
    return [_client(row) for row in rows]


def get_client(conn: sqlite3.Connection, client_id: int) -> Client | None:
    row = conn.execute(
        """
        SELECT
            id, name, meta_status, meta_status_detail, meta_page_name,
            meta_ig_username, meta_connected_at, meta_token_expires_at,
            meta_last_checked_at, last_fetch_status, last_fetch_detail,
            last_fetch_at, last_fetch_from, last_fetch_until,
            last_fetch_instagram, last_fetch_facebook
        FROM clients
        WHERE id = ?
        """,
        (client_id,),
    ).fetchone()
    if row is None:
        return None
    return _client(row)


def add_client(conn: sqlite3.Connection, name: str) -> int:
    cleaned = _client_name(name)
    now = _now()
    try:
        cursor = conn.execute(
            """
            INSERT INTO clients (name, created_at, updated_at, meta_status)
            VALUES (?, ?, ?, 'not_connected')
            """,
            (cleaned, now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateClientName(f"Client '{cleaned}' already exists.") from exc
    return int(cursor.lastrowid)


def rename_client(conn: sqlite3.Connection, client_id: int, name: str) -> None:
    cleaned = _client_name(name)
    if get_client(conn, client_id) is None:
        raise ClientInputError("This client is no longer in the list.")
    try:
        conn.execute(
            "UPDATE clients SET name = ?, updated_at = ? WHERE id = ?",
            (cleaned, _now(), client_id),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateClientName(f"Client '{cleaned}' already exists.") from exc


def is_verified_link(client: Client) -> bool:
    """True only when Meta access was confirmed and stored for this client."""
    return bool(
        client.meta_status == CONNECTED
        and client.meta_connected_at
        and client.meta_page_name
    )


def connection_label(client: Client) -> str:
    """English UI label. Only a verified link may be described as Connected."""
    if is_verified_link(client):
        page = client.meta_page_name
        if client.meta_ig_username:
            return f"Connected to {page} (@{client.meta_ig_username})"
        return f"Connected to {page}"
    labels = {
        "expired": "Access expired",
        "revoked": "Access revoked",
        "error": "Connection failed",
    }
    return labels.get(client.meta_status, "Not connected")


def save_verified_link(
    conn: sqlite3.Connection,
    client_id: int,
    *,
    page_id: str,
    page_name: str,
    ig_user_id: str,
    ig_username: str | None,
    user_token: str,
    page_token: str,
    user_expires_at: str | None,
) -> None:
    """Store a link that has already been checked against Meta."""
    if get_client(conn, client_id) is None:
        raise ClientInputError("This client is no longer in the list.")
    page_id = page_id.strip()
    page_name = page_name.strip()
    ig_user_id = ig_user_id.strip()
    user_token = user_token.strip()
    page_token = page_token.strip()
    if not all((page_id, page_name, ig_user_id, user_token, page_token)):
        raise ClientInputError("The page or Instagram account was not fully verified.")
    now = _now()
    conn.execute(
        """
        UPDATE clients
        SET meta_status = 'connected',
            meta_status_detail = NULL,
            meta_page_id = ?,
            meta_page_name = ?,
            meta_ig_user_id = ?,
            meta_ig_username = ?,
            meta_connected_at = ?,
            meta_token_expires_at = ?,
            meta_last_checked_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            page_id,
            page_name,
            ig_user_id,
            (ig_username or "").strip() or None,
            now,
            user_expires_at,
            now,
            now,
            client_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO client_meta_secrets (
            client_id, user_access_token, page_access_token, updated_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            user_access_token = excluded.user_access_token,
            page_access_token = excluded.page_access_token,
            updated_at = excluded.updated_at
        """,
        (client_id, user_token, page_token, now),
    )


def load_page_secret(conn: sqlite3.Connection, client_id: int) -> tuple[str, str, str] | None:
    """Return the stored page id, Instagram id and page token for a server-side check."""
    row = conn.execute(
        """
        SELECT c.meta_page_id, c.meta_ig_user_id, s.page_access_token
        FROM clients c
        JOIN client_meta_secrets s ON s.client_id = c.id
        WHERE c.id = ?
        """,
        (client_id,),
    ).fetchone()
    if row is None:
        return None
    page_id = str(row["meta_page_id"] or "").strip()
    ig_user_id = str(row["meta_ig_user_id"] or "").strip()
    page_token = str(row["page_access_token"] or "").strip()
    if not page_id or not ig_user_id or not page_token:
        return None
    return page_id, ig_user_id, page_token


def mark_link_rechecked(
    conn: sqlite3.Connection,
    client_id: int,
    *,
    page_name: str,
    ig_username: str | None,
) -> None:
    """Refresh a link that was already verified. Never creates a new success."""
    now = _now()
    cursor = conn.execute(
        """
        UPDATE clients
        SET meta_page_name = ?,
            meta_ig_username = ?,
            meta_last_checked_at = ?,
            meta_status_detail = NULL,
            updated_at = ?
        WHERE id = ?
          AND meta_status = 'connected'
          AND meta_connected_at IS NOT NULL
        """,
        (page_name.strip(), (ig_username or "").strip() or None, now, now, client_id),
    )
    if cursor.rowcount != 1:
        raise ClientInputError("There is no verified connection.")


def disconnect_meta_link(conn: sqlite3.Connection, client_id: int) -> dict[str, str | None]:
    """Drop Meta tokens for this client only. Keep posts, strategy, legends and reports."""
    client = get_client(conn, client_id)
    if client is None:
        raise ClientInputError("This client is no longer in the list.")
    page_name = (client.meta_page_name or "").strip() or None
    ig_username = (client.meta_ig_username or "").strip() or None
    mark_link_failed(
        conn,
        client_id,
        status="not_connected",
        detail=(
            "Meta connection disconnected on purpose. "
            "Saved posts, strategy, legends and reports were kept."
        ),
    )
    return {"page_name": page_name, "ig_username": ig_username}


def mark_link_failed(
    conn: sqlite3.Connection,
    client_id: int,
    *,
    status: str,
    detail: str | None,
) -> None:
    """Record a failed attempt without keeping tokens or a success flag.

    Last known page/IG display names are kept so the UI can show which account
    lost access. IDs and tokens are cleared.
    """
    if status not in _FAILURE_STATUSES:
        raise ValueError("A failed connection must not be stored as connected.")
    client = get_client(conn, client_id)
    if client is None:
        raise ClientInputError("This client is no longer in the list.")
    now = _now()
    page_name = (client.meta_page_name or "").strip() or None
    ig_username = (client.meta_ig_username or "").strip() or None
    public = _public_detail(detail)
    if page_name or ig_username:
        account = page_name or ""
        if ig_username:
            account = f"{account} (@{ig_username})".strip() if account else f"@{ig_username}"
        if account and public and account not in public:
            public = f"{public} Last linked: {account}."
        elif account and not public:
            public = f"Last linked: {account}. Reconnect."
    conn.execute("DELETE FROM client_meta_secrets WHERE client_id = ?", (client_id,))
    conn.execute(
        """
        UPDATE clients
        SET meta_status = ?,
            meta_status_detail = ?,
            meta_page_id = NULL,
            meta_ig_user_id = NULL,
            meta_connected_at = NULL,
            meta_token_expires_at = NULL,
            meta_last_checked_at = ?,
            updated_at = ?,
            meta_page_name = COALESCE(meta_page_name, ?),
            meta_ig_username = COALESCE(meta_ig_username, ?)
        WHERE id = ?
        """,
        (status, public, now, now, page_name, ig_username, client_id),
    )


def list_items(conn: sqlite3.Connection, client_id: int, kind: str) -> list[LegendItem]:
    table = _table(kind)
    rows = conn.execute(
        f"""
        SELECT id, name, explanation
        FROM {table}
        WHERE client_id = ?
        ORDER BY name COLLATE NOCASE, id
        """,
        (client_id,),
    ).fetchall()
    return [
        LegendItem(item_id=int(row["id"]), name=str(row["name"]), explanation=str(row["explanation"] or ""))
        for row in rows
    ]


def list_formats(conn: sqlite3.Connection, client_id: int) -> list[LegendItem]:
    return list_items(conn, client_id, "format")


def list_pillars(conn: sqlite3.Connection, client_id: int) -> list[LegendItem]:
    return list_items(conn, client_id, "pillar")


def list_hooks(conn: sqlite3.Connection, client_id: int) -> list[LegendItem]:
    return list_items(conn, client_id, "hook")


def add_item(
    conn: sqlite3.Connection,
    client_id: int,
    kind: str,
    name: str,
    explanation: str,
) -> int:
    _require_client(conn, client_id)
    table = _table(kind)
    cleaned = _clean_name(name, empty_message="Enter a name.")
    note = _clean_explanation(explanation)
    if _name_taken(conn, table, client_id, cleaned, exclude_id=None):
        raise DuplicateLegendName(f"The name '{cleaned}' already exists for this client.")
    now = _now()
    try:
        cursor = conn.execute(
            f"""
            INSERT INTO {table} (client_id, name, explanation, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (client_id, cleaned, note, now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateLegendName(f"The name '{cleaned}' already exists for this client.") from exc
    return int(cursor.lastrowid)


def add_format(conn: sqlite3.Connection, client_id: int, name: str, explanation: str) -> int:
    return add_item(conn, client_id, "format", name, explanation)


def add_pillar(conn: sqlite3.Connection, client_id: int, name: str, explanation: str) -> int:
    return add_item(conn, client_id, "pillar", name, explanation)


def add_hook(conn: sqlite3.Connection, client_id: int, name: str, explanation: str) -> int:
    return add_item(conn, client_id, "hook", name, explanation)


def update_item(
    conn: sqlite3.Connection,
    client_id: int,
    kind: str,
    item_id: int,
    name: str,
    explanation: str,
) -> None:
    table = _table(kind)
    cleaned = _clean_name(name, empty_message="Enter a name.")
    note = _clean_explanation(explanation)
    _require_owned_item(conn, table, client_id, item_id)
    if _name_taken(conn, table, client_id, cleaned, exclude_id=item_id):
        raise DuplicateLegendName(f"The name '{cleaned}' already exists for this client.")
    try:
        conn.execute(
            f"""
            UPDATE {table}
            SET name = ?, explanation = ?, updated_at = ?
            WHERE id = ? AND client_id = ?
            """,
            (cleaned, note, _now(), item_id, client_id),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateLegendName(f"The name '{cleaned}' already exists for this client.") from exc


def update_format(
    conn: sqlite3.Connection,
    client_id: int,
    item_id: int,
    name: str,
    explanation: str,
) -> None:
    update_item(conn, client_id, "format", item_id, name, explanation)


def update_hook(
    conn: sqlite3.Connection,
    client_id: int,
    item_id: int,
    name: str,
    explanation: str,
) -> None:
    update_item(conn, client_id, "hook", item_id, name, explanation)


def update_pillar(
    conn: sqlite3.Connection,
    client_id: int,
    item_id: int,
    name: str,
    explanation: str,
) -> None:
    update_item(conn, client_id, "pillar", item_id, name, explanation)


def latest_sync_at(conn: sqlite3.Connection, client_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(last_synced_at) AS moment
        FROM posts
        WHERE client_id = ?
          AND last_synced_at IS NOT NULL
          AND TRIM(last_synced_at) != ''
        """,
        (client_id,),
    ).fetchone()
    if row is None or row["moment"] is None:
        return None
    text = str(row["moment"]).strip()
    return text or None


def list_posts(conn: sqlite3.Connection, client_id: int) -> list[StoredPost]:
    rows = conn.execute(
        """
        SELECT
            p.id AS post_id,
            p.external_id,
            p.platform,
            p.published_at,
            p.content_kind,
            p.permalink,
            p.views,
            p.likes,
            p.comments,
            p.shares,
            p.saves,
            p.clicks,
            p.reach,
            p.account_name,
            p.caption,
            p.media_urls,
            p.last_synced_at,
            (
                SELECT group_concat(m.metric_name, ',')
                FROM post_metrics m
                WHERE m.post_id = p.id AND m.availability = 'previous'
            ) AS previous_metrics,
            f.id AS format_id,
            f.name AS format_name,
            g.id AS pillar_id,
            g.name AS pillar_name,
            e.hook AS hook,
            p.platform_label AS platform_label,
            p.source_origin AS source_origin,
            e.format_code_raw AS format_code_raw,
            e.content_soort_raw AS content_soort_raw,
            (
                SELECT a.rating_text FROM post_assessments a
                WHERE a.post_id = p.id AND a.source = 'excel_imported'
                ORDER BY a.id DESC LIMIT 1
            ) AS rating_text,
            (
                SELECT a.source_label FROM post_assessments a
                WHERE a.post_id = p.id AND a.source = 'excel_imported'
                ORDER BY a.id DESC LIMIT 1
            ) AS rating_source_label,
            (
                SELECT a.insight_text FROM post_assessments a
                WHERE a.post_id = p.id AND a.source = 'excel_imported'
                ORDER BY a.id DESC LIMIT 1
            ) AS insight_text,
            (
                SELECT a.action_text FROM post_assessments a
                WHERE a.post_id = p.id AND a.source = 'excel_imported'
                ORDER BY a.id DESC LIMIT 1
            ) AS action_text
        FROM posts p
        LEFT JOIN post_editorial e ON e.post_id = p.id
        LEFT JOIN content_formats f
            ON f.id = e.format_id AND f.client_id = p.client_id
        LEFT JOIN content_pillars g
            ON g.id = e.pillar_id AND g.client_id = p.client_id
        WHERE p.client_id = ?
        ORDER BY p.published_at DESC, p.id DESC
        """,
        (client_id,),
    ).fetchall()
    return [_stored_post(row) for row in rows]


def save_editorial(
    conn: sqlite3.Connection,
    client_id: int,
    *,
    post_id: int,
    format_id: int | None,
    pillar_id: int | None,
    hook: str,
) -> None:
    post = conn.execute(
        "SELECT client_id FROM posts WHERE id = ?",
        (post_id,),
    ).fetchone()
    if post is None or int(post["client_id"]) != client_id:
        raise LegendInputError("This post does not belong to the selected client.")
    if format_id is not None and _not_owned(conn, "content_formats", client_id, format_id):
        raise LegendInputError("This content format does not belong to the selected client.")
    if pillar_id is not None and _not_owned(conn, "content_pillars", client_id, pillar_id):
        raise LegendInputError("This content pillar does not belong to the selected client.")
    now = _now()
    conn.execute(
        """
        INSERT INTO post_editorial (post_id, format_id, pillar_id, hook, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            format_id = excluded.format_id,
            pillar_id = excluded.pillar_id,
            hook = excluded.hook,
            updated_at = excluded.updated_at
        """,
        (post_id, format_id, pillar_id, hook.strip(), now),
    )


_METRIC_COLUMNS = {
    "views": "views",
    "likes": "likes",
    "comments": "comments",
    "shares": "shares",
    "saves": "saves",
    "clicks": "clicks",
    "reach": "reach",
}
_KEPT = frozenset({"measured", "previous"})


def upsert_synced_post(
    conn: sqlite3.Connection,
    client_id: int,
    *,
    platform: str,
    external_id: str,
    published_at: str,
    content_kind: str | None,
    permalink: str | None,
    account_name: str | None,
    caption: str | None,
    media_urls: str | None,
    synced_at: str,
) -> int:
    """Insert or update one Meta post. Editorial fields stay untouched."""
    if get_client(conn, client_id) is None:
        raise ClientInputError("This client is no longer in the list.")
    existing = conn.execute(
        """
        SELECT id FROM posts
        WHERE client_id = ? AND platform = ? AND external_id = ?
        """,
        (client_id, platform, external_id),
    ).fetchone()
    if existing is None:
        cursor = conn.execute(
            """
            INSERT INTO posts (
                client_id, platform, external_id, published_at, content_kind, permalink,
                account_name, caption, media_urls, last_synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                platform,
                external_id,
                published_at,
                content_kind,
                permalink,
                account_name,
                caption,
                media_urls,
                synced_at,
            ),
        )
        return int(cursor.lastrowid)
    post_id = int(existing["id"])
    conn.execute(
        """
        UPDATE posts
        SET published_at = ?, content_kind = ?, permalink = ?, account_name = ?,
            caption = ?, media_urls = ?, last_synced_at = ?
        WHERE id = ? AND client_id = ?
        """,
        (
            published_at,
            content_kind,
            permalink,
            account_name,
            caption,
            media_urls,
            synced_at,
            post_id,
            client_id,
        ),
    )
    return post_id


def apply_metric(
    conn: sqlite3.Connection,
    client_id: int,
    post_id: int,
    metric_name: str,
    outcome: str,
    *,
    value: int | None,
    source_name: str,
    measured_at: str,
) -> None:
    """Store a metric. A failed or empty follow-up keeps the last measured number."""
    if metric_name not in _METRIC_COLUMNS:
        raise LegendInputError("Unknown metric.")
    owner = conn.execute(
        "SELECT client_id FROM posts WHERE id = ?",
        (post_id,),
    ).fetchone()
    if owner is None or int(owner["client_id"]) != client_id:
        raise LegendInputError("This post does not belong to the selected client.")
    current = conn.execute(
        """
        SELECT value, availability, source_name, measured_at
        FROM post_metrics
        WHERE post_id = ? AND metric_name = ?
        """,
        (post_id, metric_name),
    ).fetchone()
    kept_value = current is not None and current["value"] is not None and current["availability"] in _KEPT
    if outcome == "measured":
        if value is None or isinstance(value, bool):
            raise LegendInputError("A measured value requires a number.")
        stored_value = int(value)
        availability = "measured"
        stored_source = source_name
        stored_at = measured_at
    elif kept_value and outcome in {"unavailable", "unsupported", "failed"}:
        stored_value = int(current["value"])
        availability = "previous"
        stored_source = str(current["source_name"] or source_name)
        stored_at = str(current["measured_at"] or measured_at)
    else:
        stored_value = None
        availability = outcome if outcome in {"unavailable", "unsupported", "failed"} else "unavailable"
        stored_source = source_name
        stored_at = measured_at
    conn.execute(
        """
        INSERT INTO post_metrics (post_id, metric_name, value, availability, source_name, measured_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id, metric_name) DO UPDATE SET
            value = excluded.value,
            availability = excluded.availability,
            source_name = excluded.source_name,
            measured_at = excluded.measured_at
        """,
        (post_id, metric_name, stored_value, availability, stored_source, stored_at),
    )
    column = _METRIC_COLUMNS[metric_name]
    conn.execute(
        f"UPDATE posts SET {column} = ? WHERE id = ? AND client_id = ?",
        (stored_value, post_id, client_id),
    )


def save_fetch_result(
    conn: sqlite3.Connection,
    client_id: int,
    *,
    status: str,
    detail: str,
    fetched_at: str,
    period_from: str | None,
    period_until: str | None,
    instagram_count: int,
    facebook_count: int,
) -> None:
    if get_client(conn, client_id) is None:
        raise ClientInputError("This client is no longer in the list.")
    conn.execute(
        """
        UPDATE clients
        SET last_fetch_status = ?, last_fetch_detail = ?, last_fetch_at = ?,
            last_fetch_from = ?, last_fetch_until = ?, last_fetch_instagram = ?,
            last_fetch_facebook = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            status,
            detail[:500],
            fetched_at,
            period_from,
            period_until,
            instagram_count,
            facebook_count,
            fetched_at,
            client_id,
        ),
    )


def _client_name(name: str) -> str:
    try:
        return _clean_name(name, empty_message="Enter a client name.")
    except LegendInputError as exc:
        raise ClientInputError(str(exc)) from exc


def _require_client(conn: sqlite3.Connection, client_id: int) -> None:
    if get_client(conn, client_id) is None:
        raise ClientInputError("This client is no longer in the list.")


def _require_owned_item(
    conn: sqlite3.Connection,
    table: str,
    client_id: int,
    item_id: int,
) -> None:
    row = conn.execute(
        f"SELECT client_id FROM {table} WHERE id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        raise LegendInputError("This item is no longer in the legend.")
    if int(row["client_id"]) != client_id:
        raise LegendInputError("This item belongs to another client.")


def _name_taken(
    conn: sqlite3.Connection,
    table: str,
    client_id: int,
    name: str,
    *,
    exclude_id: int | None,
) -> bool:
    if exclude_id is None:
        row = conn.execute(
            f"SELECT id FROM {table} WHERE client_id = ? AND name = ? COLLATE NOCASE",
            (client_id, name),
        ).fetchone()
    else:
        row = conn.execute(
            f"""
            SELECT id FROM {table}
            WHERE client_id = ? AND name = ? COLLATE NOCASE AND id != ?
            """,
            (client_id, name, exclude_id),
        ).fetchone()
    return row is not None


def _not_owned(conn: sqlite3.Connection, table: str, client_id: int, item_id: int) -> bool:
    if table not in _TABLES.values():
        raise ValueError(table)
    row = conn.execute(
        f"SELECT id FROM {table} WHERE id = ? AND client_id = ?",
        (item_id, client_id),
    ).fetchone()
    return row is None


def _public_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    text = " ".join(str(detail).split())
    return text[:400] or None


def _client(row: sqlite3.Row) -> Client:
    return Client(
        client_id=int(row["id"]),
        name=str(row["name"]),
        meta_status=str(row["meta_status"] or NOT_CONNECTED),
        meta_status_detail=_optional_text(row["meta_status_detail"]),
        meta_page_name=_optional_text(row["meta_page_name"]),
        meta_ig_username=_optional_text(row["meta_ig_username"]),
        meta_connected_at=_optional_text(row["meta_connected_at"]),
        meta_token_expires_at=_optional_text(row["meta_token_expires_at"]),
        meta_last_checked_at=_optional_text(row["meta_last_checked_at"]),
        last_fetch_status=_optional_text(row["last_fetch_status"]),
        last_fetch_detail=_optional_text(row["last_fetch_detail"]),
        last_fetch_at=_optional_text(row["last_fetch_at"]),
        last_fetch_from=_optional_text(row["last_fetch_from"]),
        last_fetch_until=_optional_text(row["last_fetch_until"]),
        last_fetch_instagram=_optional_int(row["last_fetch_instagram"]),
        last_fetch_facebook=_optional_int(row["last_fetch_facebook"]),
    )


def _stored_post(row: sqlite3.Row) -> StoredPost:
    return StoredPost(
        post_id=int(row["post_id"]),
        platform=str(row["platform"] or ""),
        published_at=str(row["published_at"] or ""),
        content_kind=_optional_text(row["content_kind"]),
        permalink=_optional_text(row["permalink"]),
        views=_optional_int(row["views"]),
        likes=_optional_int(row["likes"]),
        comments=_optional_int(row["comments"]),
        shares=_optional_int(row["shares"]),
        saves=_optional_int(row["saves"]),
        clicks=_optional_int(row["clicks"]),
        last_synced_at=_optional_text(row["last_synced_at"]),
        account_name=_optional_text(row["account_name"]),
        caption=_optional_text(row["caption"]),
        media_urls=_optional_text(row["media_urls"]),
        reach=_optional_int(row["reach"]),
        previous_metrics=_previous_metrics(row["previous_metrics"]),
        format_id=_optional_int(row["format_id"]),
        format_name=_optional_text(row["format_name"]),
        pillar_id=_optional_int(row["pillar_id"]),
        pillar_name=_optional_text(row["pillar_name"]),
        hook=str(row["hook"] or "").strip(),
        external_id=str(row["external_id"] or ""),
        platform_label=_optional_text(row["platform_label"]) if "platform_label" in row.keys() else None,
        source_origin=_optional_text(row["source_origin"]) if "source_origin" in row.keys() else None,
        rating_text=_optional_text(row["rating_text"]) if "rating_text" in row.keys() else None,
        rating_source_label=_optional_text(row["rating_source_label"])
        if "rating_source_label" in row.keys()
        else None,
        insight_text=_optional_text(row["insight_text"]) if "insight_text" in row.keys() else None,
        action_text=_optional_text(row["action_text"]) if "action_text" in row.keys() else None,
        format_code_raw=_optional_text(row["format_code_raw"]) if "format_code_raw" in row.keys() else None,
        content_soort_raw=_optional_text(row["content_soort_raw"]) if "content_soort_raw" in row.keys() else None,
    )
