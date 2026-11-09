"""Detail Score/Beoordeling columns and thresholds from the Excel."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook

XLSX = Path(r"c:\Users\SandrinePrumpelerRed\Downloads\RRO_Social strategie overzicht_2026.xlsx")
OUT = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\imports\redrock\_excel_score_detail.json")


def main() -> None:
    wb = load_workbook(XLSX, data_only=False)
    wbv = load_workbook(XLSX, data_only=True)
    ws = wb["Post performance"]
    wsv = wbv["Post performance"]

    headers = {}
    for c in range(1, 30):
        v = ws.cell(1, c).value
        if v:
            headers[c] = str(v).strip()
    print("HEADERS", headers)

    # Beoordeling formulas / values
    beoord_c = next(c for c, n in headers.items() if n == "Beoordeling")
    score_c = next(c for c, n in headers.items() if n == "Score")
    beoord_forms = set()
    beoord_vals = []
    for r in range(2, 30):
        cell = ws.cell(r, beoord_c)
        if isinstance(cell.value, str) and cell.value.startswith("="):
            beoord_forms.add(cell.value)
        beoord_vals.append(
            {
                "row": r,
                "formula_or_text": cell.value,
                "cached": wsv.cell(r, beoord_c).value,
                "score_cached": wsv.cell(r, score_c).value,
                "fill": getattr(getattr(cell.fill, "fgColor", None), "rgb", None),
                "platform": wsv.cell(r, 3).value if 3 in headers or True else None,
            }
        )
    # also check conditional formatting
    cf_rules = []
    try:
        for cf in ws.conditional_formatting._cf_rules.items():
            cf_rules.append(str(cf)[:500])
    except Exception as exc:
        cf_rules.append(f"err:{exc}")

    # sample full row metrics for formula verification
    samples = []
    for r in [2, 3, 5, 10, 20]:
        row = {"row": r}
        for c, name in headers.items():
            row[name] = {
                "raw": ws.cell(r, c).value,
                "cached": wsv.cell(r, c).value,
            }
        samples.append(row)

    # Formats sheet detail
    fmt = {}
    if "Formats" in wb.sheetnames:
        fws = wb["Formats"]
        fheaders = [fws.cell(1, c).value for c in range(1, 15)]
        rows = []
        for r in range(2, min(fws.max_row or 2, 40)):
            code = fws.cell(r, 1).value
            if not code:
                continue
            rows.append(
                {
                    "code": code,
                    "cols": [fws.cell(r, c).value for c in range(1, 10)],
                }
            )
        fmt = {"headers": fheaders, "rows_sample": rows[:12], "count": len(rows)}

    # Maandtab content labels
    maand = {}
    for name in wb.sheetnames:
        if any(x in name for x in ("2026", "Voorbeeld", "maand", "Maand")) and name not in {
            "Post performance"
        }:
            mws = wb[name]
            # search for key labels
            labels = []
            for r in range(1, min(80, (mws.max_row or 1) + 1)):
                for c in range(1, min(6, (mws.max_column or 1) + 1)):
                    v = mws.cell(r, c).value
                    if isinstance(v, str) and any(
                        k in v.lower()
                        for k in (
                            "analyse vorige",
                            "bijzonderheden",
                            "voorstel credit",
                            "story",
                            "prestatie",
                            "planning",
                            "doel",
                            "format",
                        )
                    ):
                        labels.append({"r": r, "c": c, "text": v.strip()[:120]})
            maand[name] = {
                "state": getattr(mws, "sheet_state", "visible"),
                "labels": labels[:20],
            }

    out = {
        "headers": headers,
        "beoordeling_formulas": sorted(beoord_forms),
        "beoordeling_samples": beoord_vals[:15],
        "conditional_formatting": cf_rules[:20],
        "row_samples": samples,
        "formats": fmt,
        "maand_labels": maand,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", OUT)
    print("beoordeling formulas", beoord_forms)
    print("score/beoord sample", beoord_vals[:5])


if __name__ == "__main__":
    main()
