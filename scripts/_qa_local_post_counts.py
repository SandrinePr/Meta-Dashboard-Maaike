"""Print local Red Rock post counts by platform/month."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ["maaike_redrock.db", "maaike_redrock_qa_demo.db"]:
    path = ROOT / "data" / name
    if not path.exists():
        print(name, "MISSING")
        continue
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    print("===", name, "===")
    for client in conn.execute("SELECT id, name, meta_status FROM clients"):
        print("client", dict(client))
        rows = conn.execute(
            """
            SELECT platform, substr(published_at, 1, 7) AS ym, COUNT(*) AS n
            FROM posts WHERE client_id = ?
            GROUP BY 1, 2
            ORDER BY 2 DESC, 1
            """,
            (client["id"],),
        ).fetchall()
        for row in rows[:40]:
            print(dict(row))
        total = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE client_id = ?",
            (client["id"],),
        ).fetchone()[0]
        print("total", total)
    try:
        print("meta_secrets_rows", conn.execute("SELECT COUNT(*) FROM client_meta_secrets").fetchone()[0])
    except Exception as exc:
        print("meta_secrets", exc)
    conn.close()
