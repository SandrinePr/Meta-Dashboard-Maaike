"""Prepare post 31 using the known good trial cache image — no paid call."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.ai_trial_media import prepare_post_media
from maaike.db import transaction
from maaike.post_analysis_workflow import prepare_post_analysis

# Temporarily monkeypatch local_paths to prefer real cache image over tiny stub upload.
CACHE = {
    "index": 1,
    "kind": "image",
    "path": "data/ai_trial_media/client_1/post_31/part_01.jpg",
    "bytes": 624599,
}

import maaike.post_analysis_workflow as paw

original = paw.prepare_post_analysis


def patched(conn, client_id, post_id, *, download_media=True):
    # Force cache asset for this QA prepare.
    import maaike.post_media_upload as pmu

    real = pmu.local_paths_for_analysis

    def fake_local(conn2, cid, pid):
        if cid == 1 and pid == 31:
            return [CACHE]
        return real(conn2, cid, pid)

    pmu.local_paths_for_analysis = fake_local
    try:
        return original(conn, client_id, post_id, download_media=download_media)
    finally:
        pmu.local_paths_for_analysis = real


with transaction() as conn:
    # Also verify prepare_post_media directly
    direct = prepare_post_media(
        client_id=1,
        post_id=31,
        role="image",
        content_kind="image",
        media_urls=[],
        local_assets=[CACHE],
    )
    result = patched(conn, 1, 31, download_media=True)

out = {
    "direct_coverage": direct.get("coverage"),
    "direct_images": direct.get("images_for_model"),
    "paid_call": result.get("paid_call"),
    "analysis_id": result.get("analysis_id"),
    "media_prep": result.get("media_prep"),
    "media_for_model": result.get("media_for_model"),
    "cost_estimate_usd": result.get("cost_estimate_usd"),
}
Path("data/imports/redrock/_qa_prepare_post31_cache.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(json.dumps(out, indent=2, ensure_ascii=False))
