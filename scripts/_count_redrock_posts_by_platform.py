"""Count unique Red Rock posts per platform from stored DB only."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from maaike.db import connect
from maaike.migrate import apply_migrations

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "maaike_redrock.db"


def main() -> None:
    conn = connect(DB)
    apply_migrations(conn)
    client = conn.execute("SELECT id, name FROM clients WHERE name = ?", ("Red Rock",)).fetchone()
    assert client, "Red Rock missing"
    cid = int(client["id"])
    print("client", cid, client["name"])

    cols = [r[1] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
    print("posts_cols", cols)

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM posts WHERE client_id = ?", (cid,)
    ).fetchone()["n"]
    print("total_unique_post_rows", total)

    # Distinct ids sanity
    distinct_ids = conn.execute(
        "SELECT COUNT(DISTINCT id) AS n FROM posts WHERE client_id = ?", (cid,)
    ).fetchone()["n"]
    print("distinct_ids", distinct_ids)

    rows = conn.execute(
        """
        SELECT id, platform, platform_label, source_origin, permalink, external_id
        FROM posts WHERE client_id = ?
        """,
        (cid,),
    ).fetchall()

    by_platform = Counter()
    by_label = Counter()
    by_origin = Counter()
    for r in rows:
        plat = (r["platform"] or "").strip().lower() or "unknown"
        label = (r["platform_label"] or r["platform"] or "Unknown").strip() or "Unknown"
        by_platform[plat] += 1
        by_label[label] += 1
        by_origin[(r["source_origin"] or "").strip() or "unknown"] += 1

    print("by_platform_key", dict(sorted(by_platform.items())))
    print("by_platform_label", dict(sorted(by_label.items())))
    print("by_source_origin", dict(sorted(by_origin.items())))

    # Related tables that must NOT inflate post counts
    for table, sql in [
        ("comments", "SELECT COUNT(*) AS n FROM comments c JOIN posts p ON p.id=c.post_id WHERE p.client_id=?"),
        (
            "post_assessments_if_any",
            None,
        ),
    ]:
        if table == "post_assessments_if_any":
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%assess%'"
            ).fetchall()
            print("assessment_like_tables", [x[0] for x in exists])
            for name in [x[0] for x in exists]:
                try:
                    n = conn.execute(
                        f"SELECT COUNT(*) AS n FROM {name} WHERE client_id = ?", (cid,)
                    ).fetchone()["n"]
                    print(f"  {name}.client_id_rows", n)
                except Exception as exc:
                    try:
                        n = conn.execute(
                            f"""
                            SELECT COUNT(*) AS n FROM {name} a
                            JOIN posts p ON p.id = a.post_id
                            WHERE p.client_id = ?
                            """,
                            (cid,),
                        ).fetchone()["n"]
                        print(f"  {name}.via_post", n)
                    except Exception as exc2:
                        print(f"  {name}.skip", type(exc).__name__, type(exc2).__name__)
            continue
        try:
            n = conn.execute(sql, (cid,)).fetchone()["n"]
            print(table, n)
        except Exception as exc:
            print(table, "err", exc)

    # Compare with API-style payload length if available
    try:
        from maaike_web.app import _posts_payload

        payload = _posts_payload(cid)
        posts = payload.get("posts") or []
        print("api_posts_len", len(posts))
        api_labels = Counter()
        for p in posts:
            cells = p.get("cells") or {}
            label = str(cells.get("Platform") or p.get("platform_label") or p.get("platform") or "Unknown")
            api_labels[label] += 1
        print("api_by_Platform_cell", dict(sorted(api_labels.items())))
    except Exception as exc:
        print("api_payload_err", type(exc).__name__, exc)

    out = {
        "client_id": cid,
        "total_unique_posts": total,
        "by_platform_key": dict(sorted(by_platform.items())),
        "by_platform_label": dict(sorted(by_label.items())),
    }
    dest = ROOT / "data" / "imports" / "redrock" / "_redrock_post_platform_counts.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", dest)


if __name__ == "__main__":
    main()
