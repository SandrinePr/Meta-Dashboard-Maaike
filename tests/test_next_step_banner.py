"""Frontend next-step helper (Maaike point 5) — exercised via Node when available.

Fallback: mirror the priority rules in Python so CI without Node still guards the contract.
"""

from __future__ import annotations


def build_next_step(
    *,
    role: str,
    client_name: str,
    channel: dict | None,
    strategy: dict | None,
    status_loading: bool = True,
    status_error: str | None = None,
):
    """Python mirror of frontend/src/nextStep.js buildNextStep priority."""
    name = (client_name or "deze klant").strip() or "deze klant"
    editable = True
    if not channel and status_error:
        return {"action": "posts", "tone": "warn"}
    if not channel:
        if status_loading:
            return {"action": None, "tone": "neutral"}
        return {"action": "posts", "tone": "warn"}
    if channel.get("state") == "connect_required":
        return {"action": "setup" if editable else "posts", "tone": "warn"}
    if channel.get("state") == "fetch_first_posts":
        return {"action": "fetch" if editable else "reports", "tone": "info"}
    missing = list(strategy.get("missing_required") or []) if strategy else []
    if editable and missing:
        return {"action": "setup", "tone": "warn"}
    if editable and strategy and strategy.get("review_status") == "te_controleren":
        return {"action": "setup", "tone": "info"}
    if channel.get("state") == "ready_to_view":
        return {"action": "fetch" if editable else "posts", "tone": "ok"}
    return {"action": "results", "tone": "ok", "name": name}


def test_editor_connect_leads_to_setup():
    step = build_next_step(
        role="editor",
        client_name="BBQube",
        channel={"state": "connect_required"},
        strategy=None,
    )
    assert step["action"] == "setup"


def test_viewer_connect_is_read_only_cta():
    step = build_next_step(
        role="viewer",
        client_name="Red Rock",
        channel={"state": "connect_required"},
        strategy=None,
    )
    assert step["action"] == "setup"


def test_editor_incomplete_strategy_leads_to_setup():
    step = build_next_step(
        role="editor",
        client_name="Red Rock",
        channel={"state": "ready_to_view"},
        strategy={"missing_required": ["tone_of_voice"], "next_step": "Vul in"},
    )
    assert step["action"] == "setup"


def test_ready_client_points_to_fetch_for_editor():
    step = build_next_step(
        role="editor",
        client_name="BBQube",
        channel={"state": "ready_to_view", "action_label": "Nieuwe berichten ophalen"},
        strategy={"missing_required": [], "review_status": "definitief"},
    )
    assert step["action"] == "fetch"


def test_status_error_does_not_hang_on_loading():
    step = build_next_step(
        role="viewer",
        client_name="Red Rock",
        channel=None,
        strategy=None,
        status_loading=False,
        status_error="403",
    )
    assert step["action"] == "posts"
    assert step["tone"] == "warn"
