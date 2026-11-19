"""Editable dashboard prompts for post analysis, trend and client reports.

File-based Social Agent instructions remain the default. Overrides are stored
in SQLite so Maaike can tweak wording without redeploying. Each generated
report keeps the prompt_version used at execution time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

PROMPT_KEYS = ("post_analysis", "trend_report", "client_report")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def ensure_prompt_settings_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS maaike_prompt_settings (
            prompt_key TEXT PRIMARY KEY,
            label TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            version_tag TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT ''
        )
        """
    )


def _default_bundle(prompt_key: str) -> dict[str, Any]:
    if prompt_key == "post_analysis":
        from maaike.claude_analysis import PROMPT_VERSION, load_analysis_prompt_bundle

        bundle = load_analysis_prompt_bundle()
        return {
            "prompt_key": prompt_key,
            "label": "Postanalyse",
            "version_tag": PROMPT_VERSION,
            "body_text": (bundle.get("system_text") or bundle.get("system") or "")[:20000],
            "source": "files",
            "editable": True,
            "files": bundle.get("files") or {},
            "ready": bool(bundle.get("ready")),
            "missing_files": bundle.get("missing_files") or [],
        }
    if prompt_key in {"trend_report", "client_report"}:
        from maaike.report_prompts import PROMPT_VERSION, load_report_instruction_bundle

        report_type = "trend" if prompt_key == "trend_report" else "client"
        bundle = load_report_instruction_bundle(report_type)
        return {
            "prompt_key": prompt_key,
            "label": "Trendrapport" if report_type == "trend" else "Klantrapport",
            "version_tag": PROMPT_VERSION,
            "body_text": (bundle.get("system_text") or "")[:20000],
            "source": "files",
            "editable": True,
            "primary_file": bundle.get("primary_file"),
            "missing_instructions": bundle.get("missing_instructions") or [],
            "ready": not bool(bundle.get("missing_instructions")),
        }
    raise ValueError(f"Onbekende prompt_key: {prompt_key}")


def list_prompt_settings(conn) -> dict[str, Any]:
    ensure_prompt_settings_table(conn)
    items = []
    for key in PROMPT_KEYS:
        base = _default_bundle(key)
        row = conn.execute(
            "SELECT body_text, version_tag, updated_at, updated_by FROM maaike_prompt_settings WHERE prompt_key = ?",
            (key,),
        ).fetchone()
        if row and str(row["body_text"] or "").strip():
            base["body_text"] = str(row["body_text"])
            base["version_tag"] = str(row["version_tag"] or base["version_tag"])
            base["source"] = "dashboard_override"
            base["updated_at"] = row["updated_at"]
            base["updated_by"] = row["updated_by"] or ""
        else:
            base["updated_at"] = None
            base["updated_by"] = ""
        items.append(base)
    return {
        "prompts": items,
        "note": (
            "Overrides gelden voor nieuwe runs. Bestaande rapporten behouden hun "
            "opgeslagen prompt_version."
        ),
        "auto_execute_in_production": False,
    }


def save_prompt_override(
    conn,
    prompt_key: str,
    *,
    body_text: str,
    version_tag: str = "",
    updated_by: str = "",
) -> dict[str, Any]:
    if prompt_key not in PROMPT_KEYS:
        raise ValueError(f"Onbekende prompt_key: {prompt_key}")
    ensure_prompt_settings_table(conn)
    base = _default_bundle(prompt_key)
    text = str(body_text or "").strip()
    if not text:
        raise ValueError("Prompttekst mag niet leeg zijn.")
    tag = str(version_tag or "").strip() or f"{base['version_tag']}-custom"
    now = _now()
    conn.execute(
        """
        INSERT INTO maaike_prompt_settings (prompt_key, label, body_text, version_tag, updated_at, updated_by)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(prompt_key) DO UPDATE SET
            body_text = excluded.body_text,
            version_tag = excluded.version_tag,
            updated_at = excluded.updated_at,
            updated_by = excluded.updated_by,
            label = excluded.label
        """,
        (prompt_key, base["label"], text, tag, now, str(updated_by or "").strip()),
    )
    return list_prompt_settings(conn)


def reset_prompt_override(conn, prompt_key: str) -> dict[str, Any]:
    if prompt_key not in PROMPT_KEYS:
        raise ValueError(f"Onbekende prompt_key: {prompt_key}")
    ensure_prompt_settings_table(conn)
    conn.execute("DELETE FROM maaike_prompt_settings WHERE prompt_key = ?", (prompt_key,))
    return list_prompt_settings(conn)


def active_prompt_text(conn, prompt_key: str) -> dict[str, Any]:
    """Return override body if present, else file default — for execution."""
    ensure_prompt_settings_table(conn)
    base = _default_bundle(prompt_key)
    row = conn.execute(
        "SELECT body_text, version_tag FROM maaike_prompt_settings WHERE prompt_key = ?",
        (prompt_key,),
    ).fetchone()
    if row and str(row["body_text"] or "").strip():
        return {
            "prompt_key": prompt_key,
            "body_text": str(row["body_text"]),
            "version_tag": str(row["version_tag"] or base["version_tag"]),
            "source": "dashboard_override",
        }
    return {
        "prompt_key": prompt_key,
        "body_text": base["body_text"],
        "version_tag": base["version_tag"],
        "source": "files",
    }


def dump_for_debug(conn) -> str:
    return json.dumps(list_prompt_settings(conn), ensure_ascii=False, indent=2)
