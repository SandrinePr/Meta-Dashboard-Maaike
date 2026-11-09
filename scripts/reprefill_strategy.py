from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maaike.db import initialize_database, transaction
from maaike.strategy import prefill_red_rock_from_sources

initialize_database()
with transaction() as conn:
    cid = conn.execute(
        "SELECT id FROM clients WHERE name = ? COLLATE NOCASE",
        ("Red Rock",),
    ).fetchone()[0]
    strategy = prefill_red_rock_from_sources(conn, cid, ROOT / "data" / "imports" / "redrock")
    answered = sorted(k for k, v in strategy["start_answers"].items() if str(v).strip())
    print("answered", answered)
    print("missing", strategy["missing_required"])
    print("tov", (strategy["start_answers"].get("tone_of_voice") or "")[:240])
