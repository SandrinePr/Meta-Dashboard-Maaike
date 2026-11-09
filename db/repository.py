"""Database upsert and search-index helpers."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

# Keep previously fetched Insights when a re-sync stores media without them
# (failed Insights call, rate limit, deleted object, etc.).
_INSIGHT_PRESERVE_KEYS = (
    "insights",
    "insights_views",
    "insights_saved",
    "insights_reach",
)
# Lean syncs (e.g. Business Discovery) must not wipe previously stored media/captions.
_MEDIA_PRESERVE_KEYS = (
    "media_url",
    "thumbnail_url",
    "full_picture",
    "attachments",
    "children",
    "caption",
    "message",
)
_UNAVAILABLE_PRESERVE_KEYS = (
    "rro_unavailable",
    "rro_unavailable_reason",
)


def merge_post_raw_json(
    existing_raw: str | None,
    new_raw: str | None,
    *,
    clear_unavailable: bool = False,
) -> str | None:
    """Merge new post JSON onto existing, preserving Insights/media when missing on new."""
    if not new_raw:
        return existing_raw
    if not existing_raw:
        return new_raw
    try:
        existing = json.loads(existing_raw)
        new = json.loads(new_raw)
    except json.JSONDecodeError:
        return new_raw
    if not isinstance(existing, dict) or not isinstance(new, dict):
        return new_raw
    merged = dict(new)
    for key in _INSIGHT_PRESERVE_KEYS:
        if merged.get(key) is None and existing.get(key) is not None:
            merged[key] = existing[key]
    for key in _MEDIA_PRESERVE_KEYS:
        if merged.get(key) in (None, "", {}) and existing.get(key) not in (None, "", {}):
            merged[key] = existing[key]
    if clear_unavailable:
        merged.pop("rro_unavailable", None)
        merged.pop("rro_unavailable_reason", None)
    else:
        for key in _UNAVAILABLE_PRESERVE_KEYS:
            if merged.get(key) is None and existing.get(key) is not None:
                merged[key] = existing[key]
    return json.dumps(merged, ensure_ascii=False)


def mark_post_unavailable(
    conn: sqlite3.Connection,
    post_id: int,
    *,
    reason: str | None = None,
) -> None:
    """Flag a post as removed/unavailable on the platform (stored in raw_json)."""
    row = conn.execute(
        "SELECT raw_json FROM posts WHERE id = ?",
        (post_id,),
    ).fetchone()
    if not row:
        return
    try:
        payload = json.loads(row["raw_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["rro_unavailable"] = True
    if reason:
        payload["rro_unavailable_reason"] = reason
    conn.execute(
        "UPDATE posts SET raw_json = ?, last_synced_at = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False), post_id),
    )


@dataclass(slots=True)
class UpsertResult:
    row_id: int
    created: bool


def upsert_account(
    conn: sqlite3.Connection,
    *,
    platform: str,
    external_id: str,
    name: str | None = None,
    username: str | None = None,
    page_id: str | None = None,
) -> int:
    """Insert or update an account and return its internal id."""
    existing = conn.execute(
        "SELECT id FROM accounts WHERE platform = ? AND external_id = ?",
        (platform, external_id),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE accounts
            SET name = COALESCE(?, name),
                username = COALESCE(?, username),
                page_id = COALESCE(?, page_id)
            WHERE id = ?
            """,
            (name, username, page_id, existing["id"]),
        )
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO accounts (platform, external_id, name, username, page_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (platform, external_id, name, username, page_id),
    )
    return int(cursor.lastrowid)


def upsert_post(
    conn: sqlite3.Connection,
    *,
    platform: str,
    external_id: str,
    account_id: int,
    content_type: str,
    text: str | None,
    permalink: str | None,
    media_url: str | None,
    thumbnail_url: str | None,
    media_type: str | None,
    published_at: str,
    raw_json: str | None,
    clear_unavailable: bool = False,
) -> UpsertResult:
    """Insert or update a post."""
    existing = conn.execute(
        "SELECT id, raw_json FROM posts WHERE platform = ? AND external_id = ?",
        (platform, external_id),
    ).fetchone()

    if existing:
        merged_raw = merge_post_raw_json(
            existing["raw_json"],
            raw_json,
            clear_unavailable=clear_unavailable,
        )
        conn.execute(
            """
            UPDATE posts
            SET account_id = ?,
                content_type = ?,
                text = ?,
                permalink = ?,
                media_url = COALESCE(?, media_url),
                thumbnail_url = COALESCE(?, thumbnail_url),
                media_type = ?,
                published_at = ?,
                raw_json = ?,
                last_synced_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                account_id,
                content_type,
                text,
                permalink,
                media_url,
                thumbnail_url,
                media_type,
                published_at,
                merged_raw,
                existing["id"],
            ),
        )
        return UpsertResult(row_id=int(existing["id"]), created=False)

    cursor = conn.execute(
        """
        INSERT INTO posts (
            platform, external_id, account_id, content_type, text, permalink,
            media_url, thumbnail_url, media_type, published_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            platform,
            external_id,
            account_id,
            content_type,
            text,
            permalink,
            media_url,
            thumbnail_url,
            media_type,
            published_at,
            raw_json,
        ),
    )
    return UpsertResult(row_id=int(cursor.lastrowid), created=True)


