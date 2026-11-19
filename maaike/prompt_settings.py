"""Global editable prompts for all clients (post feedback + reports).

File-based Social Agent instructions remain the default. Overrides live in
SQLite (and remote persist) so wording survives Render Free restarts. Each
analysis/report keeps the prompt_version used at execution time.

Client strategy, tone of voice and figures stay separate client context.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from maaike.prompt_files import ANALYSIS_PROMPT_FILES, read_social_agent_text

# Stable keys used by the dashboard and execution paths.
PROMPT_KEYS = (
    "performance_analysis",
    "general_instructions",
    "quality_standard",
    "post_analysis",
    "trend_report",
    "client_report",
)

PROMPT_META: dict[str, dict[str, str]] = {
    "performance_analysis": {
        "label": "Performance-analyse",
        "description": (
            "Richtlijnen voor postfeedback en performance-analyse. Wordt samengesteld "
            "met algemene instructies en kwaliteitsstandaard voor Claude-postfeedback, "
            "tenzij een volledige postfeedback-override actief is."
        ),
        "file": "Performance-analyse richtlijnen.txt",
        "used_for": "Postfeedback (Claude)",
    },
    "general_instructions": {
        "label": "Algemene instructies",
        "description": (
            "Rol en werkwijze voor Maaike. Geldt voor postfeedback én rapporten "
            "(tenzij een volledige rapport-override die tekst al meeneemt)."
        ),
        "file": "Role - Algemene instructies.txt",
        "used_for": "Postfeedback + trend-/klantrapporten",
    },
    "quality_standard": {
        "label": "Kwaliteitsstandaard",
        "description": (
            "Kwaliteitseisen en formulering. Geldt voor postfeedback én rapporten."
        ),
        "file": "Kwaliteitsstandaard.txt",
        "used_for": "Postfeedback + trend-/klantrapporten",
    },
    "post_analysis": {
        "label": "Postfeedback (volledige override)",
        "description": (
            "Optionele volledige systeemprompt voor Claude-postfeedback. "
            "Als deze override gevuld is, wint hij van de drie componentprompts hierboven. "
            "Leeg laten / resetten om componentprompts te gebruiken."
        ),
        "file": "",
        "used_for": "Postfeedback (Claude) — override",
    },
    "trend_report": {
        "label": "Trendrapport",
        "description": (
            "Volledige systeeminstructie voor trendrapporten (Gemini). "
            "Klantcontext (strategie, cijfers) blijft apart in de gebruikersinvoer."
        ),
        "file": "Trendrapport - opbouw en aanpak.txt",
        "used_for": "Trendrapport (Gemini)",
    },
    "client_report": {
        "label": "Klantrapport",
        "description": (
            "Volledige systeeminstructie voor klantrapporten (Gemini). "
            "Strategie, tone of voice en cijfers van de klant blijven aparte klantcontext."
        ),
        "file": "Klantrapport - opbouw en aanpak.txt",
        "used_for": "Klantrapport (Gemini)",
    },
}


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


def _file_body(prompt_key: str) -> str:
    meta = PROMPT_META[prompt_key]
    name = meta.get("file") or ""
    if not name:
        return ""
    return read_social_agent_text(name)


def _default_bundle(prompt_key: str) -> dict[str, Any]:
    if prompt_key not in PROMPT_META:
        raise ValueError(f"Onbekende prompt_key: {prompt_key}")
    meta = PROMPT_META[prompt_key]
    if prompt_key == "post_analysis":
        from maaike.claude_analysis import PROMPT_VERSION, load_analysis_prompt_bundle

        bundle = load_analysis_prompt_bundle()
        return {
            "prompt_key": prompt_key,
            "label": meta["label"],
            "description": meta["description"],
            "used_for": meta["used_for"],
            "version_tag": PROMPT_VERSION,
            "body_text": (bundle.get("system_text") or "")[:50000],
            "source": "files_composed",
            "editable": True,
            "optional_override": True,
            "ready": bool(bundle.get("ready")),
            "missing_files": bundle.get("missing_files") or [],
            "file_name": "",
        }
    if prompt_key in {"trend_report", "client_report"}:
        from maaike.report_prompts import PROMPT_VERSION, load_report_instruction_bundle

        report_type = "trend" if prompt_key == "trend_report" else "client"
        bundle = load_report_instruction_bundle(report_type)
        return {
            "prompt_key": prompt_key,
            "label": meta["label"],
            "description": meta["description"],
            "used_for": meta["used_for"],
            "version_tag": PROMPT_VERSION,
            "body_text": (bundle.get("system_text") or "")[:50000],
            "source": "files_composed",
            "editable": True,
            "optional_override": False,
            "primary_file": bundle.get("primary_file"),
            "missing_instructions": bundle.get("missing_instructions") or [],
            "ready": not bool(bundle.get("missing_instructions")),
            "file_name": meta.get("file") or "",
        }

    body = _file_body(prompt_key)
    return {
        "prompt_key": prompt_key,
        "label": meta["label"],
        "description": meta["description"],
        "used_for": meta["used_for"],
        "version_tag": f"file-{prompt_key}",
        "body_text": body[:50000],
        "source": "files",
        "editable": True,
        "optional_override": False,
        "ready": bool(body.strip()),
        "missing_files": [] if body.strip() else [meta.get("file") or prompt_key],
        "file_name": meta.get("file") or "",
    }


def _row_override(conn, prompt_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT body_text, version_tag, updated_at, updated_by, label FROM maaike_prompt_settings WHERE prompt_key = ?",
        (prompt_key,),
    ).fetchone()
    if not row or not str(row["body_text"] or "").strip():
        return None
    return {
        "body_text": str(row["body_text"]),
        "version_tag": str(row["version_tag"] or ""),
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"] or "",
        "label": row["label"] or "",
    }


def list_prompt_settings(conn) -> dict[str, Any]:
    ensure_prompt_settings_table(conn)
    items = []
    conflicts: list[str] = []
    post_override = _row_override(conn, "post_analysis")
    component_overrides = [
        key
        for key in ("performance_analysis", "general_instructions", "quality_standard")
        if _row_override(conn, key)
    ]
    if post_override and component_overrides:
        conflicts.append(
            "Volledige postfeedback-override is actief én er zijn componentprompts opgeslagen. "
            "Claude gebruikt nu de volledige override. Reset ‘Postfeedback (volledige override)’ "
            "om de componentprompts te gebruiken, of bewerk alleen de override."
        )

    for key in PROMPT_KEYS:
        base = _default_bundle(key)
        row = _row_override(conn, key)
        if row:
            base["body_text"] = row["body_text"]
            base["version_tag"] = row["version_tag"] or base["version_tag"]
            base["source"] = "dashboard_override"
            base["updated_at"] = row["updated_at"]
            base["updated_by"] = row["updated_by"]
        else:
            base["updated_at"] = None
            base["updated_by"] = ""
        items.append(base)

    return {
        "prompts": items,
        "scope": "all_clients",
        "conflicts": conflicts,
        "analysis_component_files": list(ANALYSIS_PROMPT_FILES),
        "note": (
            "Deze prompts gelden voor alle klanten. Strategie, tone of voice en cijfers "
            "blijven klantspecifieke context bij elke run. Bestaande rapporten/analyses "
            "behouden hun opgeslagen prompt_version."
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
    """Return override body if present, else file/composed default — for execution."""
    ensure_prompt_settings_table(conn)
    if prompt_key not in PROMPT_KEYS:
        raise ValueError(f"Onbekende prompt_key: {prompt_key}")
    base = _default_bundle(prompt_key)
    row = _row_override(conn, prompt_key)
    if row:
        return {
            "prompt_key": prompt_key,
            "body_text": row["body_text"],
            "version_tag": row["version_tag"] or base["version_tag"],
            "source": "dashboard_override",
            "updated_at": row["updated_at"],
        }
    return {
        "prompt_key": prompt_key,
        "body_text": base["body_text"],
        "version_tag": base["version_tag"],
        "source": base.get("source") or "files",
        "updated_at": None,
    }


def _component_text(conn, prompt_key: str) -> tuple[str, str, str]:
    """body, version_tag, source for a component key."""
    active = active_prompt_text(conn, prompt_key)
    return (
        str(active.get("body_text") or ""),
        str(active.get("version_tag") or ""),
        str(active.get("source") or "files"),
    )


def resolve_composed_post_prompt(conn) -> dict[str, Any]:
    """System text for Claude post feedback.

    Prefer a full ``post_analysis`` override when present (legacy / explicit).
    Otherwise compose performance + general + quality component prompts.
    """
    ensure_prompt_settings_table(conn)
    full = _row_override(conn, "post_analysis")
    if full:
        return {
            "system_text": full["body_text"],
            "prompt_version": full["version_tag"] or "post_analysis-override",
            "source": "dashboard_override",
            "composition": ["post_analysis"],
            "conflict_with_components": bool(
                _row_override(conn, "performance_analysis")
                or _row_override(conn, "general_instructions")
                or _row_override(conn, "quality_standard")
            ),
        }

    perf_body, perf_ver, perf_src = _component_text(conn, "performance_analysis")
    role_body, role_ver, role_src = _component_text(conn, "general_instructions")
    qual_body, qual_ver, qual_src = _component_text(conn, "quality_standard")
    parts = [
        "Je werkt voor Red Rock Agency. Gebruik uitsluitend de meegeleverde instructies en postgegevens.",
        "Verzin geen cijfers. Ontbrekende metrics zijn onbekend, niet 0.",
        "Lever insight, actie en beoordeling (Goed/Gemiddeld/Slecht) volgens de richtlijnen.",
        "Als vergelijkingsposts, format-tab of periodeoverzicht ontbreken: benoem die beperking "
        "expliciet en trek geen ongefundeerde patroonconclusies.",
        "",
        "=== Performance-analyse richtlijnen ===",
        perf_body or "(ONTBREEKT: Performance-analyse)",
        "",
        "=== Role - Algemene instructies ===",
        role_body or "(ONTBREEKT: Algemene instructies)",
        "",
        "=== Kwaliteitsstandaard ===",
        qual_body or "(ONTBREEKT: Kwaliteitsstandaard)",
        "",
    ]
    versions = [v for v in (perf_ver, role_ver, qual_ver) if v]
    sources = {perf_src, role_src, qual_src}
    source = "dashboard_override" if "dashboard_override" in sources else "files_composed"
    version = "+".join(versions) if versions else "maaike-post-composed"
    return {
        "system_text": "\n".join(parts),
        "prompt_version": version[:180],
        "source": source,
        "composition": ["performance_analysis", "general_instructions", "quality_standard"],
        "conflict_with_components": False,
    }


def resolve_report_system_prompt(conn, report_type: str) -> dict[str, Any]:
    """System text for Gemini trend/client reports with optional dashboard overrides."""
    from maaike.report_prompts import PROMPT_VERSION, load_report_instruction_bundle

    ensure_prompt_settings_table(conn)
    key = "trend_report" if report_type == "trend" else "client_report"
    full = _row_override(conn, key)
    if full:
        return {
            "system_text": full["body_text"],
            "prompt_version": full["version_tag"] or PROMPT_VERSION,
            "source": "dashboard_override",
            "composition": [key],
        }

    # Rebuild file bundle but swap role/quality from component overrides when set.
    bundle = load_report_instruction_bundle(report_type)
    role_body, role_ver, role_src = _component_text(conn, "general_instructions")
    qual_body, qual_ver, qual_src = _component_text(conn, "quality_standard")
    system = str(bundle.get("system_text") or "")
    # Replace file sections if component overrides exist.
    if role_src == "dashboard_override" and role_body:
        # Best-effort: append override block so instructions stay visible.
        system = (
            system
            + "\n\n=== Role - Algemene instructies (dashboard override) ===\n"
            + role_body[:12000]
        )
    if qual_src == "dashboard_override" and qual_body:
        system = (
            system
            + "\n\n=== Kwaliteitsstandaard (dashboard override) ===\n"
            + qual_body[:8000]
        )
    versions = [PROMPT_VERSION]
    if role_src == "dashboard_override":
        versions.append(role_ver)
    if qual_src == "dashboard_override":
        versions.append(qual_ver)
    source = (
        "dashboard_override"
        if role_src == "dashboard_override" or qual_src == "dashboard_override"
        else "files_composed"
    )
    return {
        "system_text": system,
        "prompt_version": "+".join(v for v in versions if v)[:180],
        "source": source,
        "composition": [key, "general_instructions", "quality_standard"],
        "bundle": bundle,
    }


def dump_for_debug(conn) -> str:
    return json.dumps(list_prompt_settings(conn), ensure_ascii=False, indent=2)
