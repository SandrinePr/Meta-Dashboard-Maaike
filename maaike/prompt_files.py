"""Resolve Social Agent prompt directories for local + Render deploys.

Tracked copy lives under ``maaike/prompts/social_agent`` (committed).
Legacy/local SharePoint imports may still live under ``data/imports/...``
(gitignored). Prefer the tracked tree so Linux deploys have the files.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACKED_SOCIAL_AGENT_DIR = PROJECT_ROOT / "maaike" / "prompts" / "social_agent"
LEGACY_SOCIAL_AGENT_DIR = PROJECT_ROOT / "data" / "imports" / "redrock" / "social_agent"

# Exact filenames as shipped (Linux is case-sensitive).
ANALYSIS_PROMPT_FILES = (
    "Performance-analyse richtlijnen.txt",
    "Role - Algemene instructies.txt",
    "Kwaliteitsstandaard.txt",
)


def social_agent_dir() -> Path:
    """Directory that actually contains the required analysis prompt texts."""
    tracked_ready = all((TRACKED_SOCIAL_AGENT_DIR / name).is_file() for name in ANALYSIS_PROMPT_FILES)
    if tracked_ready:
        return TRACKED_SOCIAL_AGENT_DIR
    legacy_ready = all((LEGACY_SOCIAL_AGENT_DIR / name).is_file() for name in ANALYSIS_PROMPT_FILES)
    if legacy_ready:
        return LEGACY_SOCIAL_AGENT_DIR
    # Prefer tracked path in status messages even when incomplete.
    if TRACKED_SOCIAL_AGENT_DIR.is_dir():
        return TRACKED_SOCIAL_AGENT_DIR
    return LEGACY_SOCIAL_AGENT_DIR


def read_social_agent_text(name: str) -> str:
    path = social_agent_dir() / name
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def social_agent_status() -> dict:
    root = social_agent_dir()
    files = {}
    missing = []
    for name in ANALYSIS_PROMPT_FILES:
        path = root / name
        ok = path.is_file() and path.stat().st_size > 0
        files[name] = {
            "loaded": ok,
            "chars": path.stat().st_size if ok else 0,
            "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/") if path.exists() else name,
        }
        if not ok:
            missing.append(name)
    return {
        "root": str(root.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "tracked_root": str(TRACKED_SOCIAL_AGENT_DIR.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "legacy_root": str(LEGACY_SOCIAL_AGENT_DIR.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "using_tracked": root.resolve() == TRACKED_SOCIAL_AGENT_DIR.resolve(),
        "files": files,
        "missing_files": missing,
        "ready": not missing,
    }
