"""Import Red Rock strategy Excel into Maaike posts without inventing data."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from openpyxl import load_workbook

from maaike.repository import add_format, add_pillar, list_formats, list_pillars

SOURCE_SHEET = "Post performance"
FORMATS_SHEET = "Formats"
IMPORT_SOURCE = "excel_import"
ASSESSMENT_SOURCE = "excel_imported"
ASSESSMENT_LABEL = "Overgenomen uit Excel"

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "igsh",
    "igshid",
    "si",
    "feature",
}

_METRIC_MAP = {
    "Weergaven": "views",
    "Likes": "likes",
    "Comments": "comments",
    "Shares": "shares",
    "Saves": "saves",
    "Clicks": "clicks",
}

_PLATFORM_KEYS = {
    "instagram": "instagram",
    "linkedin": "linkedin",
    "linkedin - zakelijk": "linkedin_zakelijk",
}


@dataclass
class ParsedMetric:
    raw: Any
    kind: str  # empty | nvt | zero | number | invalid
    value: int | None = None


@dataclass
class ParsedRow:
    excel_row: int
    maand: str | None
    datum: date | None
    platform_label: str
    platform_key: str
    content_soort: str | None
    format_code: str | None
    permalink_raw: str | None
    permalink_norm: str | None
    external_id: str | None
    contentpijler: str | None
    hook: str | None
    metrics: dict[str, ParsedMetric]
    rating_text: str | None
    rating_fill: str | None
    insight: str | None
    action: str | None
    score_value: float | None = None
    rating_origin: str | None = None  # excel_cached_formula | excel_plain_text | missing_cached_value | empty
    score_origin: str | None = None
    rating_missing_reason: str | None = None
    score_missing_reason: str | None = None
    issues: list[str] = field(default_factory=list)


@dataclass
class MatchPlan:
    action: str  # add | link | skip | conflict
    post_id: int | None = None
    fields_to_fill: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    reason: str = ""


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    dest = backup_dir / f"maaike_redrock-before-excel-import-{stamp}.db"
    shutil.copy2(db_path, dest)
    return dest


def parse_workbook(path: Path) -> dict[str, Any]:
    wb = load_workbook(path, data_only=False)
    wb_values = load_workbook(path, data_only=True)
    if SOURCE_SHEET not in wb.sheetnames:
        raise ValueError(f"Tabblad '{SOURCE_SHEET}' ontbreekt in {path.name}.")
    rows = _parse_performance(wb[SOURCE_SHEET], wb_values[SOURCE_SHEET], source_file=path.name)
    formats = _parse_formats(wb[FORMATS_SHEET]) if FORMATS_SHEET in wb.sheetnames else []
    from maaike.excel_analysis_context import extract_workbook_context

    context = extract_workbook_context(wb, wb_values, source_file=path.name)
    return {
        "file_name": path.name,
        "sheet": SOURCE_SHEET,
        "rows": rows,
        "formats": formats,
        "sheet_names": list(wb.sheetnames),
        "analysis_context": context,
    }


def _classify_assessment_bucket(diff: dict[str, Any] | None) -> str:
    """Mutually exclusive assessment outcome for one linked Excel row."""
    if diff is None:
        return "skipped_no_assessment_payload"
    kind = diff.get("kind")
    if kind == "new":
        return "new"
    if kind == "missing_cache_no_existing":
        return "skipped_missing_cache_no_existing"
    old_r, new_r = diff.get("old_rating"), diff.get("new_rating")
    old_s, new_s = diff.get("old_score"), diff.get("new_score")
    rating_changed = (old_r or None) != (new_r or None)
    score_changed = False
    if new_s is not None and old_s is None:
        score_changed = True
    elif old_s is not None and new_s is None:
        score_changed = True
    elif old_s is not None and new_s is not None and abs(float(old_s) - float(new_s)) > 1e-9:
        score_changed = True
    if rating_changed:
        return "label_change"  # may also include score change
    if score_changed:
        return "score_only"
    # Effective values identical (including preserved-on-missing-cache)
    return "unchanged"


def build_preview(conn, client_id: int, parsed: dict[str, Any]) -> dict[str, Any]:
    _ensure_assessment_columns(conn)
    existing = _index_existing_posts(conn, client_id)
    plans = []
    counts = {"add": 0, "link": 0, "skip": 0, "conflict": 0}
    bucket_counts = {
        "new": 0,
        "label_change": 0,
        "score_only": 0,
        "unchanged": 0,
        "skipped_no_assessment_payload": 0,
        "skipped_missing_cache_no_existing": 0,
    }
    bucket_rows: dict[str, list[dict[str, Any]]] = {k: [] for k in bucket_counts}
    missing_cached_rows = 0
    missing_cached_linked = 0
    missing_cached_skipped_match = 0
    assessment_diffs: list[dict[str, Any]] = []
    unique_post_ids: set[int] = set()
    for row in parsed["rows"]:
        plan = _match_row(row, existing)
        counts[plan.action] = counts.get(plan.action, 0) + 1
        row_missing = bool(row.rating_missing_reason or row.score_missing_reason)
        if row_missing:
            missing_cached_rows += 1
            if plan.action == "link":
                missing_cached_linked += 1
            elif plan.action in {"skip", "conflict"}:
                missing_cached_skipped_match += 1
            elif plan.action == "add":
                missing_cached_linked += 0  # counted separately via add path if needed
        diff = None
        bucket = None
        if plan.post_id is not None:
            unique_post_ids.add(int(plan.post_id))
            diff = _assessment_diff(conn, plan.post_id, row)
            bucket = _classify_assessment_bucket(diff)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            entry = {
                "post_id": plan.post_id,
                "excel_row": row.excel_row,
                "bucket": bucket,
                "old_rating": (diff or {}).get("old_rating"),
                "new_rating": (diff or {}).get("new_rating"),
                "old_score": (diff or {}).get("old_score"),
                "new_score": (diff or {}).get("new_score"),
                "rating_missing_reason": row.rating_missing_reason,
                "score_missing_reason": row.score_missing_reason,
            }
            bucket_rows[bucket].append(entry)
            if bucket in {"new", "label_change", "score_only"}:
                assessment_diffs.append({**(diff or {}), "bucket": bucket})
        elif plan.action == "add":
            # Would create post + possibly assessment; treat preview bucket as new if payload
            if any([row.rating_text, row.score_value is not None, row.insight, row.action]):
                bucket = "new"
            elif row_missing:
                bucket = "skipped_missing_cache_no_existing"
            else:
                bucket = "skipped_no_assessment_payload"
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            bucket_rows[bucket].append(
                {
                    "post_id": None,
                    "excel_row": row.excel_row,
                    "bucket": bucket,
                    "old_rating": None,
                    "new_rating": row.rating_text,
                    "old_score": None,
                    "new_score": row.score_value,
                }
            )
        plans.append(
            {
                "excel_row": row.excel_row,
                "platform_label": row.platform_label,
                "platform_key": row.platform_key,
                "permalink": row.permalink_raw,
                "external_id": row.external_id,
                "datum": row.datum.isoformat() if row.datum else None,
                "maand": row.maand,
                "format_code": row.format_code,
                "content_soort": row.content_soort,
                "contentpijler": row.contentpijler,
                "rating_text": row.rating_text,
                "score_value": row.score_value,
                "rating_origin": row.rating_origin,
                "score_origin": row.score_origin,
                "rating_missing_reason": row.rating_missing_reason,
                "score_missing_reason": row.score_missing_reason,
                "has_insight": bool(row.insight),
                "has_action": bool(row.action),
                "issues": row.issues,
                "action": plan.action,
                "post_id": plan.post_id,
                "fields_to_fill": plan.fields_to_fill,
                "conflicts": plan.conflicts,
                "reason": plan.reason,
                "assessment_diff": diff,
                "assessment_bucket": bucket,
            }
        )

    linked = counts["link"]
    # Closed set over linked rows only (mutually exclusive)
    linked_buckets = {
        "new": 0,
        "label_change": 0,
        "score_only": 0,
        "unchanged": 0,
        "skipped": 0,
    }
    for row in plans:
        if row["action"] != "link":
            continue
        b = row.get("assessment_bucket")
        if b == "new":
            linked_buckets["new"] += 1
        elif b == "label_change":
            linked_buckets["label_change"] += 1
        elif b == "score_only":
            linked_buckets["score_only"] += 1
        elif b == "unchanged":
            linked_buckets["unchanged"] += 1
        else:
            linked_buckets["skipped"] += 1
    linked_sum = sum(linked_buckets.values())
    skipped_match = counts["skip"] + counts["conflict"]
    accounting = {
        "excel_rows_parsed": len(parsed["rows"]),
        "match": {
            "add": counts["add"],
            "link": counts["link"],
            "skip": counts["skip"],
            "conflict": counts["conflict"],
            "sum": counts["add"] + counts["link"] + counts["skip"] + counts["conflict"],
            "equals_excel_rows": (
                counts["add"] + counts["link"] + counts["skip"] + counts["conflict"]
            )
            == len(parsed["rows"]),
        },
        "linked_posts_unique": len(unique_post_ids),
        "linked_assessment_buckets_mutually_exclusive": {
            **linked_buckets,
            "sum": linked_sum,
            "equals_linked_rows": linked_sum == linked,
        },
        "missing_cached_formula_outcomes": {
            "excel_rows_with_missing_cache": missing_cached_rows,
            "of_which_linked": missing_cached_linked,
            "of_which_unmatched_or_skipped": missing_cached_skipped_match,
            "note": (
                "Dit is een Excel-rijtelling (Score/Beoordeling zonder cache), "
                "niet hetzelfde als assessment-wijzigingen. Veel ontbrekende uitkomsten "
                "zitten in overgeslagen/lege rijen buiten de 91 gekoppelde posts."
            ),
        },
        "definitions": {
            "excel_row": "Eén rij op tabblad Post performance",
            "linked_row": "Excel-rij gematcht op bestaande post (action=link)",
            "unique_post": "Unieke post_id onder linked rows",
            "assessment_record": "post_assessments-rij (excel_imported) die zou ontstaan/wijzigen",
            "new": "Geen bestaand excel_imported assessment; zou nieuw worden aangemaakt",
            "label_change": "Bestaand assessment; label wijzigt (score mag ook wijzigen)",
            "score_only": "Bestaand assessment; label gelijk, alleen score wijzigt",
            "unchanged": "Bestaand assessment; effectieve label+score blijven gelijk (incl. bewaren bij ontbrekende cache)",
            "skipped": "Gekoppelde rij zonder assessment-actie (geen payload of alleen missing-cache zonder bestaande waarden)",
        },
    }
    return {
        "file_name": parsed["file_name"],
        "sheet": parsed["sheet"],
        "row_count": len(parsed["rows"]),
        "format_count": len(parsed["formats"]),
        "counts": counts,
        "rows": plans,
        "formats": parsed["formats"],
        "assessment_diffs": assessment_diffs,
        "assessment_diff_count": len(assessment_diffs),
        "assessment_summary": {
            "new": linked_buckets["new"],
            "label_change": linked_buckets["label_change"],
            "score_only": linked_buckets["score_only"],
            "unchanged": linked_buckets["unchanged"],
            "skipped": linked_buckets["skipped"],
            "sum": linked_sum,
            "equals_linked_rows": linked_sum == linked,
            # legacy aliases
            "changed": linked_buckets["label_change"] + linked_buckets["score_only"],
        },
        "assessment_bucket_samples": {
            "label_change": bucket_rows["label_change"][:25],
            "score_only": bucket_rows["score_only"][:15],
            "new": bucket_rows["new"][:10],
            "unchanged": bucket_rows["unchanged"][:10],
            "skipped": (
                bucket_rows["skipped_no_assessment_payload"]
                + bucket_rows["skipped_missing_cache_no_existing"]
            )[:10],
        },
        "accounting": accounting,
        "missing_cached_formula_outcomes": missing_cached_rows,
        "rating_formula_live": False,
        "rating_formula_note": (
            "Live beoordelingsformule blijft uitgeschakeld; "
            "alleen opgeslagen Excel-cachewaarden (Score/Beoordeling) worden gelezen."
        ),
        "analysis_context_summary": {
            "feedback_tov_present": bool((parsed.get("analysis_context") or {}).get("feedback_tov")),
            "month_sheets": len((parsed.get("analysis_context") or {}).get("month_sheets") or []),
        },
        "update_assessments_required_to_apply_diffs": True,
        "note": (
            "Preview alleen. Bestaande Excel-beoordelingen worden pas bijgewerkt bij "
            "import met update_assessments=true. Ontbrekende Excel-formule-uitkomsten wissen "
            "geen bestaande geldige beoordeling/score. Menselijke formats/pijlers/hooks/insights/acties blijven behouden."
        ),
    }


def execute_import(
    conn,
    client_id: int,
    *,
    path: Path,
    parsed: dict[str, Any] | None = None,
    apply_conflicts: bool = False,
    update_assessments: bool = False,
    sync_analysis_context: bool = True,
) -> dict[str, Any]:
    parsed = parsed or parse_workbook(path)
    preview = build_preview(conn, client_id, parsed)
    now = datetime.now(tz=timezone.utc).isoformat()
    run_id = _start_run(conn, client_id, path, now)
    _ensure_formats_from_sheet(conn, client_id, parsed["formats"])
    format_ids = {item.name: item.item_id for item in list_formats(conn, client_id)}
    pillar_ids = {item.name: item.item_id for item in list_pillars(conn, client_id)}

    applied = {
        "added": 0,
        "linked": 0,
        "skipped": 0,
        "conflicts": 0,
        "filled_fields": 0,
        "assessments_inserted": 0,
        "assessments_updated": 0,
        "assessments_skipped_existing": 0,
    }
    for row, plan_info in zip(parsed["rows"], preview["rows"]):
        action = plan_info["action"]
        if action == "conflict" and not apply_conflicts:
            applied["conflicts"] += 1
            _log_row(conn, run_id, row, "conflict", plan_info.get("post_id"), plan_info)
            continue
        if action == "skip":
            applied["skipped"] += 1
            _log_row(conn, run_id, row, "skip", plan_info.get("post_id"), plan_info)
            continue
        post_id = plan_info.get("post_id")
        if action == "add" or post_id is None:
            post_id = _insert_excel_post(conn, client_id, row, now)
            applied["added"] += 1
            status = "added"
        else:
            applied["linked"] += 1
            status = "linked"
        filled = _apply_row_to_post(
            conn,
            client_id,
            post_id,
            row,
            format_ids=format_ids,
            pillar_ids=pillar_ids,
            imported_at=now,
            source_file=path.name,
            update_assessments=update_assessments,
            applied_counts=applied,
        )
        applied["filled_fields"] += filled
        _log_row(conn, run_id, row, status, post_id, {"fields_filled": filled, **plan_info})

    if sync_analysis_context and parsed.get("analysis_context"):
        from maaike.excel_analysis_context import store_analysis_context_for_client

        store_analysis_context_for_client(
            conn, client_id, parsed["analysis_context"], source_file=path.name
        )

    conn.execute(
        "UPDATE excel_import_runs SET finished_at = ?, summary_json = ? WHERE id = ?",
        (datetime.now(tz=timezone.utc).isoformat(), json.dumps(applied, ensure_ascii=False), run_id),
    )
    return {
        "run_id": run_id,
        "applied": applied,
        "preview_counts": preview["counts"],
        "assessment_diff_count": preview.get("assessment_diff_count", 0),
        "update_assessments": update_assessments,
        "rating_formula_live": False,
    }


def normalize_post_url(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    text = str(url).strip()
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text.rstrip("/")
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    # Drop tracking query params only; keep other query pairs.
    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(kept)
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


def internal_excel_identity(*, source_file: str, source_sheet: str, excel_row: int) -> str:
    """Stable identity for Excel rows without a post URL. Not a guessed permalink."""
    key = f"{source_file}|{source_sheet}|{excel_row}".encode()
    return "excelrow:" + hashlib.sha1(key).hexdigest()[:24]


def extract_external_id(platform_key: str, url: str | None) -> str | None:
    if not url:
        return None
    text = str(url)
    if platform_key == "instagram":
        m = re.search(r"instagram\.com/(?:p|reel|tv)/([^/?#]+)", text, re.I)
        if m:
            return m.group(1)
    if platform_key.startswith("linkedin"):
        m = re.search(r"activity[:\-](\d+)", text, re.I)
        if m:
            return m.group(1)
        norm = normalize_post_url(text)
        if norm:
            return "url:" + hashlib.sha1(norm.encode()).hexdigest()[:20]
    return None


def _parse_performance(ws, wsv, *, source_file: str) -> list[ParsedRow]:
    headers = {str(ws.cell(1, c).value or "").strip(): c for c in range(1, ws.max_column + 1)}
    required = [
        "Platform",
        "Post: URL van post",
        "Content format",
        "Content soort",
        "Contentpijler",
        "Beoordeling",
        "Insight: waarom gebeurde dit?",
        "Actie: wat doen we de volgende keer anders?",
    ]
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f"Kolommen ontbreken op '{SOURCE_SHEET}': {', '.join(missing)}")
    rows: list[ParsedRow] = []
    for r in range(2, ws.max_row + 1):
        values = {name: ws.cell(r, col).value for name, col in headers.items()}
        data_values = {name: wsv.cell(r, col).value for name, col in headers.items()}
        if not any(v is not None and str(v).strip() != "" for v in values.values()):
            continue
        platform_label = str(values.get("Platform") or "").strip()
        platform_key = _PLATFORM_KEYS.get(platform_label.lower())
        issues: list[str] = []
        if not platform_key:
            issues.append(f"Onbekend platformlabel: {platform_label!r}")
            platform_key = "unknown"
        permalink_raw = _as_text(values.get("Post: URL van post"))
        permalink_norm = normalize_post_url(permalink_raw)
        external_id = extract_external_id(platform_key, permalink_raw)
        if not external_id and permalink_norm:
            external_id = "url:" + hashlib.sha1(permalink_norm.encode()).hexdigest()[:20]
        if not external_id:
            # Keep the row; identity is file+sheet+row — never invent a post URL.
            external_id = internal_excel_identity(
                source_file=source_file,
                source_sheet=SOURCE_SHEET,
                excel_row=r,
            )
            issues.append("Geen post-URL; interne Excel-rijidentiteit gebruikt (geen Meta-match).")
        rating_cell = ws.cell(r, headers["Beoordeling"])
        rating_text, rating_origin, rating_missing = _resolve_cached_label(
            values.get("Beoordeling"),
            data_values.get("Beoordeling"),
            field_name="Beoordeling",
        )
        if rating_missing:
            issues.append(rating_missing)
        fill = None
        if rating_cell.fill and rating_cell.fill.fgColor and rating_cell.fill.fgColor.rgb:
            fill = str(rating_cell.fill.fgColor.rgb)
        if not rating_text and fill and not rating_missing:
            issues.append("Gekleurde beoordelingscel zonder tekst; kleur niet als Goed/Slecht gelezen.")
        score_value, score_origin, score_missing = _resolve_cached_score(
            values.get("Score") if "Score" in headers else None,
            data_values.get("Score") if "Score" in headers else None,
        )
        if score_missing:
            issues.append(score_missing)
        metrics = {}
        for excel_name, metric_name in _METRIC_MAP.items():
            metrics[metric_name] = _parse_metric(values.get(excel_name), data_values.get(excel_name))
            if metrics[metric_name].kind == "invalid":
                issues.append(f"Ongeldige waarde voor {excel_name}: {values.get(excel_name)!r}")
        format_code = _as_text(values.get("Content format"))
        content_soort = _as_text(values.get("Content soort"))
        rows.append(
            ParsedRow(
                excel_row=r,
                maand=_as_text(values.get("Maand")),
                datum=_as_date(values.get("Datum")),
                platform_label=platform_label,
                platform_key=platform_key,
                content_soort=content_soort,
                format_code=format_code,
                permalink_raw=permalink_raw,
                permalink_norm=permalink_norm,
                external_id=external_id,
                contentpijler=_as_text(values.get("Contentpijler")),
                hook=_as_text(values.get("Hook")),
                metrics=metrics,
                rating_text=rating_text,
                rating_fill=fill,
                insight=_as_text(values.get("Insight: waarom gebeurde dit?")),
                action=_as_text(values.get("Actie: wat doen we de volgende keer anders?")),
                score_value=score_value,
                rating_origin=rating_origin,
                score_origin=score_origin,
                rating_missing_reason=rating_missing,
                score_missing_reason=score_missing,
                issues=issues,
            )
        )
    return rows


_FORMAT_SECTION_HEADERS = {
    "carrousel / post formats",
    "reel formats",
    "linkedin formats zakelijk",
    "linkedin formats",
}


def _parse_formats(ws) -> list[dict[str, Any]]:
    out = []
    for r in range(2, ws.max_row + 1):
        code = _as_text(ws.cell(r, 1).value)
        if not code:
            continue
        if code.lower() in _FORMAT_SECTION_HEADERS:
            continue
        # Real format codes look like C01, R10, LZC01, LCR01 — skip prose headers
        if " " in code and not re.match(r"^[A-Z]{1,4}\d{2}$", code, re.I):
            continue
        out.append(
            {
                "code": code,
                "example_url": _as_text(ws.cell(r, 2).value),
                "explanation": _as_text(ws.cell(r, 3).value) or "",
                "status": _as_text(ws.cell(r, 4).value),
                "count": ws.cell(r, 5).value,
                "source_row": r,
            }
        )
    return out


def _parse_metric(raw: Any, resolved: Any) -> ParsedMetric:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return ParsedMetric(raw=raw, kind="empty", value=None)
    text = str(raw).strip()
    lowered = text.lower().replace(" ", "")
    if lowered in {"n.v.t.", "n.v.t", "nvt.", "nvt", "n/a"}:
        return ParsedMetric(raw=raw, kind="nvt", value=None)
    value = resolved if resolved is not None else raw
    if isinstance(value, bool):
        return ParsedMetric(raw=raw, kind="invalid", value=None)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = int(value)
        return ParsedMetric(raw=raw, kind="zero" if number == 0 else "number", value=number)
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return ParsedMetric(raw=raw, kind="zero" if number == 0 else "number", value=number)
    return ParsedMetric(raw=raw, kind="invalid", value=None)


def _index_existing_posts(conn, client_id: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id, platform, external_id, permalink, account_name, platform_label,
               views, likes, comments, shares, saves, clicks, last_synced_at
        FROM posts WHERE client_id = ?
        """,
        (client_id,),
    ).fetchall()
    by_ext: dict[tuple[str, str], Any] = {}
    by_url: dict[str, list[Any]] = {}
    for row in rows:
        by_ext[(str(row["platform"]), str(row["external_id"]))] = row
        norm = normalize_post_url(row["permalink"])
        if norm:
            by_url.setdefault(norm, []).append(row)
            # Instagram shortcode also indexed via path end
            m = re.search(r"/(?:p|reel|tv)/([^/]+)$", norm)
            if m:
                by_url.setdefault(f"ig:{m.group(1)}", []).append(row)
    by_import_row: dict[int, Any] = {}
    link_rows = conn.execute(
        """
        SELECT l.source_row, p.id, p.platform, p.external_id, p.permalink
        FROM post_import_links l
        JOIN posts p ON p.id = l.post_id
        WHERE p.client_id = ? AND l.source_sheet = ?
        """,
        (client_id, SOURCE_SHEET),
    ).fetchall()
    for link in link_rows:
        by_import_row[int(link["source_row"])] = link
    return {"by_ext": by_ext, "by_url": by_url, "by_import_row": by_import_row}


