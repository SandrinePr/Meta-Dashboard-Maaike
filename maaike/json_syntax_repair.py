"""Mechanical JSON syntax repair only — no content rewriting.

Stops on ambiguity. LOCAL_TEST / recovery path; never calls paid AI.
"""

from __future__ import annotations

import json
import re
from typing import Any


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
# Missing opening quote on a property name:  unassessable":  →  "unassessable":
# Only when the name sits after object start, comma, or newline+indent (not inside a string context we invent).
_MISSING_OPEN_QUOTE_RE = re.compile(
    r'(?P<prefix>[{,]\s*|(?<=\n)[ \t]*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<colon>"\s*:)'
)


def strip_markdown_fences(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = _FENCE_RE.sub("", raw).strip()
    return raw


def find_missing_open_quote_keys(blob: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for match in _MISSING_OPEN_QUOTE_RE.finditer(blob):
        key = match.group("key")
        start = match.start("key")
        # Skip if already quoted: character immediately before key is "
        if start > 0 and blob[start - 1] == '"':
            continue
        hits.append(
            {
                "key": key,
                "start": start,
                "end": match.end("key"),
                "snippet": blob[max(0, start - 20) : match.end("colon") + 5],
            }
        )
    return hits


def repair_unambiguous_json_syntax(text: str) -> dict[str, Any]:
    """Repair only clear missing-opening-quote property names.

    Returns dict with keys: ok, parsed, repaired_text, original_text, edits, error.
    """
    original = text or ""
    stripped = strip_markdown_fences(original)
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return {
                "ok": True,
                "parsed": data,
                "repaired_text": stripped,
                "original_text": original,
                "edits": [],
                "error": None,
                "already_valid": True,
            }
        return {
            "ok": False,
            "parsed": None,
            "repaired_text": stripped,
            "original_text": original,
            "edits": [],
            "error": "JSON is geen object.",
            "already_valid": False,
        }
    except json.JSONDecodeError:
        pass

    # Prefer outermost object span when fences/prose exist
    match_obj = re.search(r"\{[\s\S]*\}", stripped)
    blob = match_obj.group(0) if match_obj else stripped
    hits = find_missing_open_quote_keys(blob)
    if not hits:
        return {
            "ok": False,
            "parsed": None,
            "repaired_text": None,
            "original_text": original,
            "edits": [],
            "error": "Geen eenduidige ontbrekende openingsaanhalingstekens gevonden; stop.",
            "already_valid": False,
        }

    # Apply from right to left so offsets stay valid
    repaired = blob
    edits: list[dict[str, Any]] = []
    for hit in sorted(hits, key=lambda h: h["start"], reverse=True):
        start = hit["start"]
        repaired = repaired[:start] + '"' + repaired[start:]
        edits.append(
            {
                "type": "insert_opening_quote_before_property_name",
                "key": hit["key"],
                "offset_in_object": start,
                "before": hit["snippet"],
                "after": '"' + hit["key"] + '":',
                "description": (
                    f'Property name `{hit["key"]}` mistte het openingsaanhalingsteken '
                    f'vóór de naam (… {hit["key"]}": … → … "{hit["key"]}": …).'
                ),
            }
        )
    edits.reverse()

    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "parsed": None,
            "repaired_text": repaired,
            "original_text": original,
            "edits": edits,
            "error": (
                f"Na mechanische quote-insert nog ongeldige JSON ({exc}); "
                "ambiguïteit of andere fouten — stop zonder verdere edits."
            ),
            "already_valid": False,
        }
    if not isinstance(data, dict):
        return {
            "ok": False,
            "parsed": None,
            "repaired_text": repaired,
            "original_text": original,
            "edits": edits,
            "error": "Herstelde JSON is geen object; stop.",
            "already_valid": False,
        }
    return {
        "ok": True,
        "parsed": data,
        "repaired_text": repaired,
        "original_text": original,
        "edits": edits,
        "error": None,
        "already_valid": False,
    }
