"""Clone Red Rock report #9 onto QA Controle for local UI tests. No AI calls."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "maaike_redrock.db"


def now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        from maaike.report_review import ensure_report_review_tables

        ensure_report_review_tables(conn)
    except Exception:
        pass

    clients = list(conn.execute("SELECT id, name FROM clients ORDER BY id"))
    for c in clients:
        print(f"client {c['id']}: {c['name']}")

    qa = conn.execute("SELECT id, name FROM clients WHERE name LIKE 'QA%' ORDER BY id").fetchone()
    if qa is None:
        raise SystemExit("No QA client found")
    print(f"QA client -> {qa['id']} {qa['name']}")

    src = conn.execute("SELECT * FROM client_reports WHERE id = 9").fetchone()
    if src is None:
        raise SystemExit("Report #9 not found")
    print(
        f"source report #9 client_id={src['client_id']} status={src['status']} "
        f"title={src['title']}"
    )

    # Remove prior QA clones tagged for this test
    old = conn.execute(
        """
        SELECT id FROM client_reports
        WHERE client_id = ? AND title LIKE '%QA COPY of #9%'
        """,
        (qa["id"],),
    ).fetchall()
    for row in old:
        rid = int(row["id"])
        conn.execute("DELETE FROM client_report_reviews WHERE report_id = ?", (rid,))
        conn.execute("DELETE FROM client_reports WHERE id = ?", (rid,))
        print(f"removed old QA clone #{rid}")

    cols = [r[1] for r in conn.execute("PRAGMA table_info(client_reports)").fetchall()]
    skip = {"id"}
    insert_cols = [c for c in cols if c not in skip]
    values = []
    for c in insert_cols:
        if c == "client_id":
            values.append(qa["id"])
        elif c == "title":
            values.append(f"QA COPY of #9 — {src['title']}")
        elif c in {"prepared_at", "created_at", "updated_at"}:
            values.append(now())
        else:
            values.append(src[c])
    placeholders = ", ".join("?" for _ in insert_cols)
    col_sql = ", ".join(insert_cols)
    cur = conn.execute(
        f"INSERT INTO client_reports ({col_sql}) VALUES ({placeholders})",
        values,
    )
    new_id = int(cur.lastrowid)
    print(f"created QA report #{new_id}")

    rev = conn.execute(
        "SELECT * FROM client_report_reviews WHERE report_id = 9 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if rev is not None:
        # Fresh review shell with migrated empty feedback so Red Rock review is untouched
        # but AI body is on the cloned report; seed review from AI via first API save.
        print("source has review; clone starts without copying review rows (clean concept)")
    else:
        print("source has no review row")

    # Verify Red Rock #9 untouched
    rr = conn.execute("SELECT id, client_id, title FROM client_reports WHERE id = 9").fetchone()
    rr_rev = conn.execute(
        "SELECT id, review_status, final_version_text FROM client_report_reviews WHERE report_id = 9"
    ).fetchone()
    print(f"Red Rock #9 still client={rr['client_id']} title={rr['title']}")
    if rr_rev:
        ft = rr_rev["final_version_text"] or ""
        print(f"Red Rock review status={rr_rev['review_status']} final_len={len(ft)}")
        if "QA COPY" in ft or "QA Controle —" in ft:
            raise SystemExit("QA text found on Red Rock review — abort")
    conn.commit()
    print(json.dumps({"qa_client_id": qa["id"], "qa_report_id": new_id}, indent=2))


if __name__ == "__main__":
    main()