def _match_row(row: ParsedRow, existing: dict[str, Any]) -> MatchPlan:
    if row.platform_key == "unknown" or not row.external_id:
        return MatchPlan(action="skip", reason="Geen betrouwbare match-sleutel", conflicts=row.issues)
    # Prefer existing import-link match (reimport-safe, including URL-less rows)
    linked = existing.get("by_import_row", {}).get(row.excel_row)
    if linked is not None:
        return MatchPlan(
            action="link",
            post_id=int(linked["id"]),
            fields_to_fill=_fields_present(row),
            reason="Match op bestaande Excel-bronregel",
        )
    # Direct platform+external_id
    hit = existing["by_ext"].get((row.platform_key, row.external_id))
    if hit is None and row.external_id.startswith("excelrow:"):
        # URL-less Excel row: never Meta-match by date; add or link only via identity
        hit = existing["by_ext"].get((row.platform_key, row.external_id))
    if hit is None and row.platform_key == "instagram" and row.external_id and not row.external_id.startswith("excelrow:"):
        # Meta posts use platform 'instagram' and often media id, match via URL shortcode
        candidates = existing["by_url"].get(f"ig:{row.external_id}", [])
        if len(candidates) == 1:
            hit = candidates[0]
        elif len(candidates) > 1:
            return MatchPlan(
                action="conflict",
                reason="Meerdere bestaande Instagram-posts matchen dezelfde shortcode/URL",
                conflicts=["ambiguous_url_match"],
            )
    if hit is None and row.permalink_norm:
        candidates = existing["by_url"].get(row.permalink_norm, [])
        if len(candidates) == 1:
            hit = candidates[0]
        elif len(candidates) > 1:
            return MatchPlan(action="conflict", reason="Meerdere posts met dezelfde genormaliseerde URL")
    if hit is None:
        fields = _fields_present(row)
        return MatchPlan(action="add", fields_to_fill=fields, reason="Nieuwe post uit Excel")
    conflicts = []
    fields = []
    # Check editorial fills vs conflicts later in apply; preview lists fillable fields
    fields = _fields_present(row)
    if row.issues:
        # keep as link but surface issues
        pass
    return MatchPlan(
        action="link",
        post_id=int(hit["id"]),
        fields_to_fill=fields,
        conflicts=conflicts,
        reason="Match op platform/URL of post-ID",
    )


