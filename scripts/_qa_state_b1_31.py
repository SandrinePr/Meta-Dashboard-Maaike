import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)
from maaike.db import connect

conn = connect(Path(os.environ["MAAIKE_DATABASE_PATH"]))
print("b1", dict(conn.execute("select id,code,linked_post_id,link_status,content_kind from figma_planning_items where id=1").fetchone()))
print("ed402", [dict(r) for r in conn.execute("select * from post_editorial where post_id=402").fetchall()])
print("post402", dict(conn.execute("select id,content_kind,platform from posts where id=402").fetchone()))
print(
    "a11",
    dict(
        conn.execute(
            "select id,status,substr(insight_text,1,160) as i, substr(action_text,1,100) as a from post_ai_analyses where id=11"
        ).fetchone()
    ),
)
print(
    "assess31",
    [
        dict(r)
        for r in conn.execute(
            "select id,source,substr(insight_text,1,80) as i from post_assessments where post_id=31 order by id desc limit 4"
        ).fetchall()
    ],
)
# revisions?
try:
    print(
        "revisions402",
        [
            dict(r)
            for r in conn.execute(
                "select * from post_editorial_revisions where post_id=402 order by id"
            ).fetchall()
        ],
    )
except Exception as exc:
    print("revisions err", exc)
conn.close()
