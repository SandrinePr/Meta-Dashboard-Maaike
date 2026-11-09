"""Compare a few Excel Post performance rows to Red Rock DB (read-only)."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import load_workbook

XLSX = Path(r"c:\Users\SandrinePrumpelerRed\Downloads\RRO_Social strategie overzicht_2026.xlsx")
DB = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock.db")
OUT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\imports\redrock\_excel_vs_db_sample.json")


def norm_url(u: str | None) -> str:
    if not u:
        return ""
    s = str(u).strip().split("?")[0].rstrip("/").lower()
    return s


def main() -> None:
    wb = load_workbook(XLSX, data_only=True)
    ws = wb["Post performance"]
    headers = {ws.cell(1, c).value: c for c in range(1, 20) if ws.cell(1, c).value}
    excel_rows = []
    for r in range(2, ws.max_row + 1):
        url = ws.cell(r, headers["Post: URL van post"]).value
        plat = ws.cell(r, headers["Platform"]).value
        if not plat:
            continue
        excel_rows.append(
            {
                "row": r,
                "maand": ws.cell(r, headers["Maand"]).value,
                "datum": str(ws.cell(r, headers["Datum"]).value),
                "platform": plat,
                "format": ws.cell(r, headers["Content format"]).value,
                "url": url,
                "url_n": norm_url(url),
                "pillar": ws.cell(r, headers["Contentpijler"]).value,
                "hook": ws.cell(r, headers["Hook"]).value,
                "views": ws.cell(r, headers["Weergaven"]).value,
                "likes": ws.cell(r, headers["Likes"]).value,
                "beoordeling": ws.cell(r, headers["Beoordeling"]).value,
                "score": ws.cell(r, headers["Score"]).value,
                "insight": (str(ws.cell(r, headers["Insight: waarom gebeurde dit?"]).value or "")[:80]),
                "action": (
                    str(
                        ws.cell(r, headers["Actie: wat doen we de volgende keer anders?"]).value or ""
                    )[:80]
                ),
            }
        )

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cid = conn.execute("SELECT id FROM clients WHERE name='Red Rock'").fetchone()["id"]
    posts = conn.execute(
        """
        SELECT p.id, p.platform, p.permalink, p.published_at, p.source_origin,
               pe.format_code_raw, pe.hook, pe.content_soort_raw,
               a.rating_text, a.insight_text, a.action_text, a.source
        FROM posts p
        LEFT JOIN post_editorial pe ON pe.post_id=p.id
        LEFT JOIN post_assessments a ON a.post_id=p.id AND a.source='excel_imported'
        WHERE p.client_id=?
        """,
        (cid,),
    ).fetchall()
    by_url = {}
    for p in posts:
        nu = norm_url(p["permalink"])
        if nu:
            by_url[nu] = dict(p)

    matched = []
    missing = []
    diverged = []
    for er in excel_rows:
        if not er["url_n"]:
            continue
        db = by_url.get(er["url_n"])
        if not db:
            # try substring match
            hits = [v for k, v in by_url.items() if er["url_n"] in k or k in er["url_n"]]
            db = hits[0] if hits else None
        if not db:
            missing.append(er)
            continue
        issues = []
        if (er["beoordeling"] or "") != (db["rating_text"] or "") and er["beoordeling"]:
            issues.append(f"beoordeling excel={er['beoordeling']!r} db={db['rating_text']!r}")
        if er["format"] and not (db["format_code_raw"] or ""):
            # format may be via format_id
            issues.append("format_code_raw leeg (mogelijk via format_id)")
        if er["hook"] and (db["hook"] or "") != str(er["hook"]):
            # only flag if db empty
            if not db["hook"]:
                issues.append("hook ontbreekt in DB")
        insight_db = (db["insight_text"] or "").strip()
        if er["insight"] and not insight_db:
            issues.append("insight ontbreekt in DB")
        entry = {"excel": er, "db_post_id": db["id"], "db_rating": db["rating_text"], "issues": issues}
        if issues:
            diverged.append(entry)
        else:
            matched.append(entry)

    # score not stored?
    score_cols = conn.execute("PRAGMA table_info(post_assessments)").fetchall()

    out = {
        "excel_data_rows": len(excel_rows),
        "excel_with_url": sum(1 for e in excel_rows if e["url_n"]),
        "db_posts_with_permalink": len(by_url),
        "matched_ok": len(matched),
        "matched_with_issues": len(diverged),
        "excel_url_not_in_db": len(missing),
        "missing_sample": missing[:8],
        "diverged_sample": diverged[:10],
        "matched_sample": matched[:5],
        "assessment_columns": [r[1] for r in score_cols],
        "note": "Score column is not stored in post_assessments schema",
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in out if k.endswith("sample") is False}, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
