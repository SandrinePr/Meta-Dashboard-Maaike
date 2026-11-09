import json
from pathlib import Path

from maaike.db import transaction
from maaike.reports import ensure_report_tables

db = Path(r"c:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock.db")
with transaction(db) as conn:
    ensure_report_tables(conn)
    row = conn.execute(
        "SELECT input_snapshot_json, sources_json FROM client_reports WHERE id = 12"
    ).fetchone()
    snap = json.loads(row["input_snapshot_json"] or "{}")
    sources = list(snap.get("sources") or [])
    for s in sources:
        if "workflow-editing" in str(s.get("url") or ""):
            extra = (
                " HTTP-extractie leverde slechts ~9 tekens (JS-shell); "
                "bevinding steunt deels op zoeksnippet, niet op volle paginatekst."
            )
            if "JS-shell" not in str(s.get("limitations") or ""):
                s["limitations"] = ((s.get("limitations") or "") + extra).strip()
            s["certainty"] = "bevestigd (officieel) maar fragment dun via HTTP"
    snap["sources"] = sources
    conn.execute(
        """
        UPDATE client_reports
        SET input_snapshot_json = ?, sources_json = ?, updated_at = datetime('now')
        WHERE id = 12
        """,
        (json.dumps(snap, ensure_ascii=False), json.dumps(sources, ensure_ascii=False)),
    )
    print(
        "ok",
        next(
            len(s.get("excerpt") or "")
            for s in sources
            if "workflow-editing" in str(s.get("url") or "")
        ),
    )
