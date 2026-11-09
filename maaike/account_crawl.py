"""Crawl one Instagram business account via Business Discovery into a Maaike client.

Uses the client's linked Meta page token + IG host id. Missing metrics stay None (not 0).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from maaike.activity_log import ensure_activity_table, record_activity
from maaike.meta_connect import MetaConnectError, MetaRateLimitError, graph_get, graph_version
from maaike.repository import (
    _now,
    apply_metric,
    connection_label,
    get_client,
    load_page_secret,
    upsert_synced_post,
)


def ensure_crawl_tables(conn) -> None:
    ensure_activity_table(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS client_crawl_accounts (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            username TEXT NOT NULL COLLATE NOCASE,
            ig_account_id TEXT,
            display_name TEXT,
            followers_count INTEGER,
            linked_at TEXT NOT NULL,
            last_crawled_at TEXT,
            last_crawl_status TEXT,
            last_crawl_detail TEXT,
            last_crawl_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(client_id, username COLLATE NOCASE),
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );
        """
    )


def normalize_username(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("@"):
        text = text[1:]
    text = text.split("?")[0].split("/")[-1].strip()
    return text.lower()


def list_crawl_accounts(conn, client_id: int) -> list[dict[str, Any]]:
    ensure_crawl_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM client_crawl_accounts
        WHERE client_id = ?
        ORDER BY linked_at DESC, id DESC
        """,
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def link_crawl_account(conn, client_id: int, username: str) -> dict[str, Any]:
    ensure_crawl_tables(conn)
    clean = normalize_username(username)
    if not clean or len(clean) < 2:
        raise ValueError("Enter a valid Instagram username.")
    now = _now()
    existing = conn.execute(
        "SELECT id FROM client_crawl_accounts WHERE client_id = ? AND username = ? COLLATE NOCASE",
        (client_id, clean),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO client_crawl_accounts (
                client_id, username, linked_at, last_crawl_status, last_crawl_detail
            ) VALUES (?, ?, ?, 'linked', 'Linked; not crawled yet.')
            """,
            (client_id, clean, now),
        )
    else:
        conn.execute(
            "UPDATE client_crawl_accounts SET linked_at = ? WHERE id = ?",
            (now, int(existing["id"])),
        )
    row = conn.execute(
        "SELECT * FROM client_crawl_accounts WHERE client_id = ? AND username = ? COLLATE NOCASE",
        (client_id, clean),
    ).fetchone()
    return dict(row)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _content_kind(item: dict[str, Any]) -> str:
    product = str(item.get("media_product_type") or "").upper()
    media = str(item.get("media_type") or "").upper()
    if product == "REELS" or media == "VIDEO":
        return "reel" if product == "REELS" else "video"
    if media == "CAROUSEL_ALBUM":
        return "carousel_album"
    if media == "IMAGE":
        return "image"
    return media.lower() or "post"


