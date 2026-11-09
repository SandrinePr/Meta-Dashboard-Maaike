"""Fetch a small content sample. Prints availability only, never tokens or media URLs."""

from __future__ import annotations

import json

from config import get_settings
from db.comparison_repository import DEFAULT_OWN_EXTERNAL_ID
from db.database import get_connection, initialize_database
from meta.client import MetaClient
from sync.content_sample import run_content_sample


def main() -> None:
    initialize_database()
    settings = get_settings()
    host_id = settings.meta_instagram_business_account_id or DEFAULT_OWN_EXTERNAL_ID
    client = MetaClient.from_settings()
    with get_connection() as conn:
        report = run_content_sample(conn, client, host_id=host_id)
        conn.commit()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
