"""Read-only audit of RRO Social strategie Excel vs Bruine Beer. No AI, no live writes."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook

XLSX = Path(r"c:\Users\SandrinePrumpelerRed\Downloads\RRO_Social strategie overzicht_2026.xlsx")
OUT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\imports\redrock\_excel_audit_2026.json")
DB_CANDIDATES = [
    Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_copy.db"),
    Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock.db"),
]


def sheet_summary(wb) -> list[dict]:
    rows = []
    for name in wb.sheetnames:
        ws = wb[name]
        state = getattr(ws, "sheet_state", "visible") or "visible"
        # sample headers from first non-empty row
        header = None
        for r in range(1, min(20, (ws.max_row or 1) + 1)):
            vals = [ws.cell(r, c).value for c in range(1, min(25, (ws.max_column or 1) + 1))]
            if any(v is not None and str(v).strip() for v in vals):
                header = [str(v).strip() if v is not None else "" for v in vals]
                break
        # count non-empty rows roughly
        nonempty = 0
        for r in range(1, min((ws.max_row or 0) + 1, 500)):
            if any(
                ws.cell(r, c).value is not None and str(ws.cell(r, c).value).strip()
                for c in range(1, min(8, (ws.max_column or 1) + 1))
            ):
                nonempty += 1
        rows.append(
            {
                "name": name,
                "state": state,
                "max_row": ws.max_row,
                "max_col": ws.max_column,
                "nonempty_rows_sample": nonempty,
                "header_sample": header,
            }
        )
    return rows


def find_score_formulas(wb) -> dict:
    """Extract Score / Beoordeling formulas from Post performance and Test Performance."""
    found: dict[str, list] = {}
    targets = ["Post performance", "Test Performance tabblad", "Maaike", "Formats"]
    for name in targets:
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        # map header row
        header_row = None
        headers = {}
        for r in range(1, 15):
            for c in range(1, min(40, (ws.max_column or 1) + 1)):
                v = ws.cell(r, c).value
                if isinstance(v, str) and v.strip():
                    headers.setdefault(r, {})[c] = v.strip()
            if headers.get(r) and any(
                k.lower() in {"score", "beoordeling"} for k in (x.lower() for x in headers[r].values())
            ):
                header_row = r
                break
        if not header_row:
            found[name] = {"error": "no header with Score/Beoordeling"}
            continue
        col_map = {v.lower(): c for c, v in headers[header_row].items()}
        score_col = col_map.get("score")
        beoord_col = col_map.get("beoordeling")
        samples = []
        # scan first ~40 data rows for formulas
        for r in range(header_row + 1, min(header_row + 80, (ws.max_row or 0) + 1)):
            entry = {"row": r}
            if score_col:
                cell = ws.cell(r, score_col)
                if cell.value is not None:
                    entry["score_value"] = cell.value
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        entry["score_formula"] = cell.value
            if beoord_col:
                cell = ws.cell(r, beoord_col)
                if cell.value is not None:
                    entry["beoordeling_value"] = cell.value
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        entry["beoordeling_formula"] = cell.value
            # also check fill color for beoordeling
            if beoord_col:
                fill = ws.cell(r, beoord_col).fill
                fg = getattr(getattr(fill, "fgColor", None), "rgb", None)
                if fg:
                    entry["beoordeling_fill"] = fg
            if len(entry) > 1:
                samples.append(entry)
            if len(samples) >= 12:
                break
        # unique formulas
        score_forms = sorted({s["score_formula"] for s in samples if s.get("score_formula")})
        beoord_forms = sorted({s["beoordeling_formula"] for s in samples if s.get("beoordeling_formula")})
        found[name] = {
            "header_row": header_row,
            "columns": {k: col_map[k] for k in col_map if k in {"score", "beoordeling", "likes", "comments", "shares", "saves", "weergaven", "reach", "platform"}},
            "unique_score_formulas": score_forms,
            "unique_beoordeling_formulas": beoord_forms,
            "samples": samples[:8],
        }
    return found


def defined_names(wb) -> list[str]:
    out = []
    try:
        for dn in wb.defined_names.values():
            out.append(f"{dn.name}={dn.attr_text}")
    except Exception as exc:
        out.append(f"error:{exc}")
    return out[:80]


def post_performance_profile(wb) -> dict:
    ws = wb["Post performance"]
    # find header
    header_row = 1
    headers = {}
    for r in range(1, 10):
        vals = {}
        for c in range(1, (ws.max_column or 1) + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip():
                vals[c] = v.strip()
        if "Platform" in vals.values() and any("URL" in x for x in vals.values()):
            header_row = r
            headers = vals
            break
    inv = {v: c for c, v in headers.items()}
    platforms = Counter()
    maanden = Counter()
    beoord = Counter()
    with_url = 0
    without_url = 0
    with_insight = 0
    with_score = 0
    rows = 0
    score_col = inv.get("Score")
    url_col = inv.get("Post: URL van post")
    plat_col = inv.get("Platform")
    maand_col = inv.get("Maand")
    beoord_col = inv.get("Beoordeling")
    insight_col = inv.get("Insight: waarom gebeurde dit?")
    for r in range(header_row + 1, (ws.max_row or 0) + 1):
        plat = ws.cell(r, plat_col).value if plat_col else None
        if plat is None or not str(plat).strip():
            continue
        rows += 1
        platforms[str(plat).strip()] += 1
        if maand_col:
            maanden[str(ws.cell(r, maand_col).value or "").strip() or "(leeg)"] += 1
        url = ws.cell(r, url_col).value if url_col else None
        if url and str(url).strip():
            with_url += 1
        else:
            without_url += 1
        b = ws.cell(r, beoord_col).value if beoord_col else None
        if isinstance(b, str) and b.startswith("="):
            beoord["(formule)"] += 1
        else:
            beoord[str(b or "").strip() or "(leeg)"] += 1
        ins = ws.cell(r, insight_col).value if insight_col else None
        if ins and str(ins).strip():
            with_insight += 1
        if score_col and ws.cell(r, score_col).value not in (None, ""):
            with_score += 1
    return {
        "header_row": header_row,
        "columns": list(inv.keys()),
        "data_rows": rows,
        "platforms": dict(platforms),
        "maanden": dict(maanden),
        "beoordeling": dict(beoord),
        "with_url": with_url,
        "without_url": without_url,
        "with_insight": with_insight,
        "with_score_or_formula": with_score,
    }


def compare_other_sheets(wb) -> dict:
    """Rough URL overlap between Post performance and Maaike / Test Performance."""
    def urls_from(sheet_name: str) -> set[str]:
        if sheet_name not in wb.sheetnames:
            return set()
        ws = wb[sheet_name]
        found = set()
        url_col = None
        header_row = None
        for r in range(1, 12):
            for c in range(1, min(30, (ws.max_column or 1) + 1)):
                v = ws.cell(r, c).value
                if isinstance(v, str) and "URL" in v:
                    url_col = c
                    header_row = r
                    break
            if url_col:
                break
        if not url_col:
            return set()
        for r in range(header_row + 1, min((ws.max_row or 0) + 1, 600)):
            v = ws.cell(r, url_col).value
            if v and str(v).strip().startswith("http"):
                found.add(str(v).strip().split("?")[0].rstrip("/").lower())
        return found

    pp = urls_from("Post performance")
    maaike = urls_from("Maaike")
    test = urls_from("Test Performance tabblad")
    return {
        "post_performance_urls": len(pp),
        "maaike_urls": len(maaike),
        "test_performance_urls": len(test),
        "overlap_pp_maaike": len(pp & maaike),
        "only_maaike": len(maaike - pp),
        "only_pp_vs_maaike": len(pp - maaike),
        "overlap_pp_test": len(pp & test),
        "only_test": len(test - pp),
    }


def maand_sheet_probe(wb) -> list[dict]:
    out = []
    for name in wb.sheetnames:
        low = name.lower()
        if name in {"Voorbeeld maand"} or re.search(
            r"(januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december|\d{4})",
            low,
        ):
            if name in {"Post performance", "Formats", "Feedback TOV", "Maaike", "Test Performance tabblad"}:
                continue
            ws = wb[name]
            # collect first 15 non-empty cell texts as content probe
            texts = []
            for r in range(1, min(40, (ws.max_row or 1) + 1)):
                for c in range(1, min(8, (ws.max_column or 1) + 1)):
                    v = ws.cell(r, c).value
                    if isinstance(v, str) and len(v.strip()) > 8:
                        texts.append(v.strip()[:160])
                    if len(texts) >= 12:
                        break
                if len(texts) >= 12:
                    break
            markers = {
                "heeft_analyse": any("analyse" in t.lower() for t in texts),
                "heeft_planning": any("planning" in t.lower() or "plan" in t.lower() for t in texts),
                "heeft_bijzonderheden": any("bijzonder" in t.lower() for t in texts),
                "heeft_voorstel_credit": any("credit" in t.lower() for t in texts),
                "heeft_story": any("stor" in t.lower() for t in texts),
            }
            out.append(
                {
                    "name": name,
                    "state": getattr(ws, "sheet_state", "visible"),
                    "max_row": ws.max_row,
                    "markers": markers,
                    "text_samples": texts[:8],
                }
            )
    return out


def feedback_tov_probe(wb) -> dict:
    if "Feedback TOV" not in wb.sheetnames:
        return {"present": False}
    ws = wb["Feedback TOV"]
    texts = []
    for r in range(1, min(60, (ws.max_row or 1) + 1)):
        for c in range(1, min(6, (ws.max_column or 1) + 1)):
            v = ws.cell(r, c).value
            if isinstance(v, str) and len(v.strip()) > 15:
                texts.append(v.strip()[:200])
    return {"present": True, "max_row": ws.max_row, "samples": texts[:10], "sample_count": len(texts)}


def formats_probe(wb) -> dict:
    if "Formats" not in wb.sheetnames:
        return {"present": False}
    ws = wb["Formats"]
    # header
    header = {}
    for c in range(1, min(20, (ws.max_column or 1) + 1)):
        v = ws.cell(1, c).value
        if v:
            header[c] = str(v).strip()
    codes = []
    for r in range(2, min((ws.max_row or 1) + 1, 200)):
        code = ws.cell(r, 1).value
        if code and str(code).strip():
            codes.append(str(code).strip())
    return {"present": True, "headers": list(header.values()), "code_count": len(codes), "codes_sample": codes[:15]}


def db_compare(profile_cols: list[str]) -> dict:
    db_path = next((p for p in DB_CANDIDATES if p.exists()), None)
    if not db_path:
        return {"db": None}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    clients = [dict(r) for r in conn.execute("SELECT id, name FROM clients ORDER BY id")]
    red = next((c for c in clients if c["name"] == "Red Rock"), None)
    qa = next((c for c in clients if "QA" in c["name"]), None)
    out = {"db": str(db_path), "clients": clients}
    if red:
        cid = red["id"]
        posts = conn.execute(
            "SELECT COUNT(*) n FROM posts WHERE client_id=?", (cid,)
        ).fetchone()["n"]
        excel_posts = conn.execute(
            "SELECT COUNT(*) n FROM posts WHERE client_id=? AND source_origin='excel_import'",
            (cid,),
        ).fetchone()["n"]
        cols = {r[1] for r in conn.execute("PRAGMA table_info(post_assessments)").fetchall()}
        assessments = conn.execute(
            """
            SELECT source, rating_text, COUNT(*) n
            FROM post_assessments a
            JOIN posts p ON p.id=a.post_id
            WHERE p.client_id=?
            GROUP BY source, rating_text
            """,
            (cid,),
        ).fetchall()
        editorial = conn.execute(
            """
            SELECT
              SUM(CASE WHEN pe.format_id IS NOT NULL OR (pe.format_code_raw IS NOT NULL AND pe.format_code_raw!='') THEN 1 ELSE 0 END) formats,
              SUM(CASE WHEN pe.pillar_id IS NOT NULL THEN 1 ELSE 0 END) pillars,
              SUM(CASE WHEN pe.hook IS NOT NULL AND pe.hook!='' THEN 1 ELSE 0 END) hooks
            FROM post_editorial pe
            JOIN posts p ON p.id=pe.post_id
            WHERE p.client_id=?
            """,
            (cid,),
        ).fetchone()
        rating_settings = None
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='client_rating_settings'"
        ).fetchone()
        if exists:
            rating_settings = conn.execute(
                "SELECT * FROM client_rating_settings WHERE client_id=? LIMIT 1",
                (cid,),
            ).fetchone()
        out["red_rock"] = {
            "client_id": cid,
            "posts": posts,
            "excel_origin_posts": excel_posts,
            "assessments_by_source_rating": [dict(r) for r in assessments],
            "assessment_columns": sorted(cols),
            "editorial": dict(editorial) if editorial else None,
            "rating_settings": dict(rating_settings) if rating_settings else None,
        }
    # strategy tables (names vary)
    if red:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        out["strategy_tables_present"] = sorted(
            t for t in tables if "strateg" in t.lower() or "start_answer" in t.lower()
        )
        for t in out["strategy_tables_present"]:
            try:
                n = conn.execute(f"SELECT COUNT(*) n FROM {t} WHERE client_id=?", (red["id"],)).fetchone()["n"]
                out.setdefault("strategy_counts", {})[t] = n
            except Exception as exc:
                out.setdefault("strategy_counts", {})[t] = f"err:{exc}"
    if red:
        fm = conn.execute(
            "SELECT COUNT(*) n FROM content_formats WHERE client_id=?",
            (red["id"],),
        ).fetchone()["n"]
        out["content_formats"] = fm
    conn.close()
    return out


def main() -> None:
    if not XLSX.exists():
        raise SystemExit(f"Excel not found: {XLSX}")
    # data_only=False to see formulas; also load values
    wb = load_workbook(XLSX, data_only=False, read_only=False)
    wb_vals = load_workbook(XLSX, data_only=True, read_only=False)

    result = {
        "source_file": str(XLSX),
        "sheets": sheet_summary(wb),
        "defined_names": defined_names(wb),
        "post_performance": post_performance_profile(wb),
        "formulas": find_score_formulas(wb),
        "formula_values_sample": find_score_formulas(wb_vals),
        "url_overlap": compare_other_sheets(wb),
        "maand_sheets": maand_sheet_probe(wb),
        "feedback_tov": feedback_tov_probe(wb),
        "formats": formats_probe(wb),
        "db_compare": db_compare([]),
    }

    # Also dump a few computed score values from data_only workbook
    if "Post performance" in wb_vals.sheetnames:
        ws = wb_vals["Post performance"]
        # locate Score col
        score_c = None
        beoord_c = None
        header_r = 1
        for r in range(1, 10):
            for c in range(1, 40):
                v = ws.cell(r, c).value
                if v == "Score":
                    score_c = c
                    header_r = r
                if v == "Beoordeling":
                    beoord_c = c
                    header_r = r
        samples = []
        for r in range(header_r + 1, header_r + 25):
            if score_c or beoord_c:
                samples.append(
                    {
                        "row": r,
                        "score": ws.cell(r, score_c).value if score_c else None,
                        "beoordeling": ws.cell(r, beoord_c).value if beoord_c else None,
                        "platform": ws.cell(r, 1).value,
                    }
                )
        result["cached_score_values"] = samples

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("Wrote", OUT)
    print("sheets", len(result["sheets"]))
    print("PP rows", result["post_performance"]["data_rows"])
    print("formulas keys", list(result["formulas"].keys()))
    for k, v in result["formulas"].items():
        if isinstance(v, dict):
            print(k, "score_forms", v.get("unique_score_formulas"), "beoord", v.get("unique_beoordeling_formulas"))


if __name__ == "__main__":
    main()
