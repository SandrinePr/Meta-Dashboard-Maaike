"""QA: activity series collapse for #17–#20. No paid AI."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA_DB = ROOT / "data" / "maaike_redrock_qa_demo.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_qa_activity_series_check.json"


def main() -> None:
    from maaike.activity_log import (
        _fmt,
        _status_bucket,
        group_report_rows_into_series,
        list_activity_events,
    )
    from maaike.db import connect
    from maaike.migrate import apply_migrations

    conn = connect(QA_DB)
    apply_migrations(conn)
    default = list_activity_events(conn, client_id=1, limit=80)
    series = [e for e in default["events"] if e.get("latest_report_id") == 20][0]
    assert series["display_label"] == "Gereed"
    assert set([17, 18, 19, 20]).issubset(set(series["report_ids"]))
    assert series["has_earlier_failures"] is True

    # Latest failed stays visible when #20 is absent from the set
    rows = []
    for row in conn.execute(
        """
        SELECT r.id, r.client_id, r.report_type, r.status, r.title, r.prepared_at,
               r.executed_at, r.error_text, r.is_mock, r.version, r.supersedes_id,
               c.name AS client_name
        FROM client_reports r
        JOIN clients c ON c.id = r.client_id
        WHERE r.client_id = 1 AND r.id < 20
        """
    ):
        ts = row["executed_at"] or row["prepared_at"]
        st = row["status"] or ""
        err = st == "failed" or bool(row["error_text"])
        rows.append(
            {
                "id": row["id"],
                "occurred_at": ts,
                "occurred_at_label": _fmt(ts),
                "client_id": row["client_id"],
                "client_name": row["client_name"],
                "activity_type": "report",
                "status": st,
                "status_bucket": _status_bucket(st, err),
                "title": f"Report ({row['report_type']}): {row['title']}",
                "details": row["error_text"] or "",
                "source": "client_reports",
                "is_error": err,
                "version": row["version"],
                "supersedes_id": row["supersedes_id"],
            }
        )
    failed_latest = next(e for e in group_report_rows_into_series(rows) if e["latest_report_id"] == 19)
    assert failed_latest["display_label"] == "Actie nodig"
    assert failed_latest["is_error"] is True
    assert "overbelast" in (failed_latest["plain_summary"] or "").lower()

    errors = list_activity_events(conn, client_id=1, errors_only=True, limit=100)
    fail_ids = {e.get("latest_report_id") for e in errors["events"] if e["activity_type"] == "report"}
    assert {17, 18, 19}.issubset(fail_ids)

    out = {
        "series_20": {
            "display_label": series["display_label"],
            "latest_report_id": series["latest_report_id"],
            "report_ids": series["report_ids"],
            "failed_attempt_ids": [a["report_id"] for a in series["attempts"] if a["is_error"]],
            "has_earlier_failures": series["has_earlier_failures"],
        },
        "simulated_latest_failed_19": {
            "display_label": failed_latest["display_label"],
            "plain_summary": failed_latest["plain_summary"],
            "visible_in_default_overview": True,
        },
        "errors_only_failed_ids": sorted(x for x in fail_ids if x),
        "meta_sync_still_listed": any(e["activity_type"] == "meta_sync" for e in default["events"]),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