def _fields_present(row: ParsedRow) -> list[str]:
    fields = []
    if row.format_code:
        fields.append("format_code")
    if row.contentpijler:
        fields.append("contentpijler")
    if row.hook:
        fields.append("hook")
    if row.content_soort:
        fields.append("content_soort")
    if row.rating_text:
        fields.append("rating_excel")
    if row.score_value is not None:
        fields.append("score_excel")
    if row.rating_missing_reason or row.score_missing_reason:
        fields.append("cached_formula_missing")
    if row.insight:
        fields.append("insight_excel")
    if row.action:
        fields.append("action_excel")
    for name, metric in row.metrics.items():
        if metric.kind in {"zero", "number", "nvt"}:
            fields.append(f"metric:{name}")
    return fields


def _ensure_assessment_columns(conn) -> None:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(post_assessments)").fetchall()}
    for name, declaration in (
        ("score_value", "REAL"),
        ("rating_origin", "TEXT"),
        ("score_origin", "TEXT"),
        ("rating_missing_reason", "TEXT"),
        ("score_missing_reason", "TEXT"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE post_assessments ADD COLUMN {name} {declaration}")
    fmt_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(content_formats)").fetchall()}
    for name, declaration in (
        ("example_url", "TEXT"),
        ("status", "TEXT"),
        ("usage_count", "INTEGER"),
    ):
        if name not in fmt_cols:
            conn.execute(f"ALTER TABLE content_formats ADD COLUMN {name} {declaration}")


def _row_get(existing: Any | None, key: str) -> Any:
    if existing is None:
        return None
    try:
        return existing[key]
    except (KeyError, IndexError, TypeError):
        return None


def _effective_assessment_values(existing: Any | None, row: ParsedRow) -> dict[str, Any]:
    """Values that would be stored after update — missing Excel cache never clears valid DB values."""
    db_rating = _row_get(existing, "rating_text")
    db_score = _row_get(existing, "score_value")
    if row.rating_text is not None:
        new_rating = row.rating_text
        rating_preserved = False
    elif row.rating_missing_reason and db_rating:
        new_rating = db_rating
        rating_preserved = True
    else:
        new_rating = db_rating if existing is not None else None
        rating_preserved = bool(row.rating_missing_reason and db_rating)

    if row.score_value is not None:
        new_score = row.score_value
        score_preserved = False
    elif row.score_missing_reason and db_score is not None:
        new_score = db_score
        score_preserved = True
    else:
        new_score = db_score if existing is not None else None
        score_preserved = bool(row.score_missing_reason and db_score is not None)

    return {
        "rating_text": new_rating,
        "score_value": new_score,
        "rating_preserved_due_to_missing_cache": rating_preserved,
        "score_preserved_due_to_missing_cache": score_preserved,
        "rating_origin": (
            _row_get(existing, "rating_origin") if rating_preserved else row.rating_origin
        ),
        "score_origin": (
            _row_get(existing, "score_origin") if score_preserved else row.score_origin
        ),
    }


def _assessment_diff(conn, post_id: int, row: ParsedRow) -> dict[str, Any] | None:
    existing = conn.execute(
        """
        SELECT id, rating_text, score_value, rating_origin, score_origin, insight_text, action_text,
               rating_missing_reason, score_missing_reason
        FROM post_assessments
        WHERE post_id = ? AND source = ?
        ORDER BY id DESC LIMIT 1
        """,
        (post_id, ASSESSMENT_SOURCE),
    ).fetchone()
    incoming = {
        "rating_text": row.rating_text,
        "score_value": row.score_value,
        "rating_origin": row.rating_origin,
        "rating_missing_reason": row.rating_missing_reason,
        "score_missing_reason": row.score_missing_reason,
    }
    effective = _effective_assessment_values(existing, row)
    if existing is None:
        if not any(
            [
                row.rating_text,
                row.score_value is not None,
                row.insight,
                row.action,
            ]
        ):
            # Missing-cache-only row without existing assessment: nothing useful to insert
            if row.rating_missing_reason or row.score_missing_reason:
                return {
                    "post_id": post_id,
                    "excel_row": row.excel_row,
                    "changed": False,
                    "kind": "missing_cache_no_existing",
                    "existing": None,
                    "incoming": incoming,
                    "effective": effective,
                    "old_rating": None,
                    "new_rating": None,
                    "old_score": None,
                    "new_score": None,
                }
            return None
        return {
            "post_id": post_id,
            "excel_row": row.excel_row,
            "changed": True,
            "kind": "new",
            "existing": None,
            "incoming": incoming,
            "effective": effective,
            "old_rating": None,
            "new_rating": effective["rating_text"],
            "old_score": None,
            "new_score": effective["score_value"],
        }

    db_rating = existing["rating_text"]
    db_score = existing["score_value"]
    changes = []
    preserved = []
    if (effective["rating_text"] or None) != (db_rating or None):
        changes.append(
            {
                "field": "rating_text",
                "existing": db_rating,
                "incoming": row.rating_text,
                "effective": effective["rating_text"],
            }
        )
    elif effective["rating_preserved_due_to_missing_cache"]:
        preserved.append(
            {
                "field": "rating_text",
                "existing": db_rating,
                "incoming": None,
                "note": row.rating_missing_reason,
            }
        )

    if effective["score_value"] is not None and db_score is None:
        changes.append(
            {
                "field": "score_value",
                "existing": db_score,
                "incoming": row.score_value,
                "effective": effective["score_value"],
            }
        )
    elif (
        effective["score_value"] is not None
        and db_score is not None
        and abs(float(db_score) - float(effective["score_value"])) > 1e-9
    ):
        changes.append(
            {
                "field": "score_value",
                "existing": db_score,
                "incoming": row.score_value,
                "effective": effective["score_value"],
            }
        )
    elif effective["score_preserved_due_to_missing_cache"]:
        preserved.append(
            {
                "field": "score_value",
                "existing": db_score,
                "incoming": None,
                "note": row.score_missing_reason,
            }
        )

    kind = "update" if changes else ("unchanged_preserved_missing" if preserved else "unchanged")
    return {
        "post_id": post_id,
        "excel_row": row.excel_row,
        "changed": bool(changes),
        "kind": kind,
        "changes": changes,
        "preserved_due_to_missing_cache": preserved,
        "existing": {
            "rating_text": existing["rating_text"],
            "score_value": existing["score_value"],
            "rating_origin": existing["rating_origin"],
        },
        "incoming": incoming,
        "effective": effective,
        "old_rating": db_rating,
        "new_rating": effective["rating_text"],
        "old_score": db_score,
        "new_score": effective["score_value"],
        "preserve_human_insight_action": True,
        "existing_insight_present": bool(str(existing["insight_text"] or "").strip()),
        "existing_action_present": bool(str(existing["action_text"] or "").strip()),
    }


def _ensure_formats_from_sheet(conn, client_id: int, formats: list[dict[str, Any]]) -> None:
    from maaike.repository import update_format

    _ensure_assessment_columns(conn)
    existing = {item.name.lower(): item for item in list_formats(conn, client_id)}
    for item in formats:
        code = item["code"]
        explanation = item.get("explanation") or ""
        key = code.lower()
        example_url = item.get("example_url")
        status = item.get("status")
        usage = item.get("count")
        usage_count = None
        if usage is not None and str(usage).strip() != "":
            try:
                usage_count = int(float(usage))
            except (TypeError, ValueError):
                usage_count = None
        if key in existing:
            current = existing[key]
            # Fill empty explanations from Formats sheet; do not invent text.
            if explanation and not str(getattr(current, "explanation", "") or "").strip():
                update_format(conn, client_id, current.item_id, current.name, explanation)
            conn.execute(
                """
                UPDATE content_formats
                SET example_url = COALESCE(NULLIF(TRIM(COALESCE(example_url, '')), ''), ?),
                    status = COALESCE(NULLIF(TRIM(COALESCE(status, '')), ''), ?),
                    usage_count = COALESCE(usage_count, ?)
                WHERE id = ? AND client_id = ?
                """,
                (example_url, status, usage_count, current.item_id, client_id),
            )
            continue
        new_id = add_format(conn, client_id, code, explanation)
        conn.execute(
            """
            UPDATE content_formats
            SET example_url = ?, status = ?, usage_count = ?
            WHERE id = ? AND client_id = ?
            """,
            (example_url, status, usage_count, new_id, client_id),
        )
        existing[key] = True  # type: ignore


def _ensure_pillar(conn, client_id: int, name: str | None, pillar_ids: dict[str, int]) -> int | None:
    if not name:
        return None
    if name in pillar_ids:
        return pillar_ids[name]
    # case-insensitive
    for key, value in pillar_ids.items():
        if key.lower() == name.lower():
            return value
    new_id = add_pillar(conn, client_id, name, "")
    pillar_ids[name] = new_id
    return new_id


def _insert_excel_post(conn, client_id: int, row: ParsedRow, now: str) -> int:
    published = row.datum.isoformat() if row.datum else now[:10]
    cursor = conn.execute(
        """
        INSERT INTO posts (
            client_id, platform, external_id, published_at, content_kind, permalink,
            account_name, caption, media_urls, last_synced_at,
            platform_label, source_origin
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
        """,
        (
            client_id,
            row.platform_key,
            row.external_id,
            published,
            row.content_soort,
            row.permalink_raw,
            None,
            row.platform_label,
            IMPORT_SOURCE,
        ),
    )
    return int(cursor.lastrowid)


def _apply_row_to_post(
    conn,
    client_id: int,
    post_id: int,
    row: ParsedRow,
    *,
    format_ids: dict[str, int],
    pillar_ids: dict[str, int],
    imported_at: str,
    source_file: str,
    update_assessments: bool = False,
    applied_counts: dict[str, int] | None = None,
) -> int:
    filled = 0
    post = conn.execute("SELECT * FROM posts WHERE id = ? AND client_id = ?", (post_id, client_id)).fetchone()
    if post is None:
        return 0
    _ensure_assessment_columns(conn)
    # Preserve original platform label when empty
    if row.platform_label and not post["platform_label"]:
        conn.execute(
            "UPDATE posts SET platform_label = ? WHERE id = ?",
            (row.platform_label, post_id),
        )
        filled += 1
    if row.content_soort and not post["content_kind"]:
        conn.execute("UPDATE posts SET content_kind = ? WHERE id = ?", (row.content_soort, post_id))
        filled += 1
    if row.permalink_raw and not post["permalink"]:
        conn.execute("UPDATE posts SET permalink = ? WHERE id = ?", (row.permalink_raw, post_id))
        filled += 1

    format_id = None
    if row.format_code and row.format_code.lower() not in {"nvt.", "nvt", "n.v.t.", "n.v.t"}:
        for key, value in format_ids.items():
            if key.lower() == row.format_code.lower():
                format_id = value
                break
        if format_id is None:
            format_id = add_format(conn, client_id, row.format_code, "")
            format_ids[row.format_code] = format_id
    pillar_id = _ensure_pillar(conn, client_id, row.contentpijler, pillar_ids)

    editorial = conn.execute("SELECT * FROM post_editorial WHERE post_id = ?", (post_id,)).fetchone()
    current_format = editorial["format_id"] if editorial else None
    current_pillar = editorial["pillar_id"] if editorial else None
    current_hook = (editorial["hook"] if editorial else "") or ""
    new_format = current_format if current_format is not None else format_id
    new_pillar = current_pillar if current_pillar is not None else pillar_id
    new_hook = current_hook if current_hook.strip() else (row.hook or "")
    if format_id is not None and current_format is None:
        filled += 1
    if pillar_id is not None and current_pillar is None:
        filled += 1
    if row.hook and not current_hook.strip():
        filled += 1
    conn.execute(
        """
        INSERT INTO post_editorial (
            post_id, format_id, pillar_id, hook, updated_at,
            content_soort_raw, format_code_raw
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            format_id = COALESCE(post_editorial.format_id, excluded.format_id),
            pillar_id = COALESCE(post_editorial.pillar_id, excluded.pillar_id),
            hook = CASE
                WHEN TRIM(COALESCE(post_editorial.hook, '')) = '' THEN excluded.hook
                ELSE post_editorial.hook
            END,
            updated_at = excluded.updated_at,
            content_soort_raw = COALESCE(post_editorial.content_soort_raw, excluded.content_soort_raw),
            format_code_raw = COALESCE(post_editorial.format_code_raw, excluded.format_code_raw)
        """,
        (
            post_id,
            new_format,
            new_pillar,
            new_hook,
            imported_at,
            row.content_soort,
            row.format_code,
        ),
    )

    # Assessment from Excel — score/label/origin separate; never store formula text or invent 0.
    has_assessment_payload = any(
        [
            row.rating_text,
            row.score_value is not None,
            row.rating_missing_reason,
            row.score_missing_reason,
            row.insight,
            row.action,
        ]
    )
    if has_assessment_payload:
        existing_a = conn.execute(
            """
            SELECT id, rating_text, score_value, rating_origin, score_origin,
                   insight_text, action_text
            FROM post_assessments
            WHERE post_id = ? AND source = ? AND source_sheet = ? AND source_row = ?
            """,
            (post_id, ASSESSMENT_SOURCE, SOURCE_SHEET, row.excel_row),
        ).fetchone()
        if existing_a is None:
            # Also match legacy rows without sheet/row identity
            existing_a = conn.execute(
                """
                SELECT id, rating_text, score_value, rating_origin, score_origin,
                       insight_text, action_text
                FROM post_assessments
                WHERE post_id = ? AND source = ?
                ORDER BY id DESC LIMIT 1
                """,
                (post_id, ASSESSMENT_SOURCE),
            ).fetchone()
        if existing_a is None:
            # Do not insert an empty assessment that only records missing cache
            if not any([row.rating_text, row.score_value is not None, row.insight, row.action]):
                if applied_counts is not None:
                    applied_counts["assessments_skipped_missing_cache"] = (
                        applied_counts.get("assessments_skipped_missing_cache", 0) + 1
                    )
            else:
                conn.execute(
                    """
                    INSERT INTO post_assessments (
                        post_id, source, source_label, rating_text, rating_fill,
                        score_value, rating_origin, score_origin,
                        rating_missing_reason, score_missing_reason,
                        insight_text, action_text, source_file, source_sheet, source_row, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        post_id,
                        ASSESSMENT_SOURCE,
                        ASSESSMENT_LABEL,
                        row.rating_text,
                        row.rating_fill,
                        row.score_value,
                        row.rating_origin,
                        row.score_origin,
                        row.rating_missing_reason,
                        row.score_missing_reason,
                        row.insight,
                        row.action,
                        source_file,
                        SOURCE_SHEET,
                        row.excel_row,
                        imported_at,
                    ),
                )
                filled += 1
                if applied_counts is not None:
                    applied_counts["assessments_inserted"] = applied_counts.get("assessments_inserted", 0) + 1
        elif update_assessments:
            # Preserve non-empty human insight/action; never clear valid score/label on missing cache.
            keep_insight = (existing_a["insight_text"] or "").strip() or row.insight
            keep_action = (existing_a["action_text"] or "").strip() or row.action
            effective = _effective_assessment_values(existing_a, row)
            conn.execute(
                """
                UPDATE post_assessments SET
                    rating_text = ?,
                    rating_fill = COALESCE(?, rating_fill),
                    score_value = ?,
                    rating_origin = ?,
                    score_origin = ?,
                    rating_missing_reason = ?,
                    score_missing_reason = ?,
                    insight_text = ?,
                    action_text = ?,
                    source_file = ?,
                    source_sheet = ?,
                    source_row = ?,
                    imported_at = ?
                WHERE id = ?
                """,
                (
                    effective["rating_text"],
                    row.rating_fill,
                    effective["score_value"],
                    effective["rating_origin"],
                    effective["score_origin"],
                    None if effective["rating_preserved_due_to_missing_cache"] else row.rating_missing_reason,
                    None if effective["score_preserved_due_to_missing_cache"] else row.score_missing_reason,
                    keep_insight,
                    keep_action,
                    source_file,
                    SOURCE_SHEET,
                    row.excel_row,
                    imported_at,
                    existing_a["id"],
                ),
            )
            filled += 1
            if applied_counts is not None:
                applied_counts["assessments_updated"] = applied_counts.get("assessments_updated", 0) + 1
                if effective["rating_preserved_due_to_missing_cache"] or effective["score_preserved_due_to_missing_cache"]:
                    applied_counts["assessments_preserved_missing_cache"] = (
                        applied_counts.get("assessments_preserved_missing_cache", 0) + 1
                    )
        else:
            if applied_counts is not None:
                applied_counts["assessments_skipped_existing"] = (
                    applied_counts.get("assessments_skipped_existing", 0) + 1
                )

    for metric_name, metric in row.metrics.items():
        if metric.kind == "empty":
            continue
        availability = {
            "nvt": "nvt",
            "zero": "measured",
            "number": "measured",
            "invalid": "invalid",
        }.get(metric.kind, "empty")
        if availability == "invalid":
            continue
        # Historical reading once per source row/metric (reimport-safe)
        already = conn.execute(
            """
            SELECT id FROM post_metric_readings
            WHERE post_id = ? AND metric_name = ? AND source_file = ?
              AND source_sheet = ? AND source_row = ?
            """,
            (post_id, metric_name, source_file, SOURCE_SHEET, row.excel_row),
        ).fetchone()
        if already is None:
            conn.execute(
                """
                INSERT INTO post_metric_readings (
                    post_id, metric_name, value, availability, source_name,
                    measured_at, imported_at, source_file, source_sheet, source_row
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post_id,
                    metric_name,
                    metric.value,
                    availability,
                    IMPORT_SOURCE,
                    None,  # measure moment unknown for Excel snapshot
                    imported_at,
                    source_file,
                    SOURCE_SHEET,
                    row.excel_row,
                ),
            )
            filled += 1
        else:
            continue
        # Do not overwrite newer Meta measured values on posts/post_metrics
        current = conn.execute(
            """
            SELECT value, availability, source_name, measured_at
            FROM post_metrics WHERE post_id = ? AND metric_name = ?
            """,
            (post_id, metric_name),
        ).fetchone()
        meta_blocks = (
            current is not None
            and current["availability"] in {"measured", "previous"}
            and str(current["source_name"] or "").lower().startswith("meta")
        )
        if meta_blocks:
            continue
        has_number = post[metric_name] is not None if metric_name in post.keys() else False
        if has_number and current is not None and current["availability"] in {"measured", "previous"}:
            # Keep existing non-empty current; Excel stays in readings only
            continue
        conn.execute(
            """
            INSERT INTO post_metrics (post_id, metric_name, value, availability, source_name, measured_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id, metric_name) DO UPDATE SET
                value = excluded.value,
                availability = excluded.availability,
                source_name = excluded.source_name,
                measured_at = excluded.measured_at
            """,
            (post_id, metric_name, metric.value, availability, IMPORT_SOURCE, None),
        )
        if metric_name in {"views", "likes", "comments", "shares", "saves", "clicks", "reach"}:
            conn.execute(
                f"UPDATE posts SET {metric_name} = ? WHERE id = ? AND client_id = ?",
                (metric.value, post_id, client_id),
            )
    # Provenance link
    conn.execute(
        """
        INSERT INTO post_import_links (
            post_id, source_file, source_sheet, source_row, imported_at,
            platform_label_original, excel_published_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id, source_file, source_sheet, source_row) DO UPDATE SET
            platform_label_original = COALESCE(post_import_links.platform_label_original, excluded.platform_label_original),
            excel_published_at = COALESCE(excluded.excel_published_at, post_import_links.excel_published_at)
        """,
        (
            post_id,
            source_file,
            SOURCE_SHEET,
            row.excel_row,
            imported_at,
            row.platform_label,
            row.datum.isoformat() if row.datum else None,
        ),
    )
    return filled


def _start_run(conn, client_id: int, path: Path, now: str) -> int:
    cursor = conn.execute(
        """
        INSERT INTO excel_import_runs (client_id, file_name, started_at, summary_json)
        VALUES (?, ?, ?, ?)
        """,
        (client_id, path.name, now, "{}"),
    )
    return int(cursor.lastrowid)


def _log_row(conn, run_id: int, row: ParsedRow, status: str, post_id: int | None, detail: dict) -> None:
    conn.execute(
        """
        INSERT INTO excel_import_rows (run_id, excel_row, status, post_id, detail_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, row.excel_row, status, post_id, json.dumps(detail, ensure_ascii=False, default=str)),
    )


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if _is_formula_like(value):
        return None
    text = str(value).strip()
    return text or None


def _is_formula_like(value: Any) -> bool:
    if value is None:
        return False
    type_name = type(value).__name__
    if type_name in {"ArrayFormula", "DataTableFormula"} or "Formula" in type_name:
        return True
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("="):
            return True
        if text.startswith("<openpyxl.worksheet.formula"):
            return True
    return False


def _resolve_cached_label(
    formula_value: Any,
    cached_value: Any,
    *,
    field_name: str,
) -> tuple[str | None, str | None, str | None]:
    """Return (label, origin, missing_reason). Never treat formula text as label."""
    if _is_formula_like(formula_value):
        if cached_value is None or (isinstance(cached_value, str) and not str(cached_value).strip()):
            return (
                None,
                "missing_cached_value",
                f"{field_name}: formule zonder opgeslagen uitkomst in Excel-cache (niet geïmporteerd als tekst, geen 0).",
            )
        if _is_formula_like(cached_value):
            return (
                None,
                "missing_cached_value",
                f"{field_name}: Excel-cache bevat nog formuletekst, geen berekende waarde.",
            )
        text = str(cached_value).strip()
        if not text:
            return (
                None,
                "missing_cached_value",
                f"{field_name}: lege opgeslagen formule-uitkomst.",
            )
        return text, "excel_cached_formula", None
    text = _as_text(formula_value)
    if text:
        return text, "excel_plain_text", None
    cached_text = _as_text(cached_value)
    if cached_text:
        return cached_text, "excel_cached_value", None
    return None, "empty", None


def _resolve_cached_score(
    formula_value: Any,
    cached_value: Any,
) -> tuple[float | None, str | None, str | None]:
    """Return (score, origin, missing_reason). Never invent 0 for missing cache."""
    if formula_value is None and cached_value is None:
        return None, "empty", None
    if _is_formula_like(formula_value) or (
        formula_value is None and cached_value is not None
    ):
        if cached_value is None or (isinstance(cached_value, str) and not str(cached_value).strip()):
            if _is_formula_like(formula_value):
                return (
                    None,
                    "missing_cached_value",
                    "Score: formule zonder opgeslagen uitkomst in Excel-cache (niet als 0 geïmporteerd).",
                )
            return None, "empty", None
        if _is_formula_like(cached_value):
            return (
                None,
                "missing_cached_value",
                "Score: Excel-cache bevat nog formuletekst, geen berekende waarde.",
            )
        try:
            number = float(cached_value)
        except (TypeError, ValueError):
            return (
                None,
                "missing_cached_value",
                f"Score: ongeldige cachewaarde {cached_value!r}.",
            )
        return number, "excel_cached_formula", None
    if formula_value is not None and not _is_formula_like(formula_value):
        try:
            return float(formula_value), "excel_plain_text", None
        except (TypeError, ValueError):
            return None, "empty", f"Score: ongeldige platte waarde {formula_value!r}."
    return None, "empty", None


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
