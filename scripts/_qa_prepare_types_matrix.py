"""Prepare carousel #16 and reel #8 inventory (no paid calls)."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.db import transaction
from maaike.post_analysis_workflow import inventory_for_post, prepare_post_analysis

out = {"paid_calls": False, "posts": {}}
with transaction() as conn:
    for post_id, label in ((16, "carousel"), (8, "reel"), (31, "image")):
        inv = inventory_for_post(conn, 1, post_id)
        prep = prepare_post_analysis(conn, 1, post_id, download_media=True)
        out["posts"][label] = {
            "post_id": post_id,
            "analysis_id": prep["analysis_id"],
            "role": inv["analysis_role"],
            "inventory_limitations": inv["limitations"],
            "coverage": prep["media_prep"].get("coverage"),
            "images_for_model": prep["media_prep"].get("images_for_model"),
            "image_roles": prep["media_prep"].get("image_roles"),
            "full_video_to_model": prep["media_prep"].get("full_video_to_model"),
            "audio_to_model": prep["media_prep"].get("audio_to_model"),
            "media_source": prep["media_prep"].get("media_source"),
            "cost_estimate_usd": prep["cost_estimate_usd"],
            "media_for_model": prep.get("media_for_model"),
        }
    out["stories"] = {
        "present": False,
        "count": 0,
        "note": "No story posts in Red Rock QA DB.",
    }

Path("data/imports/redrock/_qa_prepare_types_matrix.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(json.dumps(out, indent=2, ensure_ascii=False)[:5000])
