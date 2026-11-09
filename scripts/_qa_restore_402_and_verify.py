"""Restore post #402 / B1 after test link; verify #31 report attach + prompt wording."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["MAAIKE_DATABASE_PATH"] = str(
    Path(r"C:\RRO\Projects\AutomationDashboardMETA-Maaike\data\maaike_redrock_qa_demo.db")
)

from maaike.ai_trial_request import build_request_package
from maaike.db import transaction
from maaike.figma_planning import preview_link_to_post
from maaike.reports import inspect_client_report_data

out: dict = {"paid_calls": False}

with transaction() as conn:
    # Restore previous state: unlink B1, clear editorial filled only for the test link
    conn.execute(
        """
        UPDATE figma_planning_items
        SET linked_post_id = NULL, link_status = 'unlinked', updated_at = datetime('now')
        WHERE id = 1 AND client_id = 1 AND linked_post_id = 402
        """
    )
    conn.execute("DELETE FROM post_editorial WHERE post_id = 402")

    b1 = dict(
        conn.execute(
            "SELECT id, code, linked_post_id, link_status, content_kind FROM figma_planning_items WHERE id=1"
        ).fetchone()
    )
    ed = conn.execute("SELECT * FROM post_editorial WHERE post_id=402").fetchone()
    out["restored"] = {"b1": b1, "editorial_402": dict(ed) if ed else None}

    preview = preview_link_to_post(conn, 1, 1, 402)
    out["preview_b1_402"] = {
        "display": (preview.get("content_kind_compare") or {}).get("display"),
        "mismatch": (preview.get("content_kind_compare") or {}).get("mismatch"),
        "changes": preview.get("changes"),
        "requires_explicit_accept": (preview.get("content_kind_compare") or {}).get(
            "requires_explicit_accept"
        ),
    }

    # #31 corrected insight still attached for June report input
    preview_report = inspect_client_report_data(conn, 1, period_year=2026, period_month=6)
    hit = next((p for p in (preview_report.get("posts") or []) if p.get("post_id") == 31), None)
    ai = (hit or {}).get("ai_analysis") or {}
    out["post31_report"] = {
        "ai_id": ai.get("id"),
        "insight_prefix": (ai.get("insight_text") or "")[:100],
        "kept_qa_review": "QA-review t.o.v. beeld" in (ai.get("insight_text") or ""),
        "kept_correction_note": "ten onrechte bank/planten" in (ai.get("insight_text") or ""),
    }

    # Prompt instruction regression (no paid call)
    pkg = build_request_package(
        role="image",
        post={
            "id": 31,
            "platform": "instagram",
            "content_kind": "image",
            "permalink": "https://example",
            "published_at": "2026-06-05",
            "caption": "test",
            "media_urls": [],
        },
        media_prep={
            "coverage": "image_and_caption",
            "images_for_model": [{"role": "image", "path": "x.jpg", "bytes": 1}],
            "full_video_to_model": False,
            "audio_to_model": False,
        },
        all_formats=[],
        pillars=["Cases"],
        metrics={"likes": 0, "comments": 0},
    )
    system = pkg.get("system_text") or ""
    user = pkg.get("user_text") or ""
    out["prompt_checks"] = {
        "system_has_three_layers": "Zichtbare details" in system and "Meetbare cijfers" in system,
        "system_blocks_causal_leap": "bewijzen niet dat het format" in system,
        "user_has_good_example": "Hypothese: een carrousel of reel" in user,
        "user_marks_bad_example": "weinig interactie, dus het statische beeld" in user,
    }

Path("data/imports/redrock/_qa_restore_402_and_verify.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(json.dumps(out, indent=2, ensure_ascii=False))
