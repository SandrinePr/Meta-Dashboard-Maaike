import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.db import connect

conn = connect(Path(os.environ["MAAIKE_DATABASE_PATH"]))
for label, like in (
    ("image", "%image%"),
    ("carousel", "%carousel%"),
    ("reel", "%reel%"),
    ("story", "%story%"),
):
    rows = conn.execute(
        """
        SELECT id, content_kind, published_at,
               CASE WHEN media_urls IS NULL OR trim(media_urls)='' THEN 0 ELSE 1 END AS has_media,
               length(coalesce(media_urls,'')) AS media_len,
               substr(coalesce(media_urls,''),1,100) AS media_preview
        FROM posts
        WHERE client_id=1 AND lower(coalesce(content_kind,'')) LIKE ?
        ORDER BY published_at DESC
        LIMIT 4
        """,
        (like,),
    ).fetchall()
    print(label, [dict(r) for r in rows])
print(
    "nov",
    [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, platform, content_kind, published_at
            FROM posts WHERE client_id=1 AND published_at LIKE '2026-11%'
            ORDER BY published_at
            """
        ).fetchall()
    ],
)
conn.close()
