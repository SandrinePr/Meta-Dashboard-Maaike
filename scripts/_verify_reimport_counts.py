"""Verify reimport counts and preserved missing-cache records. Read-only."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from maaike.excel_import import build_preview, parse_workbook

ROOT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike")
RES = ROOT / "data" / "imports" / "redrock" / "_controlled_reimport_result.json"
XLSX = Path(r"c:\Users\SandrinePrumpelerRed\Downloads\RRO_Social strategie overzicht_2026.xlsx")
LIVE = ROOT / "data" / "maaike_redrock.db"


def main() -> None:
    res = json.loads(RES.read_text(encoding="utf-8"))
    applied = res["execute_result"]["applied"]
    before = res["live_preview_before_import"]["mutually_exclusive"]
    after = res["live_preview_after_import"]
    backup = Path(res["backup_path"])

    print("=== IMPORTRESULTAAT ===")
    print("preview_before:", before)
    print("applied:", applied)
    print("preview_after:", after)
    print()
    print("Juiste lezing:")
    print(
        f"  4 nieuw + 20 label + 57 score-only = "
        f"{4 + 20 + 57} records met inhoudelijke wijziging"
    )
    print(
        f"  Daarvan bestaande updates: 20 + 57 = 77 "
        f"(= applied.assessments_updated {applied['assessments_updated']}? "
        f"{applied['assessments_updated'] == 77})"
    )
    print(
        f"  applied assessments_updated={applied['assessments_updated']} "
        f"(= 77 wijzigingen + 4 preserved-touch? "
        f"{applied['assessments_updated'] == 77 + applied.get('assessments_preserved_missing_cache', 0)})"
    )
    print(
        f"  assessments_inserted={applied['assessments_inserted']} "
        f"(verwacht 4: {applied['assessments_inserted'] == 4})"
    )
    print(
        f"  inserted+updated={applied['assessments_inserted'] + applied['assessments_updated']} "
        f"(technische writes, niet 20+57)"
    )

    conn_b = sqlite3.connect(backup)
    conn_b.row_factory = sqlite3.Row
    conn_l = sqlite3.connect(LIVE)
    conn_l.row_factory = sqlite3.Row
    cid = conn_l.execute(
        "SELECT id FROM clients WHERE name = 'Red Rock' COLLATE NOCASE"
    ).fetchone()[0]

    # Baseline vs live assessment counts
    def count_excel(conn):
        return conn.execute(
            """
            SELECT COUNT(*) FROM post_assessments a
            JOIN posts p ON p.id = a.post_id
            WHERE p.client_id = ? AND a.source = 'excel_imported'
            """,
            (cid,),
        ).fetchone()[0]

    before_n = count_excel(conn_b)
    after_n = count_excel(conn_l)
    print()
    print("=== DB ASSESSMENT COUNTS ===")
    print(f"backup excel_imported: {before_n}")
    print(f"live excel_imported:   {after_n}")
    print(f"delta (expect +4 new): {after_n - before_n}")

    parsed = parse_workbook(XLSX)
    backup_cols = {
        str(r[1]) for r in conn_b.execute("PRAGMA table_info(post_assessments)").fetchall()
    }
    backup_has_score = "score_value" in backup_cols
    backup_select = "rating_text, insight_text, action_text"
    if backup_has_score:
        backup_select += ", score_value"

    # Identify preserved posts: linked rows where Excel cache missing AND backup had values
    prev_live = build_preview(conn_l, cid, parsed)
    preserved = []
    for row in prev_live["rows"]:
        if row.get("action") != "link":
            continue
        if not (row.get("rating_missing_reason") or row.get("score_missing_reason")):
            continue
        pid = row["post_id"]
        b = conn_b.execute(
            f"""
            SELECT {backup_select}
            FROM post_assessments
            WHERE post_id = ? AND source = 'excel_imported'
            ORDER BY id DESC LIMIT 1
            """,
            (pid,),
        ).fetchone()
        if b is None:
            continue
        b_score = b["score_value"] if backup_has_score else None
        # only rows that had something to preserve
        if not (b["rating_text"] or b_score is not None):
            continue
        a = conn_l.execute(
            """
            SELECT rating_text, score_value, insight_text, action_text
            FROM post_assessments
            WHERE post_id = ? AND source = 'excel_imported'
            ORDER BY id DESC LIMIT 1
            """,
            (pid,),
        ).fetchone()
        preserved.append(
            {
                "post_id": pid,
                "excel_row": row["excel_row"],
                "missing_rating": bool(row.get("rating_missing_reason")),
                "missing_score": bool(row.get("score_missing_reason")),
                "backup_rating": b["rating_text"],
                "live_rating": a["rating_text"] if a else None,
                "backup_score": b_score,
                "live_score": a["score_value"] if a else None,
                "rating_preserved": a is not None and a["rating_text"] == b["rating_text"],
                "score_preserved": (
                    True
                    if not backup_has_score
                    else (a is not None and a["score_value"] == b_score)
                ),
                "insight_preserved": a is not None
                and (a["insight_text"] or "") == (b["insight_text"] or ""),
                "action_preserved": a is not None
                and (a["action_text"] or "") == (b["action_text"] or ""),
            }
        )

    print()
    print("=== ONTBREKENDE CACHE MET BESTAANDE WAARDEN ===")
    print("count:", len(preserved))
    print(json.dumps(preserved, ensure_ascii=False, indent=2, default=str))
    ok = all(
        p["rating_preserved"]
        and p["score_preserved"]
        and p["insight_preserved"]
        and p["action_preserved"]
        for p in preserved
    )
    print("all_content_preserved:", ok)
    print(
        "applied.assessments_preserved_missing_cache:",
        applied.get("assessments_preserved_missing_cache"),
    )

    # Clarify 81 vs 77
    print()
    print("=== CONCLUSIE TELLING ===")
    print(
        {
            "inhoudelijk_nieuw": 4,
            "inhoudelijk_bestaand_gewijzigd": 77,
            "inhoudelijk_totaal_gewijzigd": 81,
            "applied_inserted": applied["assessments_inserted"],
            "applied_updated": applied["assessments_updated"],
            "applied_updated_includes_preserved_noop_writes": applied["assessments_updated"]
            == 77 + applied.get("assessments_preserved_missing_cache", 0),
            "correct_statement": (
                "4 nieuw + 77 bestaande inhoudelijke wijzigingen = 81 records met effect. "
                "applied.assessments_updated=81 telt 77 echte updates + 4 preserve-writes "
                "waarbij ontbrekende cache bestaande waarden niet overschreef."
                if applied["assessments_updated"]
                == 77 + applied.get("assessments_preserved_missing_cache", 0)
                else "applied.updated wijkt af van 77+preserved"
            ),
        }
    )

    conn_b.close()
    conn_l.close()


if __name__ == "__main__":
    main()
