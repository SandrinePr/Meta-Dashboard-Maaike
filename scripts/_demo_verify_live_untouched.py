from pathlib import Path
from maaike.db import connect
from maaike.migrate import apply_migrations

live = connect(Path("data/maaike_redrock.db"))
apply_migrations(live)
print("live11", dict(live.execute("SELECT id,status,linked_trend_report_id FROM client_reports WHERE id=11").fetchone()))
print("live15", dict(live.execute("SELECT id,status FROM client_reports WHERE id=15").fetchone()))
print("live16", live.execute("SELECT id FROM client_reports WHERE id=16").fetchone())
qa = connect(Path("data/maaike_redrock_qa_demo.db"))
apply_migrations(qa)
print("qa16", dict(qa.execute("SELECT id,status,is_mock FROM client_reports WHERE id=16").fetchone()))