def upsert_comment(
    conn: sqlite3.Connection,
    *,
    platform: str,
    external_id: str,
    post_id: int,
    text: str,
    author_name: str | None,
    author_id: str | None,
    published_at: str,
    raw_json: str | None,
    parent_comment_id: int | None = None,
) -> UpsertResult:
    """Insert or update a comment. The same external id is never stored twice."""
    existing = conn.execute(
        "SELECT id FROM comments WHERE platform = ? AND external_id = ?",
        (platform, external_id),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE comments
            SET post_id = ?,
                parent_comment_id = COALESCE(?, parent_comment_id),
                text = ?,
                author_name = ?,
                author_id = ?,
                published_at = ?,
                raw_json = ?
            WHERE id = ?
            """,
            (
                post_id,
                parent_comment_id,
                text,
                author_name,
                author_id,
                published_at,
                raw_json,
                existing["id"],
            ),
        )
        return UpsertResult(row_id=int(existing["id"]), created=False)

    cursor = conn.execute(
        """
        INSERT INTO comments (
            platform, external_id, post_id, parent_comment_id,
            author_name, author_id, text, published_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            platform,
            external_id,
            post_id,
            parent_comment_id,
            author_name,
            author_id,
            text,
            published_at,
            raw_json,
        ),
    )
    return UpsertResult(row_id=int(cursor.lastrowid), created=True)


def sync_post_hashtags(conn: sqlite3.Connection, post_id: int, hashtags: list[str]) -> None:
    """Replace hashtag links for a post."""
    conn.execute("DELETE FROM post_hashtags WHERE post_id = ?", (post_id,))
    for tag in hashtags:
        conn.execute("INSERT OR IGNORE INTO hashtags (tag) VALUES (?)", (tag,))
        row = conn.execute("SELECT id FROM hashtags WHERE tag = ?", (tag,)).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO post_hashtags (post_id, hashtag_id) VALUES (?, ?)",
                (post_id, row["id"]),
            )