def crawl_account(
    conn,
    client_id: int,
    username: str,
    *,
    max_pages: int = 2,
    page_limit: int = 25,
) -> dict[str, Any]:
    """Fetch one account via Business Discovery and store posts for this client."""
    ensure_crawl_tables(conn)
    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("Client not found.")
    from maaike.repository import is_verified_link

    if not is_verified_link(client):
        raise ValueError("Connect Meta for this client first (host IG required for Business Discovery).")
    secret = load_page_secret(conn, client_id)
    if secret is None:
        raise ValueError("No page token stored. Connect Meta again.")
    _page_id, host_ig_id, page_token = secret
    if not host_ig_id:
        raise ValueError("No Instagram business account ID for this client.")

    clean = normalize_username(username)
    link_crawl_account(conn, client_id, clean)
    version = graph_version()
    root = f"https://graph.facebook.com/{version}"
    fetched_at = _now()
    posts_saved = 0
    metrics_saved = 0
    missing_metrics = 0
    pages = 0
    account_info: dict[str, Any] = {}
    sample_fields: list[str] = []
    errors: list[str] = []
    after: str | None = None
    oldest = None
    newest = None

    media_fields = (
        "id,caption,media_type,media_product_type,permalink,timestamp,"
        "like_count,comments_count,media_url,thumbnail_url"
    )

    while pages < max_pages:
        pages += 1
        media_q = f"media.limit({page_limit})"
        if after:
            media_q += f".after({after})"
        media_q += f"{{{media_fields}}}"
        account_part = "id,username,name,followers_count"
        fields = f"business_discovery.username({clean}){{{account_part},{media_q}}}"
        url = f"{root}/{host_ig_id}"
        try:
            payload = graph_get(
                url,
                {"fields": fields, "access_token": page_token},
                secrets=(page_token,),
            )
        except MetaRateLimitError as exc:
            errors.append(str(exc))
            break
        except MetaConnectError as exc:
            errors.append(str(exc))
            break

        discovery = payload.get("business_discovery")
        if not isinstance(discovery, dict):
            errors.append("business_discovery missing from API response (account not found or no access).")
            break

        account_info = {
            "id": discovery.get("id"),
            "username": discovery.get("username") or clean,
            "name": discovery.get("name"),
            "followers_count": _optional_int(discovery.get("followers_count")),
        }
        media_block = discovery.get("media") if isinstance(discovery.get("media"), dict) else {}
        items = media_block.get("data") if isinstance(media_block, dict) else []
        if not isinstance(items, list):
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            external_id = str(item.get("id") or "").strip()
            if not external_id:
                continue
            if not sample_fields:
                sample_fields = sorted(item.keys())
            published = str(item.get("timestamp") or "").strip() or fetched_at
            kind = _content_kind(item)
            media_urls = item.get("media_url") or item.get("thumbnail_url") or ""
            if item.get("thumbnail_url") and item.get("media_url") and item.get("thumbnail_url") != item.get("media_url"):
                media_urls = json.dumps(
                    [u for u in [item.get("thumbnail_url"), item.get("media_url")] if u],
                    ensure_ascii=False,
                )
            post_id = upsert_synced_post(
                conn,
                client_id,
                platform="instagram",
                external_id=external_id,
                published_at=published,
                content_kind=kind,
                permalink=item.get("permalink") or "",
                account_name=f"@{account_info.get('username') or clean}",
                caption=item.get("caption"),
                media_urls=str(media_urls) if media_urls else None,
                synced_at=fetched_at,
            )
            conn.execute(
                """
                UPDATE posts SET platform_label = ?, source_origin = ?
                WHERE id = ? AND client_id = ?
                """,
                ("Instagram", f"business_discovery:{clean}", post_id, client_id),
            )
            posts_saved += 1
            if oldest is None or published < oldest:
                oldest = published
            if newest is None or published > newest:
                newest = published

            likes = _optional_int(item.get("like_count"))
            comments = _optional_int(item.get("comments_count"))
            for metric_name, value in (("likes", likes), ("comments", comments)):
                if value is None:
                    missing_metrics += 1
                    continue
                apply_metric(
                    conn,
                    client_id,
                    post_id,
                    metric_name,
                    "ok",
                    value=value,
                    source_name="business_discovery",
                    measured_at=fetched_at,
                )
                # Also mirror onto posts columns when column exists
                conn.execute(
                    f"UPDATE posts SET {metric_name} = ? WHERE id = ? AND client_id = ?",
                    (value, post_id, client_id),
                )
                metrics_saved += 1
            # Explicit unknowns: views/reach/saves/shares/clicks not in BD payload
            for absent in ("views", "reach", "saves", "shares", "clicks"):
                missing_metrics += 1

        paging = (media_block or {}).get("paging") if isinstance(media_block, dict) else None
        cursors = paging.get("cursors") if isinstance(paging, dict) else None
        after = cursors.get("after") if isinstance(cursors, dict) else None
        if not after or not items:
            break

    status = "completed" if posts_saved and not errors else ("failed" if errors and not posts_saved else "completed_with_warnings")
    detail = (
        f"{posts_saved} posts saved via Business Discovery · "
        f"pages {pages} · known metrics {metrics_saved} · missing metric fields {missing_metrics}"
    )
    if errors:
        detail += " · " + "; ".join(errors[:3])

    summary = {
        "username": clean,
        "status": status,
        "fetched_at": fetched_at,
        "source": "meta_business_discovery",
        "host_ig_user_id": host_ig_id,
        "graph_version": version,
        "account": account_info,
        "pages_fetched": pages,
        "posts_saved": posts_saved,
        "metrics_saved": metrics_saved,
        "missing_metric_slots": missing_metrics,
        "fields_seen_on_post": sample_fields,
        "oldest_post_at": oldest,
        "newest_post_at": newest,
        "errors": errors,
        "note": (
            "Business Discovery provides like_count/comments_count; views/reach/saves/shares/clicks "
            "stay unknown (not stored as 0)."
        ),
    }

    conn.execute(
        """
        UPDATE client_crawl_accounts SET
            ig_account_id = ?, display_name = ?, followers_count = ?,
            last_crawled_at = ?, last_crawl_status = ?, last_crawl_detail = ?,
            last_crawl_json = ?
        WHERE client_id = ? AND username = ? COLLATE NOCASE
        """,
        (
            str(account_info.get("id") or "") or None,
            account_info.get("name"),
            account_info.get("followers_count"),
            fetched_at,
            status,
            detail,
            json.dumps(summary, ensure_ascii=False),
            client_id,
            clean,
        ),
    )
    record_activity(
        conn,
        client_id=client_id,
        activity_type="account_crawl",
        status=status,
        title=f"Account crawl @{clean}",
        details=detail,
        source_ref="business_discovery",
        is_error=status == "failed",
        occurred_at=fetched_at,
    )
    return summary
