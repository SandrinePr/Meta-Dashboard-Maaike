from pathlib import Path
from maaike.db import transaction

db = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock.db")
with transaction(db) as conn:
    r = conn.execute(
        """
        SELECT id, title, status, period_year, period_month, planning_year, planning_month,
               linked_trend_report_id, report_type
        FROM client_reports WHERE id = 11
        """
    ).fetchone()
    print("report11", dict(r) if r else None)
    cols = [c[1] for c in conn.execute("PRAGMA table_info(client_report_sources)").fetchall()]
    print("source_cols", cols)
    c = conn.execute(
        "SELECT id, name FROM clients WHERE name = 'Red Rock' COLLATE NOCASE"
    ).fetchone()
    print("client", dict(c) if c else None)
