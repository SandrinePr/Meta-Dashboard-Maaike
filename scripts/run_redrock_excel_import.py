"""Backup DB, preview and import Red Rock Excel on temp then real database."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maaike.db import connect, initialize_database, transaction
from maaike.excel_import import backup_database, build_preview, execute_import, parse_workbook
from maaike.strategy import prefill_red_rock_from_sources


def main() -> int:
    xlsx = ROOT / "data" / "imports" / "redrock" / "RRO_Social_strategie_overzicht_2026.xlsx"
    db = ROOT / "data" / "maaike_redrock.db"
    backups = ROOT / "data" / "backups"
    imports_dir = ROOT / "data" / "imports" / "redrock"
    if not xlsx.exists() or xlsx.stat().st_size < 1000:
        print("MISSING_EXCEL", xlsx)
        return 1
    backup = backup_database(db, backups)
    print("BACKUP", backup)

    temp_db = ROOT / "data" / "maaike_redrock_import_test.db"
    shutil.copy2(db, temp_db)
    initialize_database(temp_db)
    parsed = parse_workbook(xlsx)
    with transaction(temp_db) as conn:
        client = conn.execute(
            "SELECT id FROM clients WHERE name = ? COLLATE NOCASE",
            ("Red Rock",),
        ).fetchone()
        if client is None:
            print("NO_RED_ROCK_CLIENT")
            return 2
        client_id = int(client[0])
        preview = build_preview(conn, client_id, parsed)
        print("TEMP_PREVIEW", json.dumps(preview["counts"], ensure_ascii=False))
        result = execute_import(conn, client_id, path=xlsx, parsed=parsed)
        print("TEMP_IMPORT", json.dumps(result, ensure_ascii=False))
        # reimport should not duplicate posts
        result2 = execute_import(conn, client_id, path=xlsx, parsed=parsed)
        print("TEMP_REIMPORT", json.dumps(result2, ensure_ascii=False))
        posts = conn.execute(
            "SELECT platform, COUNT(*) c FROM posts WHERE client_id = ? GROUP BY platform",
            (client_id,),
        ).fetchall()
        print("TEMP_PLATFORMS", [dict(r) for r in posts])
        linkedin = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE client_id = ? AND platform LIKE 'linkedin%'",
            (client_id,),
        ).fetchone()[0]
        assessments = conn.execute(
            "SELECT COUNT(*) FROM post_assessments WHERE source = 'excel_imported'"
        ).fetchone()[0]
        print("TEMP_LINKEDIN", linkedin, "ASSESSMENTS", assessments)

    # Real DB
    initialize_database(db)
    with transaction(db) as conn:
        client = conn.execute(
            "SELECT id FROM clients WHERE name = ? COLLATE NOCASE",
            ("Red Rock",),
        ).fetchone()
        client_id = int(client[0])
        preview = build_preview(conn, client_id, parsed)
        print("REAL_PREVIEW", json.dumps(preview["counts"], ensure_ascii=False))
        (imports_dir / "_last_preview.json").write_text(
            json.dumps(preview, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result = execute_import(conn, client_id, path=xlsx, parsed=parsed)
        print("REAL_IMPORT", json.dumps(result, ensure_ascii=False))
        strategy = prefill_red_rock_from_sources(conn, client_id, imports_dir)
        print(
            "STRATEGY_PREFILL",
            "answered",
            [k for k, v in strategy["start_answers"].items() if str(v).strip()],
            "missing",
            strategy["missing_required"],
        )
        posts = conn.execute(
            "SELECT platform, COUNT(*) c FROM posts WHERE client_id = ? GROUP BY platform",
            (client_id,),
        ).fetchone()
        platforms = conn.execute(
            "SELECT platform, COUNT(*) c FROM posts WHERE client_id = ? GROUP BY platform ORDER BY 1",
            (client_id,),
        ).fetchall()
        print("REAL_PLATFORMS", [dict(r) for r in platforms])
        print(
            "REAL_ASSESSMENTS",
            conn.execute("SELECT COUNT(*) FROM post_assessments").fetchone()[0],
        )
        print(
            "REAL_READINGS",
            conn.execute("SELECT COUNT(*) FROM post_metric_readings").fetchone()[0],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
