"""Figma planning link for Social Beheer creatives — read-only import, manual post linking.

Never invents format/pillar/hook. Placeholders like "Hier in te vullen" and "n.v.t." are
not usable classifications. Existing manual editorial fields are never auto-overwritten.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests
from dotenv import load_dotenv

FILE_KEY_DEFAULT = "ew9PZ6d9NlRsL4ES8fMySO"
FILE_NAME = "RRO - Social Beheer - Uitwerking creatives"

UNUSABLE_VALUES = frozenset(
    {
        "",
        "hier in te vullen",
        "n.v.t.",
        "n.v.t",
        "nvt.",
        "nvt",
        "nvt --> ondertitelen",
        "nvt --&gt; ondertitelen",
    }
)

MONTH_NAMES_NL = {
    "januari": 1,
    "februari": 2,
    "maart": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "augustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}

SECTION_CODE_RE = re.compile(
    r"^(?P<kind>Post|Reel|Story)\s+(?P<code>[A-Z]\d+)(?:\.\d+)?$",
    re.IGNORECASE,
)


def week_letter_for_date(day: date, *, year: int, month: int) -> str | None:
    """Map a publish date to Figma week letter A/B/C… for a planning month.

    Week A starts on the Monday of the ISO week that contains the 1st of the month
    (may begin in the previous month). Example: 3 Nov 2026 → week B.
    """
    first = date(year, month, 1)
    week_a_start = first - timedelta(days=first.weekday())
    if day < week_a_start:
        return None
    # Allow a few days into the next month for late slots.
    if day.year == year and day.month > month + 1:
        return None
    if day.year > year and not (month == 12 and day.month == 1):
        return None
    index = (day - week_a_start).days // 7
    if index < 0 or index > 25:
        return None
    return chr(ord("A") + index)


def week_letter_from_code(code: str | None) -> str | None:
    text = str(code or "").strip().upper()
    if len(text) >= 1 and text[0].isalpha():
        return text[0]
    return None


def _parse_publish_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def ensure_figma_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS client_figma_files (
            client_id INTEGER PRIMARY KEY,
            file_key TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            last_synced_at TEXT,
            last_sync_note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );

        CREATE TABLE IF NOT EXISTS figma_planning_items (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            node_id TEXT NOT NULL,
            source_url TEXT NOT NULL DEFAULT '',
            page_name TEXT NOT NULL DEFAULT '',
            page_node_id TEXT NOT NULL DEFAULT '',
            period_year INTEGER,
            period_month INTEGER,
            code TEXT NOT NULL DEFAULT '',
            content_kind TEXT NOT NULL DEFAULT '',
            platform_hint TEXT NOT NULL DEFAULT '',
            format_raw TEXT NOT NULL DEFAULT '',
            format_usable INTEGER NOT NULL DEFAULT 0,
            pillar_raw TEXT NOT NULL DEFAULT '',
            pillar_usable INTEGER NOT NULL DEFAULT 0,
            hook_raw TEXT NOT NULL DEFAULT '',
            hook_usable INTEGER NOT NULL DEFAULT 0,
            brief_excerpt TEXT NOT NULL DEFAULT '',
            linked_post_id INTEGER,
            link_status TEXT NOT NULL DEFAULT 'unlinked',
            raw_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            UNIQUE(client_id, node_id),
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(linked_post_id) REFERENCES posts(id)
        );

        CREATE INDEX IF NOT EXISTS idx_figma_items_client
            ON figma_planning_items(client_id, period_year, period_month, code);
        """
    )


def figma_source_url(file_key: str, node_id: str = "") -> str:
    base = f"https://www.figma.com/design/{file_key}/{quote(FILE_NAME.replace(' ', '-'))}"
    if node_id:
        return f"{base}?node-id={node_id.replace(':', '-')}"
    return base


def normalize_node_id(value: str) -> str:
    text = str(value or "").strip()
    if "-" in text and ":" not in text:
        return text.replace("-", ":", 1)
    return text


def is_usable_classification(value: str | None) -> bool:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return False
    lower = text.lower()
    if lower in UNUSABLE_VALUES:
        return False
    if lower.startswith("hier in te vullen"):
        return False
    if lower in {"nvt", "nvt.", "n.v.t", "n.v.t."}:
        return False
    if lower.startswith("nvt"):
        # "nvt --> ondertitelen" etc.
        rest = lower[3:].lstrip(". ").lstrip("-–>—> ").strip()
        if not rest or "ondertitel" in rest:
            return False
    return True


