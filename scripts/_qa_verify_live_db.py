import os
from maaike.db import connect

print("env", os.getenv("MAAIKE_DATABASE_PATH"))
c = connect()
print("db", c.execute("PRAGMA database_list").fetchone()[2])
print(
    "qa formats",
    [r[0] for r in c.execute("SELECT name FROM content_formats WHERE client_id=4").fetchall()],
)
print("links", c.execute("SELECT COUNT(*) FROM post_import_links").fetchone()[0])
print("rr formats", c.execute("SELECT COUNT(*) FROM content_formats WHERE client_id=1").fetchone()[0])
print("reports", c.execute("SELECT COUNT(*) FROM client_reports WHERE client_id=1").fetchone()[0])
