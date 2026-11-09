"""Small content fetch. Does not change the lean scheduled discovery fields."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from db.comparison_repository import DEFAULT_OWN_USERNAME
from db.content_repository import replace_media_parts
from db.repository import upsert_comment
from meta.client import MetaClient, MetaRequestError
from meta.content_media import (
    DISCOVERY_CONTENT_FIELDS,
    as_content_fields,
    children_need_followup,
    parts_from_media_payload,
)
from meta.discovery import safe_error_text

logger = logging.getLogger(__name__)


def _part_log(parts) -> list[dict[str, Any]]:
    return [
        {
            "position": part.position,
            "role": part.role,
            "available": part.available,
            "reason": part.unavailable_reason,
        }
        for part in parts
    ]


def _store_payload(conn: sqlite3.Connection, post_id: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    caption = payload.get("caption")
    if isinstance(caption, str):
        conn.execute("UPDATE posts SET text = ? WHERE id = ?", (caption, post_id))
    media_url = payload.get("media_url") if isinstance(payload.get("media_url"), str) else None
    thumbnail = payload.get("thumbnail_url") if isinstance(payload.get("thumbnail_url"), str) else None
    conn.execute(
        """
        UPDATE posts
        SET media_url = COALESCE(?, media_url),
            thumbnail_url = COALESCE(?, thumbnail_url)
        WHERE id = ?
        """,
        (media_url, thumbnail, post_id),
    )
    parts = parts_from_media_payload(payload)
    replace_media_parts(conn, post_id, parts)
    return _part_log(parts)


def _own_samples(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT posts.id, posts.external_id, posts.media_type, posts.media_product_type
        FROM posts
        JOIN accounts ON accounts.id = posts.account_id
        WHERE accounts.username = ?
          AND accounts.platform = 'instagram'
          AND posts.platform = 'instagram'
        ORDER BY posts.published_at DESC
        LIMIT 80
        """,
        (DEFAULT_OWN_USERNAME,),
    ).fetchall()
    picked: dict[str, sqlite3.Row] = {}
    for row in rows:
        product = (row["media_product_type"] or "").upper()
        kind = (row["media_type"] or "").upper()
        if kind == "CAROUSEL_ALBUM" and "carousel" not in picked:
            picked["carousel"] = row
        elif product == "REELS" or kind == "VIDEO":
            if "reel" not in picked:
                picked["reel"] = row
        elif kind == "IMAGE" and "image" not in picked:
            picked["image"] = row
        if len(picked) == 3:
            break
    return list(picked.values())


def _fetch_own_payload(client: MetaClient, external_id: str) -> dict[str, Any]:
    payload = client.get_instagram_media_content(external_id)
    if children_need_followup(payload):
        children = client.get_instagram_media_children(external_id)
        payload = dict(payload)
        payload["children"] = {"data": children}
    return payload


def _store_replies(conn: sqlite3.Connection, client: MetaClient, post_ids: list[int]) -> dict[str, Any]:
    parent = None
    if post_ids:
        placeholders = ",".join("?" for _ in post_ids)
        parent = conn.execute(
            f"""
            SELECT id, external_id, post_id
            FROM comments
            WHERE post_id IN ({placeholders}) AND parent_comment_id IS NULL
            ORDER BY id
            LIMIT 1
            """,
            post_ids,
        ).fetchone()
    if parent is None:
        return {"status": "geen_reactie_bij_deze_posts", "stored": 0, "called": False}
    try:
        replies = client.get_instagram_comment_replies(str(parent["external_id"]), limit=25)
    except MetaRequestError as exc:
        return {
            "status": "niet_beschikbaar",
            "error_code": exc.error_code,
            "rate_limited": exc.is_rate_limited,
            "message": safe_error_text(exc),
            "stored": 0,
            "called": True,
        }
    stored = 0
    for reply in replies:
        external_id = reply.get("id")
        text = reply.get("text")
        published = reply.get("timestamp")
        if not isinstance(external_id, str) or not isinstance(text, str) or not isinstance(published, str):
            continue
        upsert_comment(
            conn,
            platform="instagram",
            external_id=external_id,
            post_id=int(parent["post_id"]),
            text=text,
            author_name=reply.get("username") if isinstance(reply.get("username"), str) else None,
            author_id=None,
            published_at=published,
            raw_json=json.dumps({"id": external_id, "parent": parent["external_id"]}, ensure_ascii=False),
            parent_comment_id=int(parent["id"]),
        )
        stored += 1
    return {"status": "opgehaald", "stored": stored, "rate_limited": False, "called": True}


