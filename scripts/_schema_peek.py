import sqlite3
from pathlib import Path

for p in [Path("data/maaike_redrock.db"), Path("data/maaike_redrock_qa_copy.db")]:
    if not p.exists():
        print("missing", p)
        continue
    c = sqlite3.connect(p)
    print("===", p)
    for t in ("post_editorial", "post_assessments", "content_formats", "client_rating_settings", "strategy_fields"):
        cols = c.execute(f"pragma table_info({t})").fetchall()
        print(t, [r[1] for r in cols] if cols else "MISSING")
    c.close()
