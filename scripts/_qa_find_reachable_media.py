import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.db import connect

root = Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\ai_trial_media")
print("trial_media exists", root.exists())
if root.exists():
    files = [p for p in root.rglob("*") if p.is_file()]
    print("file_count", len(files))
    for p in files[:30]:
        print(p.relative_to(root), p.stat().st_size)

conn = connect(Path(os.environ["MAAIKE_DATABASE_PATH"]))
try:
    rows = conn.execute(
        """
        SELECT post_id, kind, original_name, relative_path
        FROM post_media_assets WHERE client_id=1 ORDER BY id DESC LIMIT 15
        """
    ).fetchall()
    print("uploads", [dict(r) for r in rows])
except Exception as exc:
    print("uploads err", exc)

for pid in (31, 16, 8, 353, 352, 1, 2, 3):
    row = conn.execute(
        "SELECT id, content_kind, substr(media_urls,1,100) AS m FROM posts WHERE id=? AND client_id=1",
        (pid,),
    ).fetchone()
    print("post", dict(row) if row else {"id": pid, "missing": True})
conn.close()
