"""Excel/CSV export of filtered Logs rows (full selection, not page slice)."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from openpyxl import Workbook

from maaike.presentation import overview_record
from maaike.repository import StoredPost, list_posts

EXPORT_COLUMNS = [
    "Maand",
    "Publicatiedatum",
    "Platform",
    "Account",
    "Meta-post-ID",
    "Contentsoort",
    "Contentformat",
    "Post-URL",
    "Contentpijler",
    "Hook",
    "Weergaven",
    "Bereik",
    "Likes",
    "Comments",
    "Shares",
    "Saves",
    "Clicks",
    "Beoordeling",
    "Insight",
    "Actie",
    "Bron",
]


def filter_posts(
    posts: list[StoredPost],
    *,
    platform: str | None = None,
    content_soort: str | None = None,
    format_code: str | None = None,
    pillar: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    missing: str | None = None,
) -> list[StoredPost]:
    out = []
    missing_mode = (missing or "").strip().lower()
    for post in posts:
        label = (post.platform_label or post.platform or "").lower()
        if platform and platform.lower() not in label and platform.lower() != post.platform.lower():
            continue
        soort = (post.content_soort_raw or post.content_kind or "").lower()
        if content_soort and content_soort.lower() not in soort:
            continue
        fmt = (post.format_name or post.format_code_raw or "").lower()
        if format_code and format_code.lower() not in fmt:
            continue
        pil = (post.pillar_name or "").lower()
        if pillar and pillar.lower() not in pil:
            continue
        pub = (post.published_at or "")[:10]
        if date_from and pub and pub < date_from:
            continue
        if date_to and pub and pub > date_to:
            continue
        if missing_mode:
            miss_format = post.format_id is None
            miss_pillar = post.pillar_id is None
            miss_hook = not str(post.hook or "").strip()
            if missing_mode == "any" and not (miss_format or miss_pillar or miss_hook):
                continue
            if missing_mode == "format" and not miss_format:
                continue
            if missing_mode == "pillar" and not miss_pillar:
                continue
            if missing_mode == "hook" and not miss_hook:
                continue
        out.append(post)
    return out


def rows_for_export(posts: list[StoredPost]) -> list[dict[str, Any]]:
    rows = []
    for post in posts:
        cells = overview_record(post)
        cells["Bron"] = post.source_origin or ("meta" if post.last_synced_at else "")
        rows.append({col: cells.get(col, "") for col in EXPORT_COLUMNS})
    return rows


def export_csv_bytes(posts: list[StoredPost]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows_for_export(posts):
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


def export_xlsx_bytes(posts: list[StoredPost]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Logs"
    ws.append(EXPORT_COLUMNS)
    for row in rows_for_export(posts):
        ws.append([row.get(col, "") for col in EXPORT_COLUMNS])
    # Widen insight/action columns
    ws.column_dimensions["S"].width = 60
    ws.column_dimensions["T"].width = 60
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def filtered_export_posts(conn, client_id: int, filters: dict[str, str | None]) -> list[StoredPost]:
    posts = list_posts(conn, client_id)
    return filter_posts(
        posts,
        platform=filters.get("platform") or None,
        content_soort=filters.get("content_soort") or None,
        format_code=filters.get("format") or None,
        pillar=filters.get("pillar") or None,
        date_from=filters.get("date_from") or None,
        date_to=filters.get("date_to") or None,
        missing=filters.get("missing") or None,
    )


def export_filename(ext: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"redrock-logs-{stamp}.{ext}"
