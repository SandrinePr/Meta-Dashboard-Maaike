"""Backup, reimport (incl. row 64), audit 91 Excel rows vs DB, fix formats."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maaike.db import initialize_database, transaction
from maaike.excel_import import (
    SOURCE_SHEET,
    backup_database,
    build_preview,
    execute_import,
    parse_workbook,
)
from maaike.logs_export import export_csv_bytes, export_xlsx_bytes, filtered_export_posts
from maaike.strategy import get_strategy, prefill_red_rock_from_sources


def _norm(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _metric_excel(row, name: str):
    m = row.metrics[name]
    return m.kind, m.value


def audit(conn, client_id: int, parsed: dict) -> dict:
    issues = []
    links = {
        int(r["source_row"]): r
        for r in conn.execute(
            """
            SELECT l.*, p.platform_label, p.platform, p.external_id, p.permalink,
                   p.published_at, e.format_code_raw, e.content_soort_raw, e.hook,
                   f.name AS format_name, g.name AS pillar_name
            FROM post_import_links l
            JOIN posts p ON p.id = l.post_id
            LEFT JOIN post_editorial e ON e.post_id = p.id
            LEFT JOIN content_formats f ON f.id = e.format_id
            LEFT JOIN content_pillars g ON g.id = e.pillar_id
            WHERE p.client_id = ? AND l.source_sheet = ?
            """,
            (client_id, SOURCE_SHEET),
        ).fetchall()
    }
    assessments = {}
    for r in conn.execute(
        """
        SELECT a.* FROM post_assessments a
        JOIN posts p ON p.id = a.post_id
        WHERE p.client_id = ? AND a.source = 'excel_imported'
        """,
        (client_id,),
    ):
        assessments.setdefault(int(r["source_row"] or -1), []).append(r)

    readings = {}
    for r in conn.execute(
        """
        SELECT m.* FROM post_metric_readings m
        JOIN posts p ON p.id = m.post_id
        WHERE p.client_id = ? AND m.source_name = 'excel_import' AND m.source_sheet = ?
        """,
        (client_id, SOURCE_SHEET),
    ):
        readings.setdefault((int(r["source_row"]), r["metric_name"]), r)

    for row in parsed["rows"]:
        link = links.get(row.excel_row)
        if link is None:
            issues.append({"row": row.excel_row, "type": "missing_import_link"})
            continue
        if _norm(link["platform_label"]) != _norm(row.platform_label):
            issues.append(
                {
                    "row": row.excel_row,
                    "type": "platform_label",
                    "excel": row.platform_label,
                    "db": link["platform_label"],
                }
            )
        pub = _norm(link["published_at"])[:10]
        excel_date = row.datum.isoformat() if row.datum else ""
        if excel_date and pub != excel_date:
            issues.append(
                {"row": row.excel_row, "type": "datum", "excel": excel_date, "db": pub}
            )
        if _norm(row.content_soort) and _norm(link["content_soort_raw"]) != _norm(row.content_soort):
            issues.append(
                {
                    "row": row.excel_row,
                    "type": "content_soort",
                    "excel": row.content_soort,
                    "db": link["content_soort_raw"],
                }
            )
        if _norm(row.format_code):
            raw_ok = _norm(link["format_code_raw"]) == _norm(row.format_code)
            name_ok = _norm(link["format_name"]) == _norm(row.format_code)
            if not raw_ok and not name_ok:
                issues.append(
                    {
                        "row": row.excel_row,
                        "type": "format",
                        "excel": row.format_code,
                        "db_raw": link["format_code_raw"],
                        "db_name": link["format_name"],
                    }
                )
        if _norm(row.contentpijler) and _norm(link["pillar_name"]) != _norm(row.contentpijler):
            issues.append(
                {
                    "row": row.excel_row,
                    "type": "pillar",
                    "excel": row.contentpijler,
                    "db": link["pillar_name"],
                }
            )
        if _norm(row.hook) and _norm(link["hook"]) != _norm(row.hook):
            issues.append(
                {"row": row.excel_row, "type": "hook", "excel": row.hook, "db": link["hook"]}
            )
        if not row.permalink_raw and _norm(link["permalink"]):
            issues.append(
                {
                    "row": row.excel_row,
                    "type": "permalink_invented",
                    "db": link["permalink"],
                }
            )
        if not row.permalink_raw and not str(link["external_id"] or "").startswith("excelrow:"):
            issues.append(
                {
                    "row": row.excel_row,
                    "type": "expected_internal_id",
                    "db": link["external_id"],
                }
            )

        a_list = assessments.get(row.excel_row, [])
        if row.rating_text or row.insight or row.action:
            if not a_list:
                issues.append({"row": row.excel_row, "type": "missing_assessment"})
            else:
                a = a_list[0]
                if _norm(a["rating_text"]) != _norm(row.rating_text):
                    issues.append(
                        {
                            "row": row.excel_row,
                            "type": "rating",
                            "excel": row.rating_text,
                            "db": a["rating_text"],
                        }
                    )
                if _norm(a["insight_text"]) != _norm(row.insight):
                    issues.append(
                        {
                            "row": row.excel_row,
                            "type": "insight",
                            "excel_len": len(_norm(row.insight)),
                            "db_len": len(_norm(a["insight_text"])),
                        }
                    )
                if _norm(a["action_text"]) != _norm(row.action):
                    issues.append(
                        {
                            "row": row.excel_row,
                            "type": "action",
                            "excel_len": len(_norm(row.action)),
                            "db_len": len(_norm(a["action_text"])),
                        }
                    )

        for metric_name in ("views", "likes", "comments", "shares", "saves", "clicks"):
            kind, value = _metric_excel(row, metric_name)
            reading = readings.get((row.excel_row, metric_name))
            if kind == "empty":
                if reading is not None:
                    issues.append(
                        {
                            "row": row.excel_row,
                            "type": "metric_should_be_empty",
                            "metric": metric_name,
                        }
                    )
            elif kind in {"zero", "number", "nvt"}:
                if reading is None:
                    issues.append(
                        {
                            "row": row.excel_row,
                            "type": "missing_reading",
                            "metric": metric_name,
                            "kind": kind,
                        }
                    )
                else:
                    if kind == "nvt" and reading["availability"] != "nvt":
                        issues.append(
                            {
                                "row": row.excel_row,
                                "type": "metric_nvt",
                                "metric": metric_name,
                                "db": reading["availability"],
                            }
                        )
                    if kind in {"zero", "number"} and reading["value"] != value:
                        issues.append(
                            {
                                "row": row.excel_row,
                                "type": "metric_value",
                                "metric": metric_name,
                                "excel": value,
                                "db": reading["value"],
                            }
                        )

    format_codes = {f["code"].lower() for f in parsed["formats"]}
    db_formats = {
        str(r["name"]).lower(): r
        for r in conn.execute(
            "SELECT name, explanation FROM content_formats WHERE client_id = ?",
            (client_id,),
        )
    }
    missing_formats = sorted(code for code in format_codes if code not in db_formats)
    empty_expl = sorted(
        f["code"]
        for f in parsed["formats"]
        if f.get("explanation") and not _norm(db_formats.get(f["code"].lower(), {}).get("explanation") if isinstance(db_formats.get(f["code"].lower()), dict) else "")
    )
    # fix empty_expl check - db_formats values are rows
    empty_expl = []
    for f in parsed["formats"]:
        row = db_formats.get(f["code"].lower())
        if not row:
            continue
        if f.get("explanation") and not _norm(row["explanation"] if not isinstance(row, dict) else row.get("explanation")):
            # sqlite Row
            expl = row["explanation"] if "explanation" in row.keys() else ""
            if f.get("explanation") and not _norm(expl):
                empty_expl.append(f["code"])

    bogus = [
        name
        for name in db_formats
        if "format" in name and " " in name
    ]

    return {
        "excel_rows": len(parsed["rows"]),
        "import_links": len(links),
        "issues": issues,
        "missing_formats": missing_formats,
        "formats_missing_explanation": empty_expl,
        "bogus_format_names": bogus,
        "row64_present": 64 in links,
    }


def remove_bogus_formats(conn, client_id: int) -> list[str]:
    removed = []
    for row in conn.execute(
        "SELECT id, name FROM content_formats WHERE client_id = ?",
        (client_id,),
    ):
        name = str(row["name"])
        if name.lower() in {"reel formats", "linkedin formats zakelijk", "carrousel / post formats"}:
            used = conn.execute(
                "SELECT 1 FROM post_editorial WHERE format_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            if used is None:
                conn.execute("DELETE FROM content_formats WHERE id = ?", (row["id"],))
                removed.append(name)
    return removed


def main() -> int:
    xlsx = ROOT / "data" / "imports" / "redrock" / "RRO_Social_strategie_overzicht_2026.xlsx"
    db = ROOT / "data" / "maaike_redrock.db"
    backup = backup_database(db, ROOT / "data" / "backups")
    print("BACKUP", backup)
    initialize_database(db)
    parsed = parse_workbook(xlsx)
    with transaction(db) as conn:
        client_id = int(
            conn.execute(
                "SELECT id FROM clients WHERE name = ? COLLATE NOCASE",
                ("Red Rock",),
            ).fetchone()[0]
        )
        preview = build_preview(conn, client_id, parsed)
        print("PREVIEW", json.dumps(preview["counts"], ensure_ascii=False))
        row64 = next(r for r in preview["rows"] if r["excel_row"] == 64)
        print("ROW64_PLAN", json.dumps(row64, ensure_ascii=False))
        result = execute_import(conn, client_id, path=xlsx, parsed=parsed)
        print("IMPORT", json.dumps(result, ensure_ascii=False))
        result2 = execute_import(conn, client_id, path=xlsx, parsed=parsed)
        print("REIMPORT", json.dumps(result2, ensure_ascii=False))
        removed = remove_bogus_formats(conn, client_id)
        print("REMOVED_BOGUS_FORMATS", removed)
        report = audit(conn, client_id, parsed)
        # export checks
        posts = filtered_export_posts(conn, client_id, {})
        xbytes = export_xlsx_bytes(posts)
        cbytes = export_csv_bytes(posts)
        report["export_xlsx_bytes"] = len(xbytes)
        report["export_csv_bytes"] = len(cbytes)
        report["export_rows"] = len(posts)
        # insight length check in xlsx via openpyxl
        from openpyxl import load_workbook
        from io import BytesIO

        wb = load_workbook(BytesIO(xbytes))
        ws = wb.active
        # find row for excel row 64 via platform LinkedIn - Zakelijk and no URL / interne
        long_insights = 0
        for r in range(2, ws.max_row + 1):
            insight = str(ws.cell(r, 19).value or "")
            if len(insight) > 80:
                long_insights += 1
        report["export_long_insights"] = long_insights
        report["strategy"] = {
            "missing": get_strategy(conn, client_id)["missing_required"],
            "answered": sorted(
                k
                for k, v in get_strategy(conn, client_id)["start_answers"].items()
                if str(v).strip()
            ),
        }
        out = ROOT / "data" / "imports" / "redrock" / "_audit_report.json"
        # issues may be large
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("AUDIT_SUMMARY", json.dumps({
            "excel_rows": report["excel_rows"],
            "import_links": report["import_links"],
            "issue_count": len(report["issues"]),
            "issue_types": sorted({i["type"] for i in report["issues"]}),
            "row64_present": report["row64_present"],
            "missing_formats": report["missing_formats"],
            "bogus": report["bogus_format_names"],
            "export_rows": report["export_rows"],
            "reimport_added": result2["applied"]["added"],
        }, ensure_ascii=False))
        if report["issues"]:
            print("FIRST_ISSUES", json.dumps(report["issues"][:15], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
