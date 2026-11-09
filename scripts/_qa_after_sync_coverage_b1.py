"""Post-sync coverage + November + Reel B1 suggestions."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.db import connect
from maaike.figma_planning import suggest_post_matches
from maaike.reports import get_report, inspect_client_report_data
from maaike.report_review import get_review_for_report

conn = connect(Path(os.environ["MAAIKE_DATABASE_PATH"]))
client = dict(
    conn.execute(
        """
        SELECT id, name, last_fetch_status, last_fetch_detail, last_fetch_at,
               last_fetch_from, last_fetch_until, last_fetch_instagram, last_fetch_facebook
        FROM clients WHERE id=1
        """
    ).fetchone()
)

nov = [
    dict(r)
    for r in conn.execute(
        """
        SELECT id, platform, content_kind, published_at
        FROM posts WHERE client_id=1 AND published_at LIKE '2026-11%'
        ORDER BY published_at
        """
    ).fetchall()
]

# one month = Oct 2026, three months = Aug-Oct via inspect Sep + stored counts
sep = inspect_client_report_data(conn, 1, period_year=2026, period_month=9)
oct_ = inspect_client_report_data(conn, 1, period_year=2026, period_month=10)
nov_insp = inspect_client_report_data(conn, 1, period_year=2026, period_month=11)

# platform counts Aug-Oct
by_month = {}
for ym in ("2026-08", "2026-09", "2026-10", "2026-11"):
    rows = conn.execute(
        """
        SELECT platform, count(*) AS n,
               min(published_at) AS oldest, max(published_at) AS newest
        FROM posts
        WHERE client_id=1 AND substr(published_at,1,7)=?
        GROUP BY platform
        """,
        (ym,),
    ).fetchall()
    by_month[ym] = [dict(r) for r in rows]

b1 = conn.execute(
    "SELECT id, code, content_kind, period_year, period_month, node_id FROM figma_planning_items WHERE client_id=1 AND code='B1'"
).fetchone()
suggestions = []
if b1:
    suggestions = suggest_post_matches(conn, 1, int(b1["id"]), limit=8)

# report 20 review/pdf
review = None
try:
    report_payload = get_report(conn, 1, 20)
    report_row = report_payload.get("report") or report_payload
    review = get_review_for_report(conn, 1, report_row)
except Exception as exc:
    review = {"error": str(exc)}

pdf_candidates = list(Path("data").rglob("*20*.pdf"))[:20]
review_db = None
try:
    rev_row = conn.execute("SELECT * FROM client_report_reviews WHERE report_id=20").fetchone()
    review_db = dict(rev_row) if rev_row else None
except Exception as exc:
    review_db = {"error": str(exc)}

out = {
    "client_sync": client,
    "november_posts": nov,
    "coverage": {
        "sep": {
            "posts_by_platform": (sep.get("data_coverage") or {}).get("posts_by_platform"),
            "coverage_label": (sep.get("data_coverage") or {}).get("coverage_label"),
            "linkedin_note": (sep.get("data_coverage") or {}).get("linkedin_note"),
            "meta_sync": (sep.get("data_coverage") or {}).get("meta_sync"),
        },
        "oct": {
            "posts_by_platform": (oct_.get("data_coverage") or {}).get("posts_by_platform"),
            "coverage_label": (oct_.get("data_coverage") or {}).get("coverage_label"),
        },
        "nov": {
            "posts_by_platform": (nov_insp.get("data_coverage") or {}).get("posts_by_platform"),
            "coverage_label": (nov_insp.get("data_coverage") or {}).get("coverage_label"),
        },
        "by_month_platform": by_month,
    },
    "figma_b1": {
        "item": dict(b1) if b1 else None,
        "suggestions": suggestions,
    },
    "report_20_review": review,
    "report_20_review_db": review_db,
    "pdf_files": [str(p) for p in pdf_candidates],
}

Path("data/imports/redrock/_qa_after_sync_coverage_b1.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(json.dumps(out, indent=2, ensure_ascii=False)[:6000])
conn.close()