def _clean_field(value: str) -> str:
    text = (
        str(value or "")
        .replace("\xa0", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return " ".join(text.split()).strip()


def parse_brief_fields(brief_text: str) -> dict[str, Any]:
    """Parse INSTA/LINKEDIN brief text for format, pillar, platform, content kind."""
    text = str(brief_text or "")
    platform_hint = ""
    content_kind = ""
    header = text.split("Content format:", 1)[0].strip()
    if header:
        upper = header.upper()
        if "INSTA" in upper or "INSTAGRAM" in upper:
            platform_hint = "instagram"
        elif "LINKEDIN" in upper:
            platform_hint = "linkedin"
        elif "FACEBOOK" in upper:
            platform_hint = "facebook"
        if "REEL" in upper:
            content_kind = "reel"
        elif "STORY" in upper:
            content_kind = "story"
        elif "POST" in upper or "CARROUSEL" in upper or "CAROUSEL" in upper:
            content_kind = "post"

    format_raw = ""
    pillar_raw = ""
    m_fmt = re.search(
        r"Content format:\s*(.*?)\s*Contentpijler:",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m_fmt:
        format_raw = _clean_field(m_fmt.group(1))
    m_pil = re.search(
        r"Contentpijler:\s*(.*?)\s*Wat moet de gebruiker",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m_pil:
        pillar_raw = _clean_field(m_pil.group(1))
    elif "Contentpijler:" in text:
        after = text.split("Contentpijler:", 1)[1]
        pillar_raw = _clean_field(after.split("Wat moet", 1)[0])

    return {
        "platform_hint": platform_hint,
        "content_kind": content_kind,
        "format_raw": format_raw,
        "format_usable": is_usable_classification(format_raw),
        "pillar_raw": pillar_raw,
        "pillar_usable": is_usable_classification(pillar_raw),
        "brief_excerpt": _clean_field(text)[:1200],
    }


def parse_hook_field(hook_text: str) -> dict[str, Any]:
    text = str(hook_text or "")
    if "Hook / tekst in post:" in text:
        text = text.split("Hook / tekst in post:", 1)[1]
    elif text.lower().startswith("hook / tekst in post:"):
        text = text.split(":", 1)[1]
    hook_raw = _clean_field(text)
    return {"hook_raw": hook_raw, "hook_usable": is_usable_classification(hook_raw)}


def parse_section_name(name: str) -> dict[str, str]:
    match = SECTION_CODE_RE.match(str(name or "").strip())
    if not match:
        return {"code": "", "content_kind_from_name": ""}
    kind = match.group("kind").lower()
    code = match.group("code").upper()
    return {"code": code, "content_kind_from_name": kind}


def period_from_page_name(page_name: str, default_year: int = 2026) -> tuple[int | None, int | None]:
    name = str(page_name or "").strip().lower()
    month = MONTH_NAMES_NL.get(name)
    if month is None:
        return None, None
    return default_year, month


def get_figma_connection(conn, client_id: int) -> dict[str, Any]:
    ensure_figma_tables(conn)
    row = conn.execute(
        "SELECT * FROM client_figma_files WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if row is None:
        return {
            "client_id": client_id,
            "file_key": "",
            "file_name": "",
            "source_url": "",
            "last_synced_at": None,
            "last_sync_note": "",
            "linked": False,
        }
    return {
        "client_id": client_id,
        "file_key": row["file_key"],
        "file_name": row["file_name"],
        "source_url": row["source_url"],
        "last_synced_at": row["last_synced_at"],
        "last_sync_note": row["last_sync_note"] or "",
        "linked": bool(row["file_key"]),
    }


def save_figma_connection(
    conn,
    client_id: int,
    *,
    file_key: str,
    file_name: str = FILE_NAME,
    source_url: str = "",
    sync_note: str = "",
) -> dict[str, Any]:
    ensure_figma_tables(conn)
    key = str(file_key or "").strip()
    if not key:
        raise ValueError("Figma file key is required.")
    # Guard against the previously mistyped key (capital I vs lowercase L).
    if key == "ew9PZ6d9NIRsL4ES8fMySO":
        raise ValueError(
            "This file key looks mistyped (NIRs). Use ew9PZ6d9NlRsL4ES8fMySO (NlRs)."
        )
    url = source_url.strip() or figma_source_url(key)
    now = _now()
    conn.execute(
        """
        INSERT INTO client_figma_files (
            client_id, file_key, file_name, source_url, last_synced_at, last_sync_note, updated_at
        ) VALUES (?, ?, ?, ?, NULL, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            file_key = excluded.file_key,
            file_name = excluded.file_name,
            source_url = excluded.source_url,
            last_sync_note = excluded.last_sync_note,
            updated_at = excluded.updated_at
        """,
        (client_id, key, file_name or FILE_NAME, url, sync_note, now),
    )
    return get_figma_connection(conn, client_id)


def _item_out(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "node_id": row["node_id"],
        "source_url": row["source_url"],
        "page_name": row["page_name"],
        "page_node_id": row["page_node_id"],
        "period_year": row["period_year"],
        "period_month": row["period_month"],
        "code": row["code"],
        "content_kind": row["content_kind"],
        "platform_hint": row["platform_hint"],
        "format_raw": row["format_raw"],
        "format_usable": bool(row["format_usable"]),
        "pillar_raw": row["pillar_raw"],
        "pillar_usable": bool(row["pillar_usable"]),
        "hook_raw": row["hook_raw"],
        "hook_usable": bool(row["hook_usable"]),
        "brief_excerpt": row["brief_excerpt"],
        "linked_post_id": row["linked_post_id"],
        "link_status": row["link_status"],
    }


def list_planning_items(conn, client_id: int) -> list[dict[str, Any]]:
    ensure_figma_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM figma_planning_items
        WHERE client_id = ?
        ORDER BY id
        """,
        (client_id,),
    ).fetchall()
    items = [_item_out(r) for r in rows]
    items.sort(
        key=lambda i: (
            -(i["period_year"] or 0),
            -(i["period_month"] or 0),
            i["code"] or "",
            i["id"],
        )
    )
    return items


def upsert_planning_items(conn, client_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Upsert by (client_id, node_id). Re-import does not create duplicates."""
    ensure_figma_tables(conn)
    now = _now()
    inserted = 0
    updated = 0
    for raw in items:
        node_id = normalize_node_id(str(raw.get("node_id") or ""))
        if not node_id:
            continue
        existing = conn.execute(
            "SELECT id, linked_post_id, link_status FROM figma_planning_items WHERE client_id = ? AND node_id = ?",
            (client_id, node_id),
        ).fetchone()
        payload = (
            client_id,
            node_id,
            str(raw.get("source_url") or ""),
            str(raw.get("page_name") or ""),
            str(raw.get("page_node_id") or ""),
            raw.get("period_year"),
            raw.get("period_month"),
            str(raw.get("code") or ""),
            str(raw.get("content_kind") or ""),
            str(raw.get("platform_hint") or ""),
            str(raw.get("format_raw") or ""),
            1 if raw.get("format_usable") else 0,
            str(raw.get("pillar_raw") or ""),
            1 if raw.get("pillar_usable") else 0,
            str(raw.get("hook_raw") or ""),
            1 if raw.get("hook_usable") else 0,
            str(raw.get("brief_excerpt") or "")[:2000],
            json.dumps(raw.get("raw") or {}, ensure_ascii=False)[:20000],
            now,
        )
        if existing is None:
            conn.execute(
                """
                INSERT INTO figma_planning_items (
                    client_id, node_id, source_url, page_name, page_node_id,
                    period_year, period_month, code, content_kind, platform_hint,
                    format_raw, format_usable, pillar_raw, pillar_usable,
                    hook_raw, hook_usable, brief_excerpt, linked_post_id, link_status,
                    raw_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'unlinked', ?, ?)
                """,
                payload,
            )
            inserted += 1
        else:
            conn.execute(
                """
                UPDATE figma_planning_items SET
                    source_url = ?, page_name = ?, page_node_id = ?,
                    period_year = ?, period_month = ?, code = ?, content_kind = ?,
                    platform_hint = ?, format_raw = ?, format_usable = ?,
                    pillar_raw = ?, pillar_usable = ?, hook_raw = ?, hook_usable = ?,
                    brief_excerpt = ?, raw_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload[2],
                    payload[3],
                    payload[4],
                    payload[5],
                    payload[6],
                    payload[7],
                    payload[8],
                    payload[9],
                    payload[10],
                    payload[11],
                    payload[12],
                    payload[13],
                    payload[14],
                    payload[15],
                    payload[16],
                    payload[17],
                    now,
                    existing["id"],
                ),
            )
            updated += 1
    return {"inserted": inserted, "updated": updated, "total": inserted + updated}


def parse_items_from_metadata_xml(
    xml_text: str,
    *,
    file_key: str,
    page_name: str,
    page_node_id: str,
    default_year: int = 2026,
) -> list[dict[str, Any]]:
    """Parse MCP get_metadata XML for planning sections (Post/Reel/Story + code)."""
    year, month = period_from_page_name(page_name, default_year=default_year)
    items: list[dict[str, Any]] = []
    # Split on section tags with Post/Reel/Story names
    section_re = re.compile(
        r'<section id="(?P<id>[^"]+)" name="(?P<name>(?:Post|Reel|Story)[^"]*)"[^>]*>(?P<body>.*?)</section>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in section_re.finditer(xml_text):
        section_name = match.group("name").strip()
        # Skip templates
        if section_name.lower().startswith("template"):
            continue
        parsed_name = parse_section_name(section_name)
        if not parsed_name["code"]:
            # Allow "Post - Something" without week code — keep name as code label empty
            if not re.match(r"^(Post|Reel|Story)\b", section_name, re.I):
                continue
        node_id = normalize_node_id(match.group("id"))
        body = match.group("body")
        brief = ""
        hook = ""
        for tm in re.finditer(r'<text id="[^"]+" name="(?P<name>[^"]*)"', body):
            name = tm.group("name")
            if "Content format:" in name or "Contentpijler:" in name:
                # Prefer filled briefs over template leftovers; last filled wins later
                if "Hier in te vullen" in name and brief and "Hier in te vullen" not in brief:
                    continue
                brief = name
            if name.startswith("Hook / tekst in post:"):
                # Prefer first slide hook when multiple; keep first usable, else first
                if not hook:
                    hook = name
                elif not is_usable_classification(parse_hook_field(hook)["hook_raw"]):
                    if is_usable_classification(parse_hook_field(name)["hook_raw"]):
                        hook = name
        brief_fields = parse_brief_fields(brief)
        hook_fields = parse_hook_field(hook)
        content_kind = brief_fields["content_kind"] or parsed_name["content_kind_from_name"]
        items.append(
            {
                "node_id": node_id,
                "source_url": figma_source_url(file_key, node_id),
                "page_name": page_name,
                "page_node_id": page_node_id,
                "period_year": year,
                "period_month": month,
                "code": parsed_name["code"] or section_name,
                "content_kind": content_kind,
                "platform_hint": brief_fields["platform_hint"],
                "format_raw": brief_fields["format_raw"],
                "format_usable": brief_fields["format_usable"],
                "pillar_raw": brief_fields["pillar_raw"],
                "pillar_usable": brief_fields["pillar_usable"],
                "hook_raw": hook_fields["hook_raw"],
                "hook_usable": hook_fields["hook_usable"],
                "brief_excerpt": brief_fields["brief_excerpt"],
                "raw": {"section_name": section_name},
            }
        )
    return items


def resolve_figma_token() -> dict[str, Any]:
    load_dotenv(override=False)
    token = (
        os.getenv("FIGMA_ACCESS_TOKEN", "").strip()
        or os.getenv("FIGMA_TOKEN", "").strip()
        or os.getenv("FIGMA_API_TOKEN", "").strip()
    )
    return {
        "configured": bool(token),
        "token": token,
        "missing_setting": None if token else "FIGMA_ACCESS_TOKEN in .env (server-side)",
    }


def fetch_figma_file(file_key: str) -> dict[str, Any]:
    resolved = resolve_figma_token()
    if not resolved["configured"]:
        raise ValueError(resolved["missing_setting"])
    url = f"https://api.figma.com/v1/files/{file_key}"
    response = requests.get(
        url,
        headers={"X-Figma-Token": resolved["token"]},
        timeout=120,
    )
    if response.status_code == 403:
        raise ValueError("Figma API refused access (403). Check token and file share permissions.")
    if response.status_code == 404:
        raise ValueError("Figma file not found (404). Check the file key.")
    if response.status_code != 200:
        raise ValueError(f"Figma API error HTTP {response.status_code}.")
    return response.json()


def _walk_sections(node: dict[str, Any], page_name: str, page_id: str, file_key: str, year: int | None, month: int | None, out: list[dict[str, Any]]) -> None:
    name = str(node.get("name") or "")
    ntype = str(node.get("type") or "")
    node_id = normalize_node_id(str(node.get("id") or ""))
    if ntype == "SECTION" and SECTION_CODE_RE.match(name.strip()):
        texts: list[str] = []

        def collect(n: dict[str, Any]) -> None:
            if n.get("type") == "TEXT":
                # REST API returns characters in node; name may also hold text in some exports
                chars = n.get("characters")
                texts.append(str(chars if chars is not None else n.get("name") or ""))
            for child in n.get("children") or []:
                if isinstance(child, dict):
                    collect(child)

        collect(node)
        brief = next((t for t in texts if "Content format:" in t or "Contentpijler:" in t), "")
        hooks = [t for t in texts if t.startswith("Hook / tekst in post:") or "Hook / tekst in post:" in t]
        hook = ""
        for h in hooks:
            if is_usable_classification(parse_hook_field(h)["hook_raw"]):
                hook = h
                break
        if not hook and hooks:
            hook = hooks[0]
        parsed_name = parse_section_name(name)
        brief_fields = parse_brief_fields(brief)
        hook_fields = parse_hook_field(hook)
        out.append(
            {
                "node_id": node_id,
                "source_url": figma_source_url(file_key, node_id),
                "page_name": page_name,
                "page_node_id": page_id,
                "period_year": year,
                "period_month": month,
                "code": parsed_name["code"],
                "content_kind": brief_fields["content_kind"] or parsed_name["content_kind_from_name"],
                "platform_hint": brief_fields["platform_hint"],
                "format_raw": brief_fields["format_raw"],
                "format_usable": brief_fields["format_usable"],
                "pillar_raw": brief_fields["pillar_raw"],
                "pillar_usable": brief_fields["pillar_usable"],
                "hook_raw": hook_fields["hook_raw"],
                "hook_usable": hook_fields["hook_usable"],
                "brief_excerpt": brief_fields["brief_excerpt"],
                "raw": {"section_name": name},
            }
        )
        return
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _walk_sections(child, page_name, page_id, file_key, year, month, out)


def extract_items_from_figma_document(doc: dict[str, Any], file_key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    document = doc.get("document") or {}
    for page in document.get("children") or []:
        if not isinstance(page, dict):
            continue
        page_name = str(page.get("name") or "")
        page_id = normalize_node_id(str(page.get("id") or ""))
        year, month = period_from_page_name(page_name)
        _walk_sections(page, page_name, page_id, file_key, year, month, items)
    return items


def sync_from_figma_api(conn, client_id: int) -> dict[str, Any]:
    link = get_figma_connection(conn, client_id)
    if not link["linked"]:
        raise ValueError("Link a Figma file to this client first.")
    doc = fetch_figma_file(link["file_key"])
    items = extract_items_from_figma_document(doc, link["file_key"])
    stats = upsert_planning_items(conn, client_id, items)
    now = _now()
    note = f"Synced via Figma API; {stats['inserted']} new, {stats['updated']} updated."
    conn.execute(
        """
        UPDATE client_figma_files
        SET last_synced_at = ?, last_sync_note = ?, updated_at = ?
        WHERE client_id = ?
        """,
        (now, note, now, client_id),
    )
    return {
        "connection": get_figma_connection(conn, client_id),
        "stats": stats,
        "items": list_planning_items(conn, client_id),
        "source": "figma_api",
    }


def sync_from_metadata_files(
    conn,
    client_id: int,
    pages: list[dict[str, Any]],
    *,
    file_key: str,
    note: str = "",
) -> dict[str, Any]:
    """Import from MCP metadata XML snapshots (no Figma write)."""
    save_figma_connection(
        conn,
        client_id,
        file_key=file_key,
        source_url=figma_source_url(file_key),
        sync_note=note or "Import from Figma metadata snapshot",
    )
    all_items: list[dict[str, Any]] = []
    for page in pages:
        xml = str(page.get("xml") or "")
        all_items.extend(
            parse_items_from_metadata_xml(
                xml,
                file_key=file_key,
                page_name=str(page.get("page_name") or ""),
                page_node_id=normalize_node_id(str(page.get("page_node_id") or "")),
            )
        )
    stats = upsert_planning_items(conn, client_id, all_items)
    now = _now()
    sync_note = note or f"Metadata import; {stats['inserted']} new, {stats['updated']} updated."
    conn.execute(
        """
        UPDATE client_figma_files
        SET last_synced_at = ?, last_sync_note = ?, updated_at = ?
        WHERE client_id = ?
        """,
        (now, sync_note, now, client_id),
    )
    return {
        "connection": get_figma_connection(conn, client_id),
        "stats": stats,
        "items": list_planning_items(conn, client_id),
        "source": "metadata_snapshot",
    }


def suggest_post_matches(conn, client_id: int, item_id: int, limit: int = 12) -> list[dict[str, Any]]:
    """Hints only — week codes do not prove a published post match.

    Month + week letter (e.g. Reel B1 in November → prefer posts in November week B)
    raise the hint score, but multiple candidates still require manual confirm.
    """
    from maaike.repository import list_posts

    row = conn.execute(
        "SELECT * FROM figma_planning_items WHERE id = ? AND client_id = ?",
        (item_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Planning item not found.")
    item = _item_out(row)
    posts = list_posts(conn, client_id)
    year = item.get("period_year")
    month = item.get("period_month")
    kind = (item.get("content_kind") or "").lower()
    target_week = week_letter_from_code(item.get("code"))
    scored: list[dict[str, Any]] = []
    for post in posts:
        score = 0
        reasons: list[str] = []
        pub = str(post.published_at or "")
        pub_day = _parse_publish_date(pub)
        same_month = False
        if year and month and pub_day:
            if pub_day.year == int(year) and pub_day.month == int(month):
                same_month = True
                score += 4
                reasons.append(f"same planning month ({year}-{int(month):02d})")
            post_week = week_letter_for_date(pub_day, year=int(year), month=int(month))
            if target_week and post_week == target_week:
                score += 5
                reasons.append(f"same week letter {target_week} (hint only)")
            elif target_week and post_week and same_month:
                reasons.append(f"other week letter {post_week} (wanted {target_week})")
        elif year and month and pub.startswith(f"{year}-{int(month):02d}"):
            same_month = True
            score += 4
            reasons.append(f"same planning month ({year}-{int(month):02d})")
        pk = str(post.content_kind or "").lower()
        if kind == "reel" and "reel" in pk:
            score += 2
            reasons.append("content kind reel")
        elif kind == "story" and "story" in pk:
            score += 2
            reasons.append("content kind story")
        elif kind == "post" and pk in {"image", "carousel_album", "album", "post"}:
            score += 1
            reasons.append("content kind post-like")
        if item.get("platform_hint") and post.platform == item["platform_hint"]:
            score += 1
            reasons.append("platform hint")
        # Caption overlap with hook — weak signal only
        hook = (item.get("hook_raw") or "")[:40].lower()
        caption = (post.caption or "").lower()
        if item.get("hook_usable") and hook and hook[:20] in caption:
            score += 2
            reasons.append("caption overlaps hook text")
        # Without month/week overlap, content-kind-only matches stay weak and capped lower.
        if not same_month and score > 0:
            reasons.append("outside planning month")
        if score <= 0:
            continue
        confidence = "low"
        if same_month and target_week and any("same week letter" in r for r in reasons):
            confidence = "medium"
            # Still never auto-link: multiple reels in the same week stay ambiguous.
        scored.append(
            {
                "post_id": post.post_id,
                "platform": post.platform,
                "published_at": post.published_at,
                "content_kind": post.content_kind,
                "permalink": post.permalink,
                "format_name": post.format_name,
                "pillar_name": post.pillar_name,
                "hook": post.hook,
                "caption_preview": (post.caption or "")[:120],
                "score": score,
                "reasons": reasons,
                "same_planning_month": same_month,
                "week_letter": (
                    week_letter_for_date(pub_day, year=int(year), month=int(month))
                    if year and month and pub_day
                    else None
                ),
                "planning_week_letter": target_week,
                "planning_month": f"{year}-{int(month):02d}" if year and month else None,
                "confidence": confidence,
                "note": (
                    "Week codes like B1 are month/week hints only — confirm the post yourself. "
                    "Several reels in the same week are not auto-linked."
                ),
            }
        )
    scored.sort(key=lambda x: (-x["score"], str(x["published_at"] or "")))
    # When the planning month is known, prefer that month — do not flood with other months.
    if year and month:
        in_month = [s for s in scored if s.get("same_planning_month")]
        return in_month[:limit]
    return scored[:limit]


def content_kind_label(kind: str | None) -> str:
    """Human-facing content-kind label (NL) for Figma vs published comparison."""
    raw = str(kind or "").strip().lower()
    mapping = {
        "reel": "reel",
        "story": "story",
        "image": "afbeelding",
        "photo": "afbeelding",
        "carousel_album": "carrousel",
        "carousel": "carrousel",
        "album": "carrousel",
        "video": "video",
        "post": "post",
    }
    if raw in mapping:
        return mapping[raw]
    if "carousel" in raw:
        return "carrousel"
    if "reel" in raw:
        return "reel"
    if "story" in raw:
        return "story"
    return raw or "onbekend"


def content_kinds_compatible(figma_kind: str | None, post_kind: str | None) -> bool:
    a = content_kind_label(figma_kind)
    b = content_kind_label(post_kind)
    if a == "onbekend" or b == "onbekend":
        return True
    return a == b


def preview_link_to_post(conn, client_id: int, item_id: int, post_id: int) -> dict[str, Any]:
    """Show which post fields would change — never claims auto-overwrite of filled values."""
    from maaike.repository import list_posts

    row = conn.execute(
        "SELECT * FROM figma_planning_items WHERE id = ? AND client_id = ?",
        (item_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Planning item not found.")
    item = _item_out(row)
    posts = {p.post_id: p for p in list_posts(conn, client_id)}
    post = posts.get(post_id)
    if post is None:
        raise ValueError("Post not found for this client.")

    changes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def consider(field: str, proposed: str | None, current: str | None, usable: bool) -> None:
        if not usable or not (proposed or "").strip():
            skipped.append(
                {
                    "field": field,
                    "reason": "Figma value missing or unusable (placeholder / n.v.t.)",
                    "proposed": proposed or "",
                    "current": current or "",
                }
            )
            return
        if (current or "").strip():
            skipped.append(
                {
                    "field": field,
                    "reason": "Existing manual value kept — will not overwrite",
                    "proposed": proposed,
                    "current": current,
                }
            )
            return
        changes.append(
            {
                "field": field,
                "action": "fill",
                "from": current or "",
                "to": proposed,
            }
        )

    consider("format", item["format_raw"] if item["format_usable"] else "", post.format_name, item["format_usable"])
    consider("pillar", item["pillar_raw"] if item["pillar_usable"] else "", post.pillar_name, item["pillar_usable"])
    consider("hook", item["hook_raw"] if item["hook_usable"] else "", post.hook, item["hook_usable"])

    figma_label = content_kind_label(item.get("content_kind"))
    published_label = content_kind_label(post.content_kind)
    kind_mismatch = not content_kinds_compatible(item.get("content_kind"), post.content_kind)
    compare_line = f"Figma: {figma_label} · Gepubliceerd: {published_label}"

    return {
        "item": item,
        "post": {
            "post_id": post.post_id,
            "platform": post.platform,
            "published_at": post.published_at,
            "content_kind": post.content_kind,
            "content_kind_label": published_label,
            "format_name": post.format_name,
            "pillar_name": post.pillar_name,
            "hook": post.hook,
            "permalink": post.permalink,
        },
        "content_kind_compare": {
            "figma_kind": item.get("content_kind"),
            "figma_label": figma_label,
            "published_kind": post.content_kind,
            "published_label": published_label,
            "mismatch": kind_mismatch,
            "display": compare_line,
            "requires_explicit_accept": kind_mismatch,
            "accept_prompt": (
                "Ik bevestig bewust dat Figma en de gepubliceerde post een andere contentsoort hebben."
                if kind_mismatch
                else None
            ),
        },
        "changes": changes,
        "skipped": skipped,
        "requires_confirmation": True,
        "note": (
            f"{compare_line}. Confirm manually. Week codes are hints only."
            + (
                " Contentsoort wijkt af — vink expliciet aan dat je die afwijking accepteert vóór bevestigen."
                if kind_mismatch
                else ""
            )
        ),
    }


def apply_link_to_post(
    conn,
    client_id: int,
    item_id: int,
    post_id: int,
    *,
    confirm: bool = False,
    accept_content_kind_mismatch: bool = False,
) -> dict[str, Any]:
    from maaike.repository import list_formats, list_pillars, save_editorial

    if not confirm:
        raise ValueError("Set confirm=true after reviewing the field preview.")
    preview = preview_link_to_post(conn, client_id, item_id, post_id)
    compare = preview.get("content_kind_compare") or {}
    if compare.get("mismatch") and not accept_content_kind_mismatch:
        raise ValueError(
            f"{compare.get('display')}. "
            "Set accept_content_kind_mismatch=true to consciously accept this difference. "
            "Nothing was saved."
        )
    post = preview["post"]
    item = preview["item"]

    formats = {f.name.lower(): f for f in list_formats(conn, client_id)}
    pillars = {p.name.lower(): p for p in list_pillars(conn, client_id)}

    format_id = None
    if post.get("format_name"):
        fmt = formats.get(str(post["format_name"]).lower())
        format_id = fmt.item_id if fmt else None
    pillar_id = None
    if post.get("pillar_name"):
        pil = pillars.get(str(post["pillar_name"]).lower())
        pillar_id = pil.item_id if pil else None
    hook = post.get("hook") or ""

    for change in preview["changes"]:
        field = change["field"]
        value = change["to"]
        if field == "format":
            fmt = formats.get(value.lower())
            if fmt is None:
                # Do not invent formats — skip if legend has no match
                preview.setdefault("warnings", []).append(
                    f"Format '{value}' not in client Format tab — not applied."
                )
            else:
                format_id = fmt.item_id
        elif field == "pillar":
            pil = pillars.get(value.lower())
            if pil is None:
                preview.setdefault("warnings", []).append(
                    f"Pillar '{value}' not in client legend — not applied."
                )
            else:
                pillar_id = pil.item_id
        elif field == "hook":
            hook = value

    # Only call save_editorial if we are filling something or already had values to keep
    # Reconstruct current IDs for fields we keep
    if format_id is None and post.get("format_name"):
        fmt = formats.get(str(post["format_name"]).lower())
        format_id = fmt.item_id if fmt else None
    if pillar_id is None and post.get("pillar_name"):
        pil = pillars.get(str(post["pillar_name"]).lower())
        pillar_id = pil.item_id if pil else None

    save_editorial(
        conn,
        client_id,
        post_id=post_id,
        format_id=format_id,
        pillar_id=pillar_id,
        hook=hook or "",
    )
    now = _now()
    conn.execute(
        """
        UPDATE figma_planning_items
        SET linked_post_id = ?, link_status = 'linked_confirmed', updated_at = ?
        WHERE id = ? AND client_id = ?
        """,
        (post_id, now, item_id, client_id),
    )
    return {
        "ok": True,
        "preview": preview_link_to_post(conn, client_id, item_id, post_id),
        "item": _item_out(
            conn.execute(
                "SELECT * FROM figma_planning_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        ),
    }


def planning_overview(conn, client_id: int) -> dict[str, Any]:
    token = resolve_figma_token()
    return {
        "connection": get_figma_connection(conn, client_id),
        "items": list_planning_items(conn, client_id),
        "figma_api": {
            "configured": token["configured"],
            "missing_setting": token["missing_setting"],
            "note": (
                "Live re-sync from Figma API needs FIGMA_ACCESS_TOKEN. "
                "Metadata snapshot import works without it."
            ),
        },
        "rules": {
            "unusable_placeholders": sorted(UNUSABLE_VALUES),
            "no_auto_overwrite": True,
            "week_code_not_proof": True,
            "figma_read_only": True,
        },
    }
