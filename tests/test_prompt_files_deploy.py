"""Tracked Social Agent prompts must load without data/imports (Render)."""

from __future__ import annotations

from maaike.claude_analysis import load_analysis_prompt_bundle
from maaike.prompt_files import ANALYSIS_PROMPT_FILES, social_agent_dir, social_agent_status
from maaike.report_planning import task_ai_providers
from maaike.report_prompts import load_report_instruction_bundle


def test_tracked_analysis_prompts_ready():
    status = social_agent_status()
    assert status["ready"] is True, status["missing_files"]
    assert status["using_tracked"] is True
    root = social_agent_dir()
    assert "maaike/prompts/social_agent" in str(root).replace("\\", "/")
    for name in ANALYSIS_PROMPT_FILES:
        assert (root / name).is_file()

    bundle = load_analysis_prompt_bundle()
    assert bundle["ready"] is True
    assert bundle["missing_files"] == []
    for name in ANALYSIS_PROMPT_FILES:
        assert bundle["files"][name]["loaded"] is True
        assert bundle["files"][name]["chars"] > 100


def test_report_instruction_bundle_loads_primary_texts():
    client = load_report_instruction_bundle("client")
    assert client["primary_loaded"] is True
    assert "Role - Algemene instructies.txt" not in (client.get("missing_instructions") or [])
    trend = load_report_instruction_bundle("trend")
    assert trend["primary_loaded"] is True


def test_task_providers_claude_posts_gemini_reports():
    providers = task_ai_providers()
    assert providers["post_analysis"]["primary"]["provider"] == "Anthropic Claude"
    assert providers["client_report"]["primary"]["provider"] == "Google Gemini Developer API"
    assert providers["trend_report"]["primary"]["provider"] == "Google Gemini Developer API"