def upsert_search_index(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: int,
    platform: str,
    text: str | None,
    hashtags: list[str],
    published_at: str,
    permalink: str | None,
    thumbnail_url: str | None,
) -> None:
    """Replace one FTS index row for an entity."""
    conn.execute(
        "DELETE FROM search_index WHERE entity_type = ? AND entity_id = ?",
        (entity_type, str(entity_id)),
    )
    conn.execute(
        """
        INSERT INTO search_index (
            entity_type, entity_id, platform, text, hashtags,
            published_at, permalink, thumbnail_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            str(entity_id),
            platform,
            text or "",
            " ".join(hashtags),
            published_at,
            permalink,
            thumbnail_url,
        ),
    )


def get_post_hashtags(conn: sqlite3.Connection, post_id: int) -> list[str]:
    """Return hashtags linked to a post."""
    rows = conn.execute(
        """
        SELECT h.tag
        FROM hashtags h
        JOIN post_hashtags ph ON ph.hashtag_id = h.id
        WHERE ph.post_id = ?
        ORDER BY h.tag
        """,
        (post_id,),
    ).fetchall()
    return [row["tag"] for row in rows]


def get_post_by_platform_external_id(
    conn: sqlite3.Connection,
    *,
    platform: str,
    external_id: str,
) -> sqlite3.Row | None:
    """Fetch one post row by platform and external id."""
    return conn.execute(
        "SELECT * FROM posts WHERE platform = ? AND external_id = ?",
        (platform, external_id),
    ).fetchone()


def rebuild_search_index(conn: sqlite3.Connection) -> None:
    """Rebuild FTS rows from posts, comments, and linked hashtags."""
    posts = conn.execute(
        """
        SELECT id, platform, text, published_at, permalink, thumbnail_url
        FROM posts
        """
    ).fetchall()
    for post in posts:
        hashtags = get_post_hashtags(conn, int(post["id"]))
        upsert_search_index(
            conn,
            entity_type="post",
            entity_id=int(post["id"]),
            platform=post["platform"],
            text=post["text"],
            hashtags=hashtags,
            published_at=post["published_at"],
            permalink=post["permalink"],
            thumbnail_url=post["thumbnail_url"],
        )

    comments = conn.execute(
        """
        SELECT
            c.id,
            c.platform,
            c.text,
            c.published_at,
            c.post_id,
            p.permalink,
            p.thumbnail_url
        FROM comments c
        JOIN posts p ON p.id = c.post_id
        """
    ).fetchall()
    for comment in comments:
        hashtags = get_post_hashtags(conn, int(comment["post_id"]))
        upsert_search_index(
            conn,
            entity_type="comment",
            entity_id=int(comment["id"]),
            platform=comment["platform"],
            text=comment["text"],
            hashtags=hashtags,
            published_at=comment["published_at"],
            permalink=comment["permalink"],
            thumbnail_url=comment["thumbnail_url"],
        )


def list_own_account_ids(
    conn: sqlite3.Connection,
    *,
    platforms: set[str] | None = None,
) -> list[int]:
    """Return account IDs for own dashboard sync accounts (never competitors).

    Prefers configured Meta Instagram/page IDs when present in the DB; otherwise
    falls back to every non-competitor account for the requested platforms.
    """
    from config import get_settings

    settings = get_settings()
    platforms = set(platforms) if platforms else {"instagram", "facebook"}
    preferred: list[int] = []

    if "instagram" in platforms and settings.meta_instagram_business_account_id:
        row = conn.execute(
            """
            SELECT id FROM accounts
            WHERE platform = 'instagram' AND external_id = ?
              AND COALESCE(comparison_role, '') != 'competitor'
            """,
            (settings.meta_instagram_business_account_id,),
        ).fetchone()
        if row:
            preferred.append(int(row["id"]))

    if "facebook" in platforms and settings.meta_page_id:
        row = conn.execute(
            """
            SELECT id FROM accounts
            WHERE platform = 'facebook' AND external_id = ?
              AND COALESCE(comparison_role, '') != 'competitor'
            """,
            (settings.meta_page_id,),
        ).fetchone()
        if row:
            preferred.append(int(row["id"]))

    # Comparison preference own account (Instagram) when configured.
    if "instagram" in platforms:
        pref = conn.execute(
            "SELECT own_account_id FROM comparison_preferences WHERE id = 1"
        ).fetchone()
        if pref and pref["own_account_id"] is not None:
            own_id = int(pref["own_account_id"])
            role = conn.execute(
                "SELECT comparison_role FROM accounts WHERE id = ?",
                (own_id,),
            ).fetchone()
            if (
                role is not None
                and (role["comparison_role"] or "") != "competitor"
                and own_id not in preferred
            ):
                preferred.append(own_id)

    if preferred:
        return preferred

    sql = """
        SELECT id FROM accounts
        WHERE COALESCE(comparison_role, '') != 'competitor'
    """
    params: list[Any] = []
    if platforms:
        placeholders = ", ".join("?" for _ in platforms)
        sql += f" AND platform IN ({placeholders})"
        params.extend(sorted(platforms))
    sql += " ORDER BY id"
    return [int(row["id"]) for row in conn.execute(sql, params).fetchall()]


def count_records(conn: sqlite3.Connection) -> dict[str, int]:
    """Return sync summary counts for own accounts only (exclude competitors)."""
    own_ids = list_own_account_ids(conn)
    if not own_ids:
        return {
            "instagram_posts": 0,
            "instagram_comments": 0,
            "facebook_posts": 0,
            "facebook_comments": 0,
        }
    placeholders = ", ".join("?" for _ in own_ids)
    return {
        "instagram_posts": conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM posts
            WHERE platform = 'instagram' AND account_id IN ({placeholders})
            """,
            own_ids,
        ).fetchone()["c"],
        "instagram_comments": conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM comments c
            JOIN posts p ON p.id = c.post_id
            WHERE c.platform = 'instagram' AND p.account_id IN ({placeholders})
            """,
            own_ids,
        ).fetchone()["c"],
        "facebook_posts": conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM posts
            WHERE platform = 'facebook' AND account_id IN ({placeholders})
            """,
            own_ids,
        ).fetchone()["c"],
        "facebook_comments": conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM comments c
            JOIN posts p ON p.id = c.post_id
            WHERE c.platform = 'facebook' AND p.account_id IN ({placeholders})
            """,
            own_ids,
        ).fetchone()["c"],
    }
