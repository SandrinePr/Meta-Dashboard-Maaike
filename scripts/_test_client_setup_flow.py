"""Local proof: new client setup data + existing client preservation."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["MAAIKE_DATABASE_PATH"] = str(ROOT / "data" / "maaike_setup_test.db")
db = Path(os.environ["MAAIKE_DATABASE_PATH"])
if db.exists():
    db.unlink()

from maaike.comparison_service import add_competitor, comparison_state
from maaike.db import initialize_database, transaction
from maaike.figma_planning import planning_overview, save_figma_connection
from maaike.repository import add_client, get_client
from maaike.strategy import START_QUESTIONS, get_strategy, save_strategy, upsert_target

initialize_database()
with transaction() as conn:
    c1 = add_client(conn, "BBQube")
    answers = {
        q["key"]: f"antwoord {q['key']}"
        for q in START_QUESTIONS
        if q["required_for_complete"]
    }
    save_strategy(
        conn,
        c1,
        account_info={"naam": "BBQube"},
        start_answers=answers,
        strategy_fields={"canva_strategy_url": "https://www.canva.com/design/old"},
        source_notes=[],
        mark_complete=True,
    )
    save_figma_connection(
        conn,
        c1,
        file_key="ExistingKey123",
        file_name="BBQube",
        source_url="https://www.figma.com/design/ExistingKey123",
    )
    add_competitor(conn, c1, "oldcompetitor")
    before = {
        "name": get_client(conn, c1).name,
        "canva": get_strategy(conn, c1)["strategy_fields"].get("canva_strategy_url"),
        "figma": planning_overview(conn, c1)["connection"]["file_key"],
        "competitors": comparison_state(conn, c1)["competitors"],
        "completed": get_strategy(conn, c1)["completed_at"] is not None,
    }

    c2 = add_client(conn, "Setup Test Klant")
    answers2 = {
        q["key"]: f"test {q['key']}"
        for q in START_QUESTIONS
        if q["required_for_complete"]
    }
    save_strategy(
        conn,
        c2,
        account_info={"naam": "Setup Test Klant"},
        start_answers=answers2,
        strategy_fields={"canva_strategy_url": "https://www.canva.com/design/newtest"},
        source_notes=[],
        mark_complete=True,
    )
    save_figma_connection(
        conn,
        c2,
        file_key="NewFileKey456",
        file_name="",
        source_url="https://www.figma.com/design/NewFileKey456",
    )
    upsert_target(
        conn,
        c2,
        {
            "metric_name": "bereik",
            "platform": "instagram",
            "target_value": 1000,
            "unit": "views",
            "account_key": "",
            "target_kind": "absolute",
            "baseline_value": None,
            "period_year": 2026,
            "period_quarter": None,
            "notes": "",
        },
    )
    add_competitor(conn, c2, "nieuwconcurrent")

    after_existing = {
        "name": get_client(conn, c1).name,
        "canva": get_strategy(conn, c1)["strategy_fields"].get("canva_strategy_url"),
        "figma": planning_overview(conn, c1)["connection"]["file_key"],
        "competitors": comparison_state(conn, c1)["competitors"],
        "completed": get_strategy(conn, c1)["completed_at"] is not None,
    }
    new_state = {
        "name": get_client(conn, c2).name,
        "missing": get_strategy(conn, c2)["missing_required"],
        "canva": get_strategy(conn, c2)["strategy_fields"].get("canva_strategy_url"),
        "figma": planning_overview(conn, c2)["connection"]["file_key"],
        "competitors": comparison_state(conn, c2)["competitors"],
        "targets": len(get_strategy(conn, c2)["targets"]),
        "completed": get_strategy(conn, c2)["completed_at"] is not None,
    }

    # Later edit existing client without wiping sibling data.
    save_strategy(
        conn,
        c1,
        account_info={"naam": "BBQube"},
        start_answers=answers,
        strategy_fields={"canva_strategy_url": "https://www.canva.com/design/updated"},
        source_notes=[],
        mark_complete=False,
    )
    edited = {
        "canva": get_strategy(conn, c1)["strategy_fields"].get("canva_strategy_url"),
        "figma": planning_overview(conn, c1)["connection"]["file_key"],
        "competitors": comparison_state(conn, c1)["competitors"],
        "name": get_client(conn, c1).name,
    }

print(
    json.dumps(
        {
            "before": before,
            "after_existing": after_existing,
            "new_client": new_state,
            "edited_existing": edited,
            "preserve_ok": (
                before["name"] == after_existing["name"]
                and before["figma"] == after_existing["figma"] == edited["figma"]
                and before["competitors"] == after_existing["competitors"] == edited["competitors"]
                and edited["canva"].endswith("/updated")
            ),
            "new_ok": (
                new_state["name"] == "Setup Test Klant"
                and not new_state["missing"]
                and new_state["targets"] == 1
                and new_state["figma"] == "NewFileKey456"
                and "nieuwconcurrent" in new_state["competitors"]
                and new_state["completed"]
            ),
        },
        ensure_ascii=False,
        indent=2,
    )
)
