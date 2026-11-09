"""Prepare post 31 (image) using CDN or local trial cache — no paid call."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.db import transaction
from maaike.post_analysis_workflow import prepare_post_analysis

with transaction() as conn:
    result = prepare_post_analysis(conn, 1, 31, download_media=True)

out = {
    "post_id": 31,
    "content_kind": "image",
    "paid_call": result.get("paid_call"),
    "analysis_id": result.get("analysis_id"),
    "status": result.get("status"),
    "media_prep": result.get("media_prep"),
    "media_for_model": result.get("media_for_model"),
    "cost_estimate_usd": result.get("cost_estimate_usd"),
    "limitations": (result.get("inventory") or {}).get("limitations"),
}
Path("data/imports/redrock/_qa_prepare_post31.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(json.dumps(out, indent=2, ensure_ascii=False))
