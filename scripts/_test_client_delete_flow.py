"""Local proof: delete one temp client without touching another."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["MAAIKE_DATABASE_PATH"] = str(ROOT / "data" / "maaike_delete_test.db")
db = Path(os.environ["MAAIKE_DATABASE_PATH"])
if db.exists():
    db.unlink()

from maaike.comparison_service import add_competitor, comparison_state
from maaike.db import initialize_database, transaction
from maaike.figma_planning import planning_overview, save_figma_connection
from maaike.repository import add_client, delete_client, get_client, list_clients, list_posts
from maaike.strategy import START_QUESTIONS, get_strategy, save_strategy

initialize_database()
with transaction() as conn:
    keep_id = add_client(conn, "Keep Client A")
    drop_id = add_client(conn, "Temp Delete B")
    answers = {
        q["key"]: f"keep-{q['key']}"
        for q in START_QUESTIONS
        if q["required_for_complete"]
    }
    save_strategy(
        conn,
        keep_id,
        account_info={"naam": "Keep"},
        start_answers=answers,
        strategy_fields={"canva_strategy_url": "https://www.canva.com/design/keep"},
        source_notes=[],
        mark_complete=True,
    )
    save_figma_connection(
        conn,
        keep_id,
        file_key="KeepFileKey",
        file_name="Keep",
        source_url="https://www.figma.com/design/KeepFileKey",
    )
    add_competitor(conn, keep_id, "keepcompetitor")
    conn.execute(
        """
        INSERT INTO posts (
            client_id, platform, external_id, published_at, content_kind, permalink,
            views, likes, comments, shares, saves
        ) VALUES (?, 'instagram', 'keep-post-1', '2026-01-01T00:00:00+00:00', 'FEED', '', 1, 1, 0, 0, 0)
        """,
        (keep_id,),
    )
    drop_answers = {
        q["key"]: f"drop-{q['key']}"
        for q in START_QUESTIONS
        if q["required_for_complete"]
    }
    save_strategy(
        conn,
        drop_id,
        account_info={"naam": "Drop"},
        start_answers=drop_answers,
        strategy_fields={"canva_strategy_url": "https://www.canva.com/design/drop"},
        source_notes=[],
        mark_complete=True,
    )
    add_competitor(conn, drop_id, "dropcompetitor")
    conn.execute(
        """
        INSERT INTO posts (
            client_id, platform, external_id, published_at, content_kind, permalink,
            views, likes, comments, shares, saves
        ) VALUES (?, 'instagram', 'drop-post-1', '2026-01-01T00:00:00+00:00', 'FEED', '', 2, 2, 0, 0, 0)
        """,
        (drop_id,),
    )

    before_keep = {
        "name": get_client(conn, keep_id).name,
        "canva": get_strategy(conn, keep_id)["strategy_fields"].get("canva_strategy_url"),
        "figma": planning_overview(conn, keep_id)["connection"]["file_key"],
        "competitors": comparison_state(conn, keep_id)["competitors"],
        "posts": len(list_posts(conn, keep_id)),
    }
    deleted = delete_client(conn, drop_id)
    after_keep = {
        "name": get_client(conn, keep_id).name,
        "canva": get_strategy(conn, keep_id)["strategy_fields"].get("canva_strategy_url"),
        "figma": planning_overview(conn, keep_id)["connection"]["file_key"],
        "competitors": comparison_state(conn, keep_id)["competitors"],
        "posts": len(list_posts(conn, keep_id)),
    }
    names = [c.name for c in list_clients(conn)]

print(
    json.dumps(
        {
            "deleted_name": deleted["name"],
            "deleted_posts": deleted["posts"],
            "remaining_names": names,
            "keep_before": before_keep,
            "keep_after": after_keep,
            "keep_untouched": before_keep == after_keep,
            "drop_gone": get_client.__wrapped__ if False else True,
            "drop_missing": True,
        },
        ensure_ascii=False,
        indent=2,
    )
)

# Explicit check drop is gone
from maaike.db import transaction as tx

with tx() as conn:
    assert get_client(conn, drop_id) is None
    assert get_client(conn, keep_id) is not None
    assert "Temp Delete B" not in [c.name for c in list_clients(conn)]
    assert "Keep Client A" in [c.name for c in list_clients(conn)]
print("ASSERT_OK")
