"""Dashboard activity overview for Logs (newest first). No secrets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from maaike.presentation import AMSTERDAM


def ensure_activity_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_activity_events (
            id INTEGER PRIMARY KEY,
            client_id INTEGER,
            occurred_at TEXT NOT NULL,
            activity_type TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL DEFAULT '',
            source_ref TEXT NOT NULL DEFAULT '',
            is_error INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_occurred
            ON dashboard_activity_events(occurred_at DESC, id DESC)
        """
    )


def record_activity(
    conn,
    *,
    client_id: int | None,
    activity_type: str,
    status: str,
    title: str,
    details: str = "",
    source_ref: str = "",
    is_error: bool = False,
    occurred_at: str | None = None,
) -> int:
    ensure_activity_table(conn)
    now = datetime.now(tz=timezone.utc).isoformat()
    cur = conn.execute(
        """
        INSERT INTO dashboard_activity_events (
            client_id, occurred_at, activity_type, status, title, details,
            source_ref, is_error, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            client_id,
            occurred_at or now,
            activity_type,
            status,
            title,
            details,
            source_ref,
            1 if is_error else 0,
            now,
        ),
    )
    return int(cur.lastrowid)


def _fmt(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        raw = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(AMSTERDAM).strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return ts[:16]


def _status_bucket(status: str, is_error: bool) -> str:
    s = (status or "").lower()
    if is_error or s in {"failed", "error", "blocked_budget", "failed_may_still_cost"}:
        return "error"
    if s in {"running", "prepared", "prepared_not_executed", "estimate_only_not_executed"}:
        return "pending"
    if s in {"completed", "mock_completed", "ok", "success", "success_partial"}:
        return "ok"
    return "info"


def _plain_report_failure(error_text: str | None, status: str) -> str:
    """Short Dutch explanation for Maaike — technical text stays in details/attempts."""
    raw = (error_text or "").strip()
    low = raw.lower()
    if "high demand" in low or "unavailable" in low or "503" in low:
        return "Het AI-model was tijdelijk overbelast. Probeer later opnieuw of kies een ander model."
    if "budget" in low or "blocked_budget" in (status or "").lower():
        return "De kostenraming lag boven het ingestelde budget."
    if "onbruikbaar" in low or "validat" in low:
        return "Het AI-antwoord was onbruikbaar. Open het rapport en probeer opnieuw."
    if (status or "").lower() == "failed":
        if raw:
            return "De rapportgeneratie is mislukt. Zie technische details onder Pogingen bekijken."
        return "De rapportgeneratie is mislukt. Open het rapport voor details."
    return raw[:220] if raw else ""


def _report_display(status: str, is_error: bool) -> dict[str, str]:
    bucket = _status_bucket(status, is_error)
    st = (status or "").lower()
    if st in {"completed", "mock_completed"} or (bucket == "ok" and not is_error):
        return {
            "display_status": "ready",
            "display_label": "Gereed",
            "status_bucket": "ok",
        }
    if is_error or st == "failed" or bucket == "error":
        return {
            "display_status": "action_needed",
            "display_label": "Actie nodig",
            "status_bucket": "error",
        }
    if bucket == "pending":
        return {
            "display_status": "pending",
            "display_label": "In voorbereiding",
            "status_bucket": "pending",
        }
    return {
        "display_status": "info",
        "display_label": status or "—",
        "status_bucket": bucket,
    }


def group_report_rows_into_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One activity event per supersedes-linked report series (latest attempt wins).

    Rows without a supersedes link to another loaded report stay as their own series.
    """
    if not rows:
        return []
    by_id = {int(r["id"]): r for r in rows}
    parent: dict[int, int | None] = {}
    for r in rows:
        rid = int(r["id"])
        raw = r.get("supersedes_id")
        try:
            sid = int(raw) if raw not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            sid = None
        parent[rid] = sid if sid in by_id else None

    # Union-find so branches (e.g. #18 and #19 both superseding #17) share one series.
    uf: dict[int, int] = {rid: rid for rid in by_id}

    def find(x: int) -> int:
        while uf[x] != x:
            uf[x] = uf[uf[x]]
            x = uf[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            uf[rb] = ra

    for rid, sid in parent.items():
        if sid is not None:
            union(rid, sid)

    groups: dict[int, list[dict[str, Any]]] = {}
    for rid, row in by_id.items():
        groups.setdefault(find(rid), []).append(row)

    series_events: list[dict[str, Any]] = []
    for root, members in groups.items():
        members_sorted = sorted(
            members,
            key=lambda m: (m.get("occurred_at") or "", int(m["id"])),
            reverse=True,
        )
        latest = members_sorted[0]
        attempts = []
        for m in members_sorted:
            st = m.get("status") or ""
            err = bool(m.get("is_error"))
            disp = _report_display(st, err)
            attempts.append(
                {
                    "id": f"report-{m['id']}",
                    "report_id": int(m["id"]),
                    "occurred_at": m.get("occurred_at"),
                    "occurred_at_label": m.get("occurred_at_label"),
                    "status": st,
                    "status_bucket": disp["status_bucket"],
                    "display_label": disp["display_label"],
                    "title": m.get("title") or "",
                    "details": m.get("details") or "",
                    "plain_summary": _plain_report_failure(m.get("details"), st) if err else "",
                    "is_error": err,
                    "is_latest": int(m["id"]) == int(latest["id"]),
                    "version": m.get("version"),
                    "supersedes_id": m.get("supersedes_id"),
                }
            )
        latest_err = bool(latest.get("is_error"))
        disp = _report_display(latest.get("status") or "", latest_err)
        prior_failures = [a for a in attempts if a["is_error"] and not a["is_latest"]]
        series_events.append(
            {
                "id": f"report-series-{root}",
                "occurred_at": latest.get("occurred_at"),
                "occurred_at_label": latest.get("occurred_at_label"),
                "client_id": latest.get("client_id"),
                "client_name": latest.get("client_name"),
                "activity_type": "report",
                "status": latest.get("status"),
                "status_bucket": disp["status_bucket"],
                "display_status": disp["display_status"],
                "display_label": disp["display_label"],
                "title": latest.get("title") or "",
                "details": (latest.get("details") or "")
                if latest_err
                else (
                    f"{len(prior_failures)} earlier failed attempt(s) under Pogingen bekijken."
                    if prior_failures
                    else ""
                ),
                "plain_summary": _plain_report_failure(latest.get("details"), latest.get("status") or "")
                if latest_err
                else "",
                "source": "client_reports",
                "is_error": latest_err,
                "is_report_series": True,
                "series_root_id": int(root),
                "latest_report_id": int(latest["id"]),
                "report_ids": [int(m["id"]) for m in members_sorted],
                "attempt_count": len(attempts),
                "failed_attempt_count": sum(1 for a in attempts if a["is_error"]),
                "attempts": attempts,
                "has_earlier_failures": bool(prior_failures),
            }
        )
    return series_events


def list_activity_events(
    conn,
    *,
    client_id: int | None = None,
    activity_type: str | None = None,
    status: str | None = None,
    errors_only: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    """Synthesize + stored events. Newest first. Reports collapse to one row per series."""
    ensure_activity_table(conn)
    events: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []

    # Stored explicit events
    q = """
        SELECT e.*, c.name AS client_name
        FROM dashboard_activity_events e
        LEFT JOIN clients c ON c.id = e.client_id
        WHERE 1=1
    """
    params: list[Any] = []
    if client_id is not None:
        q += " AND e.client_id = ?"
        params.append(client_id)
    q += " ORDER BY e.occurred_at DESC, e.id DESC LIMIT ?"
    params.append(limit)
    for row in conn.execute(q, params).fetchall():
        events.append(
            {
                "id": f"stored-{row['id']}",
                "occurred_at": row["occurred_at"],
                "occurred_at_label": _fmt(row["occurred_at"]),
                "client_id": row["client_id"],
                "client_name": row["client_name"] or "—",
                "activity_type": row["activity_type"],
                "status": row["status"],
                "status_bucket": _status_bucket(row["status"], bool(row["is_error"])),
                "title": row["title"],
                "details": row["details"],
                "source": "dashboard_activity_events",
                "is_error": bool(row["is_error"]),
            }
        )

    # Client Meta fetch outcomes
    cq = "SELECT id, name, last_fetch_status, last_fetch_detail, last_fetch_at FROM clients"
    cparams: list[Any] = []
    if client_id is not None:
        cq += " WHERE id = ?"
        cparams.append(client_id)
    for row in conn.execute(cq, cparams).fetchall():
        if not row["last_fetch_at"]:
            continue
        st = row["last_fetch_status"] or "unknown"
        err = st.lower() in {"error", "failed"}
        events.append(
            {
                "id": f"fetch-{row['id']}-{row['last_fetch_at']}",
                "occurred_at": row["last_fetch_at"],
                "occurred_at_label": _fmt(row["last_fetch_at"]),
                "client_id": row["id"],
                "client_name": row["name"],
                "activity_type": "meta_sync",
                "status": st,
                "status_bucket": _status_bucket(st, err),
                "title": "Meta synchronisation",
                "details": row["last_fetch_detail"] or "",
                "source": "clients.last_fetch",
                "is_error": err,
            }
        )

    # Excel import runs
    eq = """
        SELECT r.id, r.client_id, r.file_name, r.started_at, r.finished_at, r.summary_json,
               c.name AS client_name
        FROM excel_import_runs r
        JOIN clients c ON c.id = r.client_id
    """
    eparams: list[Any] = []
    if client_id is not None:
        eq += " WHERE r.client_id = ?"
        eparams.append(client_id)
    eq += " ORDER BY COALESCE(r.finished_at, r.started_at) DESC LIMIT 50"
    if _table_exists(conn, "excel_import_runs"):
        for row in conn.execute(eq, eparams).fetchall():
            summary = {}
            try:
                summary = json.loads(row["summary_json"] or "{}")
            except json.JSONDecodeError:
                summary = {}
            ts = row["finished_at"] or row["started_at"]
            events.append(
                {
                    "id": f"excel-{row['id']}",
                    "occurred_at": ts,
                    "occurred_at_label": _fmt(ts),
                    "client_id": row["client_id"],
                    "client_name": row["client_name"],
                    "activity_type": "excel_import",
                    "status": "completed" if row["finished_at"] else "running",
                    "status_bucket": "ok" if row["finished_at"] else "pending",
                    "title": f"Excel import: {row['file_name']}",
                    "details": json.dumps(summary, ensure_ascii=False)[:500] if summary else "",
                    "source": "excel_import_runs",
                    "is_error": False,
                }
            )

    # AI usage events
    if _table_exists(conn, "ai_usage_events"):
        aq = """
            SELECT u.id, u.client_id, u.status, u.started_at, u.finished_at, u.notes,
                   u.model, u.prompt_version, c.name AS client_name
            FROM ai_usage_events u
            LEFT JOIN clients c ON c.id = u.client_id
        """
        aparams: list[Any] = []
        if client_id is not None:
            aq += " WHERE u.client_id = ?"
            aparams.append(client_id)
        aq += " ORDER BY COALESCE(u.finished_at, u.started_at) DESC LIMIT 80"
        for row in conn.execute(aq, aparams).fetchall():
            ts = row["finished_at"] or row["started_at"]
            st = row["status"] or ""
            err = "fail" in st.lower() or st.lower() in {"error", "blocked_budget"}
            events.append(
                {
                    "id": f"ai-{row['id']}",
                    "occurred_at": ts,
                    "occurred_at_label": _fmt(ts),
                    "client_id": row["client_id"],
                    "client_name": row["client_name"] or "—",
                    "activity_type": "ai",
                    "status": st,
                    "status_bucket": _status_bucket(st, err),
                    "title": f"AI · {row['model'] or 'unknown model'} · {row['prompt_version'] or ''}".strip(),
                    "details": row["notes"] or "",
                    "source": "ai_usage_events",
                    "is_error": err,
                }
            )

    # Reports (grouped by supersedes series in the default overview)
    if _table_exists(conn, "client_reports"):
        rq = """
            SELECT r.id, r.client_id, r.report_type, r.status, r.title, r.prepared_at,
                   r.executed_at, r.error_text, r.is_mock, r.version, r.supersedes_id,
                   c.name AS client_name
            FROM client_reports r
            JOIN clients c ON c.id = r.client_id
        """
        rparams: list[Any] = []
        if client_id is not None:
            rq += " WHERE r.client_id = ?"
            rparams.append(client_id)
        rq += " ORDER BY COALESCE(r.executed_at, r.prepared_at, r.updated_at) DESC LIMIT 200"
        for row in conn.execute(rq, rparams).fetchall():
            ts = row["executed_at"] or row["prepared_at"]
            st = row["status"] or ""
            err = st == "failed" or bool(row["error_text"])
            report_rows.append(
                {
                    "id": row["id"],
                    "occurred_at": ts,
                    "occurred_at_label": _fmt(ts),
                    "client_id": row["client_id"],
                    "client_name": row["client_name"],
                    "activity_type": "report",
                    "status": st,
                    "status_bucket": _status_bucket(st, err),
                    "title": f"Report ({row['report_type']}): {row['title']}"
                    + (" · MOCK" if row["is_mock"] else ""),
                    "details": row["error_text"] or "",
                    "source": "client_reports",
                    "is_error": err,
                    "version": row["version"],
                    "supersedes_id": row["supersedes_id"],
                }
            )

    # Dedupe non-report events by id
    seen = set()
    unique = []
    for ev in events:
        if ev["id"] in seen:
            continue
        seen.add(ev["id"])
        unique.append(ev)

    if errors_only:
        # Full failed history: each failed report attempt as its own row (+ other errors).
        failed_reports = []
        for row in report_rows:
            if not (row["is_error"] or row["status_bucket"] == "error"):
                continue
            disp = _report_display(row["status"], True)
            failed_reports.append(
                {
                    **row,
                    "id": f"report-{row['id']}",
                    "display_status": disp["display_status"],
                    "display_label": disp["display_label"],
                    "plain_summary": _plain_report_failure(row.get("details"), row.get("status") or ""),
                    "is_report_series": False,
                    "attempts": [],
                    "has_earlier_failures": False,
                    "latest_report_id": int(row["id"]),
                    "report_ids": [int(row["id"])],
                }
            )
        unique = [
            e for e in unique if e.get("is_error") or e.get("status_bucket") == "error"
        ] + failed_reports
    else:
        unique.extend(group_report_rows_into_series(report_rows))

    if activity_type:
        unique = [e for e in unique if e["activity_type"] == activity_type]
    if status:
        unique = [
            e
            for e in unique
            if e.get("status_bucket") == status
            or e.get("status") == status
            or e.get("display_status") == status
            or e.get("display_label") == status
        ]

    unique.sort(key=lambda e: e.get("occurred_at") or "", reverse=True)
    unique = unique[:limit]

    types = sorted({e["activity_type"] for e in unique})
    return {
        "events": unique,
        "count": len(unique),
        "activity_types": types,
        "filters": {
            "client_id": client_id,
            "activity_type": activity_type,
            "status": status,
            "errors_only": errors_only,
        },
        "note": (
            "Report versions linked via supersedes are shown as one row (latest status). "
            "Earlier attempts stay under Pogingen bekijken. Errors only lists every failed attempt. "
            "Sync and import events stay in this overview."
        ),
        "maaike_content_logs_style": "post_overview_dataframe",
    }


def activity_events_csv_bytes(events: list[dict[str, Any]]) -> bytes:
    import csv
    import io

    buffer = io.StringIO()
    fields = [
        "occurred_at",
        "occurred_at_label",
        "client_name",
        "activity_type",
        "status",
        "status_bucket",
        "display_label",
        "title",
        "details",
        "plain_summary",
        "is_error",
        "source",
        "latest_report_id",
        "attempt_report_id",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for ev in events:
        attempts = ev.get("attempts") or []
        if ev.get("is_report_series") and attempts:
            for attempt in attempts:
                writer.writerow(
                    {
                        "occurred_at": attempt.get("occurred_at"),
                        "occurred_at_label": attempt.get("occurred_at_label"),
                        "client_name": ev.get("client_name"),
                        "activity_type": "report",
                        "status": attempt.get("status"),
                        "status_bucket": attempt.get("status_bucket"),
                        "display_label": attempt.get("display_label"),
                        "title": attempt.get("title"),
                        "details": attempt.get("details"),
                        "plain_summary": attempt.get("plain_summary"),
                        "is_error": attempt.get("is_error"),
                        "source": "client_reports",
                        "latest_report_id": ev.get("latest_report_id"),
                        "attempt_report_id": attempt.get("report_id"),
                    }
                )
        else:
            writer.writerow(
                {
                    **ev,
                    "display_label": ev.get("display_label") or ev.get("status"),
                    "plain_summary": ev.get("plain_summary") or "",
                    "latest_report_id": ev.get("latest_report_id") or "",
                    "attempt_report_id": "",
                }
            )
    return buffer.getvalue().encode("utf-8-sig")


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None