def _competitor_sample(conn: sqlite3.Connection, client: MetaClient, host_id: str) -> dict[str, Any]:
    account = conn.execute(
        """
        SELECT id, username
        FROM accounts
        WHERE comparison_role = 'competitor' AND username IS NOT NULL
        ORDER BY id
        LIMIT 1
        """
    ).fetchone()
    if account is None or not host_id:
        return {"status": "overgeslagen", "reason": "Geen concurrent of geen eigen Instagram-id."}
    username = str(account["username"])
    inner = as_content_fields(DISCOVERY_CONTENT_FIELDS)
    fields = f"business_discovery.username({username}){{media.limit(3){{{inner}}}}}"
    try:
        payload = client.get_json(host_id, params={"fields": fields}, use_page_token=True)
    except MetaRequestError as exc:
        if exc.is_rate_limited:
            return {
                "status": "limiet",
                "error_code": exc.error_code,
                "rate_limited": True,
                "message": safe_error_text(exc),
            }
        plain = (
            "id,caption,media_type,media_product_type,media_url,thumbnail_url,"
            "permalink,timestamp,like_count,comments_count"
        )
        fields = f"business_discovery.username({username}){{media.limit(3){{{plain}}}}}"
        try:
            payload = client.get_json(host_id, params={"fields": fields}, use_page_token=True)
        except MetaRequestError as second:
            return {
                "status": "niet_beschikbaar",
                "error_code": second.error_code,
                "rate_limited": second.is_rate_limited,
                "message": safe_error_text(second),
            }
    discovery = payload.get("business_discovery") if isinstance(payload, dict) else None
    media = discovery.get("media") if isinstance(discovery, dict) else None
    data = media.get("data") if isinstance(media, dict) else None
    rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    logged = []
    for row in rows:
        external_id = row.get("id")
        stored_parts = None
        if isinstance(external_id, str):
            match = conn.execute(
                "SELECT id FROM posts WHERE platform = 'instagram' AND external_id = ?",
                (external_id,),
            ).fetchone()
            if match is not None:
                stored_parts = _store_payload(conn, int(match["id"]), row)
        logged.append(
            {
                "media_type": row.get("media_type"),
                "caption_present": isinstance(row.get("caption"), str) and bool(row.get("caption").strip()),
                "image_or_video_url": isinstance(row.get("media_url"), str),
                "thumbnail_url": isinstance(row.get("thumbnail_url"), str),
                "child_count": len((row.get("children") or {}).get("data") or [])
                if isinstance(row.get("children"), dict)
                else 0,
                "stored_for_known_post": stored_parts is not None,
                "parts": stored_parts,
            }
        )
    return {"status": "opgehaald", "username": username, "posts": logged, "rate_limited": False}


def run_content_sample(conn: sqlite3.Connection, client: MetaClient, *, host_id: str) -> dict[str, Any]:
    """Fetch one image, one carousel and one reel, plus one reply check and one competitor page."""
    report: dict[str, Any] = {"own": [], "replies": None, "competitor": None, "stopped": None}
    samples = _own_samples(conn)
    if not samples:
        report["stopped"] = "Geen eigen Instagram-posts in de database."
        return report
    for row in samples:
        try:
            payload = _fetch_own_payload(client, str(row["external_id"]))
        except MetaRequestError as exc:
            entry = {
                "media_type": row["media_type"],
                "product": row["media_product_type"],
                "status": "niet_beschikbaar",
                "error_code": exc.error_code,
                "rate_limited": exc.is_rate_limited,
                "message": safe_error_text(exc),
            }
            report["own"].append(entry)
            if exc.is_rate_limited:
                report["stopped"] = "Meta-aanvraaglimiet bereikt. Verdere inhoud is niet opgehaald."
                return report
            continue
        parts = _store_payload(conn, int(row["id"]), payload)
        report["own"].append(
            {
                "media_type": payload.get("media_type") or row["media_type"],
                "product": payload.get("media_product_type") or row["media_product_type"],
                "status": "opgehaald",
                "caption_present": isinstance(payload.get("caption"), str) and bool(str(payload.get("caption")).strip()),
                "parts": parts,
            }
        )
    replies = _store_replies(conn, client, [int(row["id"]) for row in samples])
    report["replies"] = replies
    if replies.get("rate_limited"):
        report["stopped"] = "Meta-aanvraaglimiet bereikt. Verdere inhoud is niet opgehaald."
        return report
    competitor = _competitor_sample(conn, client, host_id)
    report["competitor"] = competitor
    if competitor.get("rate_limited"):
        report["stopped"] = "Meta-aanvraaglimiet bereikt. Verdere inhoud is niet opgehaald."
    return report
