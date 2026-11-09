"""Re-run import for excel dates, verify row 64 / exports / strategy pending."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maaike.db import initialize_database, transaction
from maaike.excel_import import execute_import, parse_workbook
from maaike.logs_export import export_csv_bytes, export_xlsx_bytes, filtered_export_posts
from maaike.strategy import get_strategy


def main() -> int:
    xlsx = ROOT / "data" / "imports" / "redrock" / "RRO_Social_strategie_overzicht_2026.xlsx"
    initialize_database()
    parsed = parse_workbook(xlsx)
    with transaction() as conn:
        client_id = int(
            conn.execute(
                "SELECT id FROM clients WHERE name = ? COLLATE NOCASE",
                ("Red Rock",),
            ).fetchone()[0]
        )
        result = execute_import(conn, client_id, path=xlsx, parsed=parsed)
        print("IMPORT", json.dumps(result["applied"], ensure_ascii=False))
        row64 = conn.execute(
            """
            SELECT p.id, p.external_id, p.permalink, p.platform_label, e.hook,
                   a.rating_text, a.insight_text, a.action_text, l.excel_published_at
            FROM post_import_links l
            JOIN posts p ON p.id = l.post_id
            LEFT JOIN post_editorial e ON e.post_id = p.id
            LEFT JOIN post_assessments a ON a.post_id = p.id AND a.source = 'excel_imported'
            WHERE l.source_row = 64 AND p.client_id = ?
            """,
            (client_id,),
        ).fetchone()
        print("ROW64", dict(row64) if row64 else None)
        links = conn.execute(
            "SELECT COUNT(*) FROM post_import_links l JOIN posts p ON p.id=l.post_id WHERE p.client_id=?",
            (client_id,),
        ).fetchone()[0]
        print("LINKS", links)
        dated = conn.execute(
            """
            SELECT COUNT(*) FROM post_import_links l
            JOIN posts p ON p.id = l.post_id
            WHERE p.client_id = ? AND l.excel_published_at IS NOT NULL
            """,
            (client_id,),
        ).fetchone()[0]
        print("EXCEL_DATES_STORED", dated)
        # date mismatch example row 2
        r2 = conn.execute(
            """
            SELECT p.published_at, l.excel_published_at FROM post_import_links l
            JOIN posts p ON p.id = l.post_id
            WHERE l.source_row = 2 AND p.client_id = ?
            """,
            (client_id,),
        ).fetchone()
        print("ROW2_DATES", dict(r2) if r2 else None)
        posts = filtered_export_posts(conn, client_id, {"platform": "LinkedIn"})
        xbytes = export_xlsx_bytes(posts)
        cbytes = export_csv_bytes(posts)
        print("EXPORT_LI_FILTER", len(posts), "xlsx", len(xbytes), "csv", len(cbytes))
        # full export contains insight for row 64
        all_posts = filtered_export_posts(conn, client_id, {})
        print("EXPORT_ALL", len(all_posts))
        strategy = get_strategy(conn, client_id)
        print("PENDING", json.dumps(strategy["pending_questions"], ensure_ascii=False, indent=2))
        formats = conn.execute(
            "SELECT COUNT(*) FROM content_formats WHERE client_id=? AND TRIM(explanation)!=''",
            (client_id,),
        ).fetchone()[0]
        print("FORMATS_WITH_EXPLANATION", formats)
        # client separation
        other = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE client_id != ?",
            (client_id,),
        ).fetchone()[0]
        print("OTHER_CLIENT_POSTS", other)
        reimport = execute_import(conn, client_id, path=xlsx, parsed=parsed)
        print("REIMPORT_ADDED", reimport["applied"]["added"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
