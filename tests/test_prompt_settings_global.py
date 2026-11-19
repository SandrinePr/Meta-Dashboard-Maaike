"""Global prompt catalog + composition for all clients."""

from __future__ import annotations

import sqlite3

from maaike.prompt_settings import (
    PROMPT_KEYS,
    active_prompt_text,
    list_prompt_settings,
    resolve_composed_post_prompt,
    resolve_report_system_prompt,
    save_prompt_override,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_list_includes_inventory_keys() -> None:
    conn = _conn()
    payload = list_prompt_settings(conn)
    keys = [p["prompt_key"] for p in payload["prompts"]]
    for key in (
        "performance_analysis",
        "general_instructions",
        "quality_standard",
        "post_analysis",
        "trend_report",
        "client_report",
    ):
        assert key in keys
    assert payload["scope"] == "all_clients"
    assert set(PROMPT_KEYS) == set(keys)


def test_component_override_used_in_post_composition() -> None:
    conn = _conn()
    save_prompt_override(
        conn,
        "performance_analysis",
        body_text="COMPONENT PERFORMANCE MARKER XYZ",
        version_tag="perf-test-1",
        updated_by="test",
    )
    resolved = resolve_composed_post_prompt(conn)
    assert "COMPONENT PERFORMANCE MARKER XYZ" in resolved["system_text"]
    assert "perf-test-1" in resolved["prompt_version"]
    assert resolved["source"] == "dashboard_override"
    assert "performance_analysis" in resolved["composition"]


def test_full_post_override_wins_and_flags_conflict() -> None:
    conn = _conn()
    save_prompt_override(
        conn,
        "performance_analysis",
        body_text="COMPONENT SHOULD BE IGNORED",
        version_tag="perf-x",
        updated_by="test",
    )
    save_prompt_override(
        conn,
        "post_analysis",
        body_text="FULL OVERRIDE ONLY",
        version_tag="full-1",
        updated_by="test",
    )
    resolved = resolve_composed_post_prompt(conn)
    assert resolved["system_text"] == "FULL OVERRIDE ONLY"
    assert resolved["conflict_with_components"] is True
    listed = list_prompt_settings(conn)
    assert listed["conflicts"]


def test_same_prompt_for_any_client_context() -> None:
    """Prompt body is global; client context is not stored in prompt_settings."""
    conn = _conn()
    save_prompt_override(
        conn,
        "general_instructions",
        body_text="GLOBAL ROLE TEXT",
        version_tag="role-1",
        updated_by="Maaike",
    )
    a = active_prompt_text(conn, "general_instructions")
    b = active_prompt_text(conn, "general_instructions")
    assert a["body_text"] == b["body_text"] == "GLOBAL ROLE TEXT"
    report = resolve_report_system_prompt(conn, "trend")
    assert "GLOBAL ROLE TEXT" in report["system_text"]
    assert "role-1" in report["prompt_version"]
