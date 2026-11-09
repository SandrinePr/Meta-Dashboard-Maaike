"""Extract Feedback TOV + maandcontext from the strategy workbook (no invented text)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

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

_SKIP_SHEETS = {
    "post performance",
    "formats",
    "feedback tov",
    "maaike",
    "test performance tabblad",
    "voorbeeld maand",
}


def extract_workbook_context(wb, wb_values=None, *, source_file: str) -> dict[str, Any]:
    feedback = _extract_feedback_tov(wb["Feedback TOV"] if "Feedback TOV" in wb.sheetnames else None)
    months = []
    for name in wb.sheetnames:
        if name.strip().lower() in _SKIP_SHEETS:
            continue
        period = _parse_month_sheet_name(name)
        if period is None and not _looks_like_month_sheet(wb[name]):
            continue
        ws = wb[name]
        sheet = _extract_month_sheet(ws, sheet_name=name, period=period)
        if sheet is not None:
            months.append(sheet)
    return {
        "source_file": source_file,
        "feedback_tov": feedback,
        "month_sheets": months,
        "extracted_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def store_analysis_context_for_client(
    conn,
    client_id: int,
    context: dict[str, Any],
    *,
    source_file: str,
) -> None:
    """Merge Excel analysis context into client strategy_fields (fill-empty only for TOV)."""
    from maaike.strategy import get_strategy, save_strategy

    current = get_strategy(conn, client_id)
    fields = dict(current.get("strategy_fields") or {})
    feedback = (context.get("feedback_tov") or {}).get("text") or ""
    if feedback and not str(fields.get("feedback_tov") or "").strip():
        fields["feedback_tov"] = feedback
    fields["excel_month_contexts"] = context.get("month_sheets") or []
    fields["excel_analysis_context_meta"] = {
        "source_file": source_file,
        "extracted_at": context.get("extracted_at"),
        "feedback_tov_present": bool(feedback),
        "month_sheet_count": len(context.get("month_sheets") or []),
    }
    save_strategy(
        conn,
        client_id,
        account_info=current.get("account_info"),
        start_answers=current.get("start_answers"),
        strategy_fields=fields,
        source_notes=current.get("source_notes"),
        mark_complete=False,
    )


def resolve_month_context_for_period(
    context_months: list[dict[str, Any]],
    *,
    planning_year: int | None,
    planning_month: int | None,
    analysis_year: int | None,
    analysis_month: int | None,
    client_name: str | None = None,
) -> dict[str, Any]:
    """Pick maandcontext by period linkage (planning tab / content), not tab name alone."""
    if not context_months:
        return {
            "present": False,
            "match": None,
            "missing_reason": "Geen Excel-maandbladen opgeslagen voor deze klant.",
            "candidates_checked": 0,
        }
    scored: list[tuple[int, dict[str, Any]]] = []
    for sheet in context_months:
        score = 0
        py = sheet.get("planning_year")
        pm = sheet.get("planning_month")
        ay = sheet.get("analysis_year")
        am = sheet.get("analysis_month")
        if planning_year and planning_month and py == planning_year and pm == planning_month:
            score += 100
        if analysis_year and analysis_month and ay == analysis_year and am == analysis_month:
            # Content "Maand" under Analyse vorige planning (e.g. November→September)
            score += 80
        elif analysis_year and analysis_month and ay == analysis_year and am != analysis_month:
            score -= 20  # same year wrong month — prefer exact content link
        client_cell = (sheet.get("client_label") or "").strip().lower()
        if client_name and client_cell:
            cn = client_name.strip().lower()
            if cn in client_cell or client_cell in cn:
                score += 15
            else:
                score -= 50  # wrong client isolation
        if sheet.get("analyse_vorige_planning") or sheet.get("bijzonderheden"):
            score += 5
        if sheet.get("period_link_source") == "excel_content_maand_cel":
            score += 10
        scored.append((score, sheet))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score < 50:
        return {
            "present": False,
            "match": None,
            "missing_reason": (
                "Geen maandblad met voldoende periodekoppeling gevonden "
                f"(beste score {best_score} op '{best.get('sheet_name')}')."
            ),
            "candidates_checked": len(context_months),
            "best_candidate": {
                "sheet_name": best.get("sheet_name"),
                "planning_year": best.get("planning_year"),
                "planning_month": best.get("planning_month"),
                "score": best_score,
            },
        }
    return {
        "present": True,
        "match": best,
        "missing_reason": None,
        "candidates_checked": len(context_months),
        "match_score": best_score,
    }


def build_client_analysis_context(
    conn,
    client_id: int,
    *,
    analysis_year: int,
    analysis_month: int,
    planning_year: int | None = None,
    planning_month: int | None = None,
) -> dict[str, Any]:
    """Assemble analysis context for execute/inspect from client-scoped strategy storage."""
    from maaike.strategy import get_strategy

    client = conn.execute("SELECT id, name FROM clients WHERE id = ?", (client_id,)).fetchone()
    if client is None:
        raise ValueError("Klant niet gevonden.")
    strategy = get_strategy(conn, client_id)
    fields = strategy.get("strategy_fields") or {}
    answers = strategy.get("start_answers") or {}
    feedback = str(fields.get("feedback_tov") or "").strip()
    months = fields.get("excel_month_contexts") or []
    if isinstance(months, str):
        try:
            months = json.loads(months)
        except json.JSONDecodeError:
            months = []
    plan_y = planning_year or analysis_year
    plan_m = planning_month
    if plan_m is None:
        # Default: planning = month after analysis period
        if analysis_month == 12:
            plan_y, plan_m = analysis_year + 1, 1
        else:
            plan_y, plan_m = analysis_year, analysis_month + 1
    month_match = resolve_month_context_for_period(
        list(months),
        planning_year=plan_y,
        planning_month=plan_m,
        analysis_year=analysis_year,
        analysis_month=analysis_month,
        client_name=str(client["name"]),
    )
    matched = month_match.get("match") or {}
    selection_ok = True
    selection_reason = None
    if matched:
        sheet_plan = (matched.get("planning_year"), matched.get("planning_month"))
        sheet_analysis = (matched.get("analysis_year"), matched.get("analysis_month"))
        wanted_plan = (plan_y, plan_m)
        wanted_analysis = (analysis_year, analysis_month)
        if sheet_plan == wanted_plan and sheet_analysis == wanted_analysis:
            label = matched.get("analysis_month_label") or f"{analysis_year}-{analysis_month:02d}"
            selection_reason = (
                f"Tab '{matched.get('sheet_name')}' is het planningsblad voor "
                f"{plan_y}-{plan_m:02d}. Inhoud 'Analyse vorige planning → Maand' = "
                f"{label!r} koppelt aan analyseperiode {analysis_year}-{analysis_month:02d} "
                f"(bron: {matched.get('period_link_source') or 'excel'})."
            )
        elif sheet_plan == wanted_plan:
            selection_reason = (
                f"Tab '{matched.get('sheet_name')}' gekozen op planningsmaand "
                f"{plan_y}-{plan_m:02d}, maar inhouds-Maand "
                f"{matched.get('analysis_month_label')!r} komt niet overeen met "
                f"analyseperiode {analysis_year}-{analysis_month:02d}."
            )
            selection_ok = False
        elif sheet_analysis == wanted_analysis:
            selection_reason = (
                f"Tab '{matched.get('sheet_name')}' heeft wel analyse-Maand "
                f"{matched.get('analysis_month_label')!r}, maar planning "
                f"{sheet_plan[0]}-{int(sheet_plan[1] or 0):02d} ≠ gevraagd "
                f"{plan_y}-{plan_m:02d}."
            )
            selection_ok = False
        else:
            selection_ok = False
            sp_y, sp_m = sheet_plan[0], sheet_plan[1]
            sa_y, sa_m = sheet_analysis[0], sheet_analysis[1]
            plan_label = f"{sp_y}-{sp_m:02d}" if sp_y and sp_m else "onbekend"
            analysis_label = f"{sa_y}-{sa_m:02d}" if sa_y and sa_m else "onbekend"
            selection_reason = (
                f"Geselecteerd blad '{matched.get('sheet_name')}' "
                f"(plan {plan_label}, analyse {analysis_label}) "
                f"past niet bij gevraagde plan {plan_y}-{plan_m:02d} / "
                f"analyse {analysis_year}-{analysis_month:02d}."
            )
    elif month_match.get("best_candidate"):
        selection_ok = False
        selection_reason = month_match.get("missing_reason")
    tov = str(answers.get("tone_of_voice") or fields.get("tone_of_voice") or "").strip()
    return {
        "client_id": client_id,
        "client_name": client["name"],
        "analysis_period": {
            "year": analysis_year,
            "month": analysis_month,
            "label": f"{analysis_year}-{analysis_month:02d}",
            "role": "analyseperiode",
        },
        "planning_period": {
            "year": plan_y,
            "month": plan_m,
            "label": f"{plan_y}-{plan_m:02d}",
            "role": "planningsmaand",
            "derived_from_analysis_default": planning_month is None,
        },
        "feedback_tov": {
            "present": bool(feedback),
            "text": feedback or None,
            "source": "strategy_fields.feedback_tov" if feedback else None,
            "missing_reason": None if feedback else "Feedback TOV ontbreekt voor deze klant.",
        },
        "tone_of_voice": {
            "present": bool(tov),
            "text": tov or None,
            "source": "start_answers.tone_of_voice" if answers.get("tone_of_voice") else (
                "strategy_fields.tone_of_voice" if fields.get("tone_of_voice") else None
            ),
            "missing_reason": None if tov else "Tone of voice ontbreekt.",
        },
        "month_context": {
            "present": bool(month_match.get("present")) and selection_ok,
            "sheet_name": matched.get("sheet_name") if selection_ok else None,
            "client_label": matched.get("client_label") if selection_ok else None,
            "analysis_month_label": matched.get("analysis_month_label") if matched else None,
            "planning_credit_month_label": matched.get("planning_credit_month_label") if matched else None,
            "period_link_source": matched.get("period_link_source") if matched else None,
            "sheet_analysis_year": matched.get("analysis_year") if matched else None,
            "sheet_analysis_month": matched.get("analysis_month") if matched else None,
            "sheet_planning_year": matched.get("planning_year") if matched else None,
            "sheet_planning_month": matched.get("planning_month") if matched else None,
            "analyse_vorige_planning": matched.get("analyse_vorige_planning") if selection_ok else None,
            "bijzonderheden": matched.get("bijzonderheden") if selection_ok else None,
            "stories": (matched.get("stories") or []) if selection_ok else [],
            "source": (
                f"excel_month_contexts[{matched.get('sheet_name')}]"
                if selection_ok and matched
                else None
            ),
            "selection_ok": selection_ok,
            "selection_reason": selection_reason,
            "missing_reason": None
            if (month_match.get("present") and selection_ok)
            else (selection_reason or month_match.get("missing_reason")),
            "match_meta": {
                k: month_match.get(k)
                for k in ("match_score", "candidates_checked", "best_candidate")
                if k in month_match
            },
        },
        "strategy_answers_present": bool(answers),
        "targets_count": len(strategy.get("targets") or []),
        "channel_rules_keys": [
            k for k in answers.keys() if any(x in k.lower() for x in ("platform", "kanaal", "linkedin", "instagram"))
        ],
    }


def _extract_feedback_tov(ws: Worksheet | None) -> dict[str, Any]:
    if ws is None:
        return {"present": False, "text": None, "missing_reason": "Tabblad 'Feedback TOV' ontbreekt."}
    lines = []
    for row in ws.iter_rows(min_row=1, max_col=1, values_only=True):
        cell = row[0]
        if cell is None:
            continue
        text = str(cell).strip()
        if text:
            lines.append(text)
    body = "\n".join(lines).strip()
    return {
        "present": bool(body),
        "text": body or None,
        "line_count": len(lines),
        "missing_reason": None if body else "Feedback TOV-tabblad is leeg.",
    }


def _parse_month_sheet_name(name: str) -> dict[str, int] | None:
    text = (name or "").strip().lower()
    m = re.match(r"^([a-z]+)\s+(\d{4})$", text)
    if not m:
        return None
    month = MONTH_NAMES_NL.get(m.group(1))
    if not month:
        return None
    return {"year": int(m.group(2)), "month": month}


def _looks_like_month_sheet(ws: Worksheet) -> bool:
    sample = []
    for r in range(1, min(25, (ws.max_row or 1) + 1)):
        for c in range(1, min(6, (ws.max_column or 1) + 1)):
            val = ws.cell(r, c).value
            if val is not None:
                sample.append(str(val).lower())
    joined = " | ".join(sample)
    return "analyse vorige planning" in joined or "bijzonderheden" in joined


def _parse_content_month_label(raw: str | None, *, fallback_year: int | None) -> dict[str, Any] | None:
    """Parse Excel 'Maand' cell under Analyse/Bijzonderheden/Planning (not tab name alone)."""
    if not raw:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"xxx", "n.v.t.", "nvt", "n.v.t"}:
        return None
    # Exact month name, optional year: "September", "September 2026"
    m = re.match(r"^([A-Za-zÀ-ÿ]+)\s*(\d{4})?$", text, re.I)
    if m:
        month = MONTH_NAMES_NL.get(m.group(1).lower())
        if month:
            year = int(m.group(2)) if m.group(2) else fallback_year
            return {
                "year": year,
                "month": month,
                "label": text,
                "kind": "calendar_month",
            }
    # Range like "21 sep t/m 20 okt" — keep label; use first month if recognizable
    range_m = re.search(
        r"\b(jan|feb|mrt|apr|mei|jun|jul|aug|sep|okt|nov|dec)[a-z]*\b",
        text.lower(),
    )
    alias = {
        "jan": 1,
        "feb": 2,
        "mrt": 3,
        "apr": 4,
        "mei": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "okt": 10,
        "nov": 11,
        "dec": 12,
    }
    if range_m:
        month = alias.get(range_m.group(1)[:3])
        return {
            "year": fallback_year,
            "month": month,
            "label": text,
            "kind": "range_or_custom",
        }
    return {"year": fallback_year, "month": None, "label": text, "kind": "unparsed"}


def _extract_section_month_labels(ws: Worksheet) -> dict[str, str | None]:
    """Read the first 'Maand' value under Analyse / Bijzonderheden / Voorstel credit."""
    analyse_m = bijz_m = plan_m = None
    mode = None
    for r in range(1, (ws.max_row or 0) + 1):
        a = str(ws.cell(r, 1).value or "").strip().lower()
        b = str(ws.cell(r, 2).value or "").strip()
        if "analyse vorige" in a:
            mode = "analyse"
            continue
        if "bijzonderheden" in a:
            mode = "bijz"
            continue
        if "voorstel credit" in a:
            mode = "plan"
            continue
        if a == "maand" and b:
            if mode == "analyse" and not analyse_m:
                analyse_m = b
            elif mode == "bijz" and not bijz_m:
                bijz_m = b
            elif mode == "plan" and not plan_m:
                plan_m = b
    return {"analyse": analyse_m, "bijzonderheden": bijz_m, "planning": plan_m}


def _extract_month_sheet(
    ws: Worksheet,
    *,
    sheet_name: str,
    period: dict[str, int] | None,
) -> dict[str, Any] | None:
    cells: list[tuple[int, int, str]] = []
    for r in range(1, (ws.max_row or 0) + 1):
        for c in range(1, min((ws.max_column or 0) + 1, 12)):
            val = ws.cell(r, c).value
            if val is None:
                continue
            text = str(val).strip()
            if text:
                cells.append((r, c, text))
    if not cells:
        return None
    client_label = None
    for r, c, text in cells[:20]:
        if text.lower() in {"klant", "client"}:
            right = ws.cell(r, c + 1).value
            if right:
                client_label = str(right).strip()
                break
        if "red rock" in text.lower():
            client_label = text
            break
    analyse = _section_after_marker(cells, "analyse vorige planning")
    bijzonder = _section_after_marker(cells, "bijzonderheden")
    stories = _extract_story_mentions(cells)
    planning_year = period["year"] if period else None
    planning_month = period["month"] if period else None
    labels = _extract_section_month_labels(ws)
    # Prefer content "Maand" under Analyse — Excel does NOT always use planning-1.
    content_analysis = _parse_content_month_label(
        labels.get("analyse"), fallback_year=planning_year
    )
    content_bijz = _parse_content_month_label(
        labels.get("bijzonderheden"), fallback_year=planning_year
    )
    content_plan = _parse_content_month_label(
        labels.get("planning"), fallback_year=planning_year
    )
    if content_plan and content_plan.get("month") and content_plan.get("year"):
        # Credit-block month can confirm planning; tab name remains primary.
        if planning_month is None:
            planning_year = content_plan.get("year")
            planning_month = content_plan.get("month")
    analysis_year = content_analysis.get("year") if content_analysis else None
    analysis_month = content_analysis.get("month") if content_analysis else None
    analysis_label = content_analysis.get("label") if content_analysis else None
    if analysis_month is None and planning_year and planning_month:
        # Fallback only when content month missing
        if planning_month == 1:
            analysis_year, analysis_month = planning_year - 1, 12
        else:
            analysis_year, analysis_month = planning_year, planning_month - 1
        analysis_label = f"(afgeleid planning-1; geen Maand-cel)"
    return {
        "sheet_name": sheet_name,
        "client_label": client_label,
        "planning_year": planning_year,
        "planning_month": planning_month,
        "analysis_year": analysis_year,
        "analysis_month": analysis_month,
        "analysis_month_label": analysis_label,
        "bijzonderheden_month_label": (content_bijz or {}).get("label"),
        "planning_credit_month_label": (content_plan or {}).get("label") or labels.get("planning"),
        "analyse_vorige_planning": analyse or None,
        "bijzonderheden": bijzonder or None,
        "stories": stories,
        "has_analyse": bool(analyse),
        "has_bijzonderheden": bool(bijzonder),
        "period_link_source": "excel_content_maand_cel"
        if content_analysis and content_analysis.get("month")
        else "fallback_planning_minus_one",
    }


def _section_after_marker(cells: list[tuple[int, int, str]], marker: str) -> str:
    marker_l = marker.lower()
    start_row = None
    for r, _c, text in cells:
        if marker_l in text.lower():
            start_row = r
            break
    if start_row is None:
        return ""
    # Collect following lines until next ALL-CAPS-ish header or empty gap of 4+ rows
    collected = []
    last_row = start_row
    stop_markers = (
        "voorstel",
        "contentpijlers",
        "planning",
        "credits",
        "story",
        "stories",
        "bijzonderheden",
        "analyse vorige planning",
    )
    for r, _c, text in cells:
        if r <= start_row:
            continue
        if r - last_row > 6 and collected:
            break
        lower = text.lower().strip()
        if any(lower.startswith(m) for m in stop_markers) and marker_l not in lower:
            # allow bijzonderheden section only when seeking analyse, and vice versa
            if lower != marker_l:
                break
        if len(text) > 2:
            collected.append(text)
            last_row = r
        if len(collected) >= 40:
            break
    return "\n".join(collected).strip()


def _extract_story_mentions(cells: list[tuple[int, int, str]]) -> list[dict[str, str]]:
    out = []
    for _r, _c, text in cells:
        lower = text.lower()
        if "story" in lower or "stories" in lower:
            if len(text) > 3:
                out.append({"text": text[:500]})
    return out[:20]
