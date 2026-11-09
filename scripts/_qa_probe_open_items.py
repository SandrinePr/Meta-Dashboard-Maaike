from pathlib import Path

from maaike.db import connect

conn = connect(Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db"))
print(
    "analyses",
    [
        dict(r)
        for r in conn.execute(
            "select id,post_id,status,provider from post_ai_analyses order by id desc limit 5"
        ).fetchall()
    ],
)
for kind in ("image", "carousel", "reel", "story"):
    row = conn.execute(
        """
        select id,platform,content_kind,published_at
        from posts
        where client_id=1 and lower(coalesce(content_kind,'')) like ?
        order by published_at desc limit 1
        """,
        (f"%{kind}%",),
    ).fetchone()
    print(kind, dict(row) if row else None)
b1 = conn.execute(
    """
    select id,code,content_kind,period_year,period_month,page_name,node_id
    from figma_planning_items where client_id=1 and code='B1'
    """
).fetchone()
print("b1", dict(b1) if b1 else None)
print(
    "trial",
    [
        dict(r)
        for r in conn.execute(
            "select post_id,status from ai_trial_posts order by id desc limit 5"
        ).fetchall()
    ],
)
# Nov week mapping probe: posts around early November if any
print(
    "nov_posts",
    [
        dict(r)
        for r in conn.execute(
            """
            select id, platform, content_kind, published_at
            from posts where client_id=1 and published_at like '2026-11%'
            order by published_at
            """
        ).fetchall()
    ],
)
conn.close()
