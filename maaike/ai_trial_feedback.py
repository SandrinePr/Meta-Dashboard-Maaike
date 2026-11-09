"""Human feedback, final verdict and Logs adoption for AI trial results."""

from __future__ import annotations

import json
from typing import Any

from maaike.ai_trial import TRIAL_KEY, _now, ensure_ai_tables, get_trial
from maaike.repository import LegendInputError, save_editorial

USABILITY_VALUES = frozenset({"", "usable", "partial", "not_usable"})
USABILITY_LABELS = {
    "usable": "Usable",
    "partial": "Partly usable",
    "not_usable": "Not usable",
    "": "(not chosen)",
}
ITEM_DECISIONS = frozenset({"accept", "correct", "reject", "add", ""})
REVIEW_STATUS_LABELS = {
    "": "No review",
    "awaiting_review": "Awaiting review",
    "in_review": "In review",
    "final_draft": "Final draft",
    "approved": "Approved",
}


def _ensure_feedback_columns(conn) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(ai_analysis_feedback)").fetchall()}
    for name, declaration in (
        ("reviewer_name", "TEXT NOT NULL DEFAULT ''"),
        ("item_decisions_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("final_version_text", "TEXT NOT NULL DEFAULT ''"),
        ("review_status", "TEXT NOT NULL DEFAULT ''"),
        ("ai_original_json", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        if name not in existing:
            conn.execute(f"ALTER TABLE ai_analysis_feedback ADD COLUMN {name} {declaration}")


def ensure_feedback_tables(conn) -> None:
    ensure_ai_tables(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ai_analysis_feedback (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            trial_run_id INTEGER,
            execution_key TEXT NOT NULL,
            usability TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            corrected_format TEXT NOT NULL DEFAULT '',
            corrected_pillar TEXT NOT NULL DEFAULT '',
            corrected_hook TEXT NOT NULL DEFAULT '',
            final_verdict TEXT NOT NULL DEFAULT '',
            final_verdict_confirmed INTEGER NOT NULL DEFAULT 0,
            final_verdict_confirmed_at TEXT,
            reviewer_name TEXT NOT NULL DEFAULT '',
            item_decisions_json TEXT NOT NULL DEFAULT '[]',
            final_version_text TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT '',
            ai_original_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(client_id, post_id, execution_key),
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        );

        CREATE TABLE IF NOT EXISTS post_editorial_revisions (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT NOT NULL DEFAULT '',
            new_value TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            source_detail TEXT NOT NULL DEFAULT '',
            trial_run_id INTEGER,
            feedback_id INTEGER,
            adopted_at TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ai_feedback_exec
            ON ai_analysis_feedback(client_id, post_id, execution_key);
        CREATE INDEX IF NOT EXISTS idx_editorial_revisions_post
            ON post_editorial_revisions(post_id, adopted_at DESC);
        """
    )
    _ensure_feedback_columns(conn)


def execution_key_for_post(row: dict[str, Any] | Any) -> str:
    """Stable key for one AI execution of one post."""
    payload = {}
    raw = row["request_payload_json"] if not isinstance(row, dict) else row.get("request_payload_json")
    if isinstance(raw, str):
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {}
    elif isinstance(raw, dict):
        payload = raw
    live = payload.get("_live_ai_result") or {}
    executed = str(live.get("executed_at") or "").strip()
    model = str(live.get("model") or "").strip()
    prompt = str(live.get("prompt_version") or "").strip()
    post_id = int(row["post_id"] if not isinstance(row, dict) else row["post_id"])
    if executed:
        return f"{post_id}|{executed}|{model}|{prompt}"
    status = str(row["status"] if not isinstance(row, dict) else row.get("status") or "")
    if status in {"mock_completed", "completed", "failed"}:
        # Fallback for mock without live blob timestamps.
        return f"{post_id}|{status}|{prompt or 'unknown'}|{model or 'mock'}"
    return f"{post_id}|pending"


def _require_owned_post(conn, client_id: int, post_id: int) -> None:
    owned = conn.execute(
        "SELECT id FROM posts WHERE id = ? AND client_id = ?",
        (post_id, client_id),
    ).fetchone()
    if owned is None:
        raise ValueError("Post hoort niet bij deze klant.")


def get_feedback(conn, client_id: int, post_id: int, execution_key: str) -> dict[str, Any] | None:
    ensure_feedback_tables(conn)
    row = conn.execute(
        """
        SELECT * FROM ai_analysis_feedback
        WHERE client_id = ? AND post_id = ? AND execution_key = ?
        """,
        (client_id, post_id, execution_key),
    ).fetchone()
    if row is None:
        return None
    return _feedback_out(row)


def _row_get(row, key: str, default: Any = None) -> Any:
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _parse_json_field(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def seed_post_review_items(post: dict[str, Any] | None = None, ai: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Per-conclusie items for post AI trial (format/pillar/hook/insight/action)."""
    src = ai or {}
    post = post or {}
    pairs = (
        ("format", "Format", src.get("proposed_format_code") or post.get("ai_format_code") or ""),
        ("pillar", "Contentpijler", src.get("proposed_pillar") or post.get("ai_pillar") or ""),
        ("hook", "Hook", src.get("proposed_hook") or post.get("ai_hook") or ""),
        ("insight", "Insight", src.get("ai_insight") or post.get("ai_insight") or ""),
        ("action", "Actie", src.get("ai_action") or post.get("ai_action") or ""),
        ("addition", "Eigen aanvulling", ""),
    )
    items = []
    for key, label, text in pairs:
        items.append(
            {
                "key": key,
                "label": label,
                "ai_text": str(text or "").strip(),
                "decision": "add" if key == "addition" else "",
                "human_text": "",
            }
        )
    return items


def _merge_post_items(seeded: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {str(i.get("key")): i for i in existing if isinstance(i, dict)}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for seed in seeded:
        key = str(seed["key"])
        seen.add(key)
        prev = by_key.get(key) or {}
        decision = str(prev.get("decision") or seed.get("decision") or "")
        if decision not in ITEM_DECISIONS:
            decision = ""
        out.append(
            {
                "key": key,
                "label": seed["label"],
                "ai_text": seed.get("ai_text") or "",
                "decision": decision,
                "human_text": str(prev.get("human_text") or ""),
            }
        )
    for key, prev in by_key.items():
        if key in seen:
            continue
        decision = str(prev.get("decision") or "")
        if decision not in ITEM_DECISIONS:
            decision = ""
        out.append(
            {
                "key": key,
                "label": str(prev.get("label") or key),
                "ai_text": str(prev.get("ai_text") or ""),
                "decision": decision,
                "human_text": str(prev.get("human_text") or ""),
            }
        )
    return out


def _compose_post_final(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        decision = str(item.get("decision") or "")
        label = str(item.get("label") or item.get("key") or "")
        if decision == "reject":
            continue
        if decision in {"correct", "add"}:
            text = str(item.get("human_text") or "").strip()
        elif decision == "accept":
            text = str(item.get("ai_text") or "").strip()
        else:
            continue
        if text:
            lines.append(f"{label}: {text}")
    return "\n\n".join(lines)


def _feedback_out(row) -> dict[str, Any]:
    usability = str(row["usability"] or "")
    confirmed = bool(row["final_verdict_confirmed"])
    item_decisions = _parse_json_field(_row_get(row, "item_decisions_json", "[]"), [])
    review_status = str(_row_get(row, "review_status", "") or "")
    if confirmed:
        review_status = "approved"
    has_human = bool(
        usability
        or str(row["notes"] or "").strip()
        or str(row["corrected_format"] or "").strip()
        or str(row["corrected_pillar"] or "").strip()
        or str(row["corrected_hook"] or "").strip()
        or any(str(i.get("decision") or "") for i in item_decisions if isinstance(i, dict))
        or str(_row_get(row, "final_version_text", "") or "").strip()
        or str(_row_get(row, "reviewer_name", "") or "").strip()
    )
    if confirmed and str(row["final_verdict"] or "").strip():
        verdict_display = str(row["final_verdict"])
    elif confirmed:
        verdict_display = "Approved"
    elif has_human:
        verdict_display = (
            str(row["final_verdict"]).strip()
            or REVIEW_STATUS_LABELS.get(review_status)
            or "Concept-eindoordeel aanwezig — nog niet bevestigd."
        )
    else:
        verdict_display = "Alleen AI-analyse; niet menselijk beoordeeld"
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "post_id": row["post_id"],
        "trial_run_id": row["trial_run_id"],
        "execution_key": row["execution_key"],
        "usability": usability,
        "usability_label": USABILITY_LABELS.get(usability, usability),
        "notes": row["notes"] or "",
        "corrected_format": row["corrected_format"] or "",
        "corrected_pillar": row["corrected_pillar"] or "",
        "corrected_hook": row["corrected_hook"] or "",
        "final_verdict": row["final_verdict"] or "",
        "final_verdict_confirmed": confirmed,
        "final_verdict_confirmed_at": row["final_verdict_confirmed_at"],
        "reviewer_name": str(_row_get(row, "reviewer_name", "") or ""),
        "item_decisions": item_decisions,
        "final_version_text": str(_row_get(row, "final_version_text", "") or ""),
        "review_status": review_status,
        "review_status_label": REVIEW_STATUS_LABELS.get(review_status, review_status or "No review"),
        "ai_original": _parse_json_field(_row_get(row, "ai_original_json", "{}"), {}),
        "is_approved": confirmed or review_status == "approved",
        "has_human_feedback": has_human,
        "verdict_display": verdict_display,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def save_feedback(conn, client_id: int, post_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Save optional human feedback for the current AI execution of a post."""
    ensure_feedback_tables(conn)
    _require_owned_post(conn, client_id, post_id)
    run = conn.execute(
        "SELECT id FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    if run is None:
        raise ValueError("Geen AI-proef voor deze klant.")
    row = conn.execute(
        "SELECT * FROM ai_trial_posts WHERE trial_run_id = ? AND post_id = ?",
        (run["id"], post_id),
    ).fetchone()
    if row is None:
        raise ValueError("Proefpost niet gevonden.")

    usability = str((body or {}).get("usability") or "").strip()
    if usability not in USABILITY_VALUES:
        raise ValueError("Ongeldige bruikbaarheidswaarde.")
    notes = str((body or {}).get("notes") or "").strip()
    corrected_format = str((body or {}).get("corrected_format") or "").strip()
    corrected_pillar = str((body or {}).get("corrected_pillar") or "").strip()
    corrected_hook = str((body or {}).get("corrected_hook") or "").strip()
    # Optional draft verdict text — confirmation is a separate action.
    final_verdict = str((body or {}).get("final_verdict") or "").strip()
    confirm = bool((body or {}).get("confirm_final_verdict"))
    reviewer_name = str((body or {}).get("reviewer_name") or "").strip()
    final_version_text = str((body or {}).get("final_version_text") or "").strip()
    compose_final = bool((body or {}).get("compose_final_from_items"))

    live = {}
    live_result: dict[str, Any] = {}
    try:
        payload_raw = row["request_payload_json"] or "{}"
        live = (json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw or {}).get(
            "_live_ai_result"
        ) or {}
        if isinstance(live.get("result"), dict):
            live_result = live["result"]
    except (TypeError, json.JSONDecodeError):
        live = {}
        live_result = {}
    if live.get("analysis_usable") is False or str(_row_get(row, "status") or "") == "failed":
        raise ValueError(
            "Deze uitvoering heeft geen bruikbare AI-analyse. "
            "Feedback/goedkeuring is niet mogelijk; bekijk raw_response en de foutmelding. "
            "Een nieuwe analyse krijgt een nieuwe execution_key en overschrijft bestaande feedback niet."
        )
    ai_snapshot = {
        "proposed_format_code": live_result.get("proposed_format_code")
        or live.get("proposed_format_code")
        or _row_get(row, "ai_format_code")
        or "",
        "proposed_pillar": live_result.get("proposed_pillar")
        or live.get("proposed_pillar")
        or _row_get(row, "ai_pillar")
        or "",
        "proposed_hook": live_result.get("proposed_hook")
        or live.get("proposed_hook")
        or _row_get(row, "ai_hook")
        or "",
        "ai_insight": live_result.get("ai_insight")
        or live.get("ai_insight")
        or _row_get(row, "ai_insight")
        or "",
        "ai_action": live_result.get("ai_action")
        or live.get("ai_action")
        or _row_get(row, "ai_action")
        or "",
    }

    seeded = seed_post_review_items(ai=ai_snapshot)
    raw_items = (body or {}).get("item_decisions")
    key = execution_key_for_post(row)
    now = _now()
    existing = conn.execute(
        """
        SELECT *
        FROM ai_analysis_feedback
        WHERE client_id = ? AND post_id = ? AND execution_key = ?
        """,
        (client_id, post_id, key),
    ).fetchone()
    if raw_items is None:
        raw_items = _parse_json_field(_row_get(existing, "item_decisions_json", "[]") if existing else "[]", [])
    if not isinstance(raw_items, list):
        raise ValueError("item_decisions moet een lijst zijn.")
    items = _merge_post_items(seeded, raw_items)
    for item in items:
        if item["decision"] not in ITEM_DECISIONS:
            raise ValueError(f"Ongeldige beslissing voor {item['key']}.")

    # Mirror legacy corrected_* into item decisions when provided without items.
    for field_key, value in (
        ("format", corrected_format),
        ("pillar", corrected_pillar),
        ("hook", corrected_hook),
    ):
        if value:
            for item in items:
                if item["key"] == field_key and not item["human_text"]:
                    item["decision"] = item["decision"] or "correct"
                    item["human_text"] = value

    if compose_final and not final_version_text:
        final_version_text = _compose_post_final(items)
    if not final_verdict and final_version_text:
        final_verdict = final_version_text

    has_item_human = any(
        str(i.get("decision") or "") in {"accept", "correct", "reject", "add"}
        or str(i.get("human_text") or "").strip()
        for i in items
        if i.get("key") != "addition" or str(i.get("human_text") or "").strip()
    )
    has_human = bool(
        usability or notes or corrected_format or corrected_pillar or corrected_hook or has_item_human
    )
    if confirm:
        if not has_human:
            raise ValueError(
                "Zonder menselijke feedback kan geen gezamenlijk eindoordeel worden bevestigd. "
                "Status blijft: Alleen AI-analyse; niet menselijk beoordeeld."
            )
        if not final_verdict:
            raise ValueError("Vul zelf een eindconclusie in vóór bevestiging (geen AI-samenvatting).")
        if not reviewer_name:
            raise ValueError("Vul de naam van de beoordelaar in vóór goedkeuring.")
        confirmed = 1
        confirmed_at = now
        review_status = "approved"
    else:
        confirmed = int(existing["final_verdict_confirmed"]) if existing else 0
        confirmed_at = existing["final_verdict_confirmed_at"] if existing else None
        if confirmed:
            # Edits after approval reopen review for this execution.
            confirmed = 0
            confirmed_at = None
        if not final_verdict and existing:
            final_verdict = str(existing["final_verdict"] or "")
        if not final_version_text and existing and not compose_final:
            final_version_text = str(_row_get(existing, "final_version_text", "") or "")
        if not reviewer_name and existing:
            reviewer_name = str(_row_get(existing, "reviewer_name", "") or "")
        if final_version_text or final_verdict:
            review_status = "final_draft"
        elif has_human:
            review_status = "in_review"
        else:
            review_status = "awaiting_review"

    ai_original_json = json.dumps(ai_snapshot, ensure_ascii=False)
    items_json = json.dumps(items, ensure_ascii=False)

    if existing:
        conn.execute(
            """
            UPDATE ai_analysis_feedback SET
                usability = ?, notes = ?, corrected_format = ?, corrected_pillar = ?,
                corrected_hook = ?, final_verdict = ?, final_verdict_confirmed = ?,
                final_verdict_confirmed_at = ?, updated_at = ?, trial_run_id = ?,
                reviewer_name = ?, item_decisions_json = ?, final_version_text = ?,
                review_status = ?, ai_original_json = ?
            WHERE id = ?
            """,
            (
                usability,
                notes,
                corrected_format,
                corrected_pillar,
                corrected_hook,
                final_verdict,
                confirmed,
                confirmed_at,
                now,
                run["id"],
                reviewer_name,
                items_json,
                final_version_text,
                review_status,
                ai_original_json,
                existing["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO ai_analysis_feedback (
                client_id, post_id, trial_run_id, execution_key,
                usability, notes, corrected_format, corrected_pillar, corrected_hook,
                final_verdict, final_verdict_confirmed, final_verdict_confirmed_at,
                reviewer_name, item_decisions_json, final_version_text, review_status,
                ai_original_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                post_id,
                run["id"],
                key,
                usability,
                notes,
                corrected_format,
                corrected_pillar,
                corrected_hook,
                final_verdict,
                confirmed,
                confirmed_at,
                reviewer_name,
                items_json,
                final_version_text,
                review_status,
                ai_original_json,
                now,
                now,
            ),
        )

    # Keep lightweight joint_verdict on trial post in sync for list views.
    fb = get_feedback(conn, client_id, post_id, key)
    conn.execute(
        """
        UPDATE ai_trial_posts
        SET human_feedback = ?, joint_verdict = ?
        WHERE trial_run_id = ? AND post_id = ?
        """,
        (
            notes or (USABILITY_LABELS.get(usability, "") if usability else ""),
            fb["verdict_display"] if fb else "Alleen AI-analyse; niet menselijk beoordeeld",
            run["id"],
            post_id,
        ),
    )
    return get_trial(conn, client_id)


def logs_adopt_preview(conn, client_id: int, post_id: int) -> dict[str, Any]:
    """Show current Logs values vs proposed values from AI/human feedback."""
    ensure_feedback_tables(conn)
    _require_owned_post(conn, client_id, post_id)
    run = conn.execute(
        "SELECT id FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    if run is None:
        raise ValueError("Geen AI-proef voor deze klant.")
    row = conn.execute(
        "SELECT * FROM ai_trial_posts WHERE trial_run_id = ? AND post_id = ?",
        (run["id"], post_id),
    ).fetchone()
    if row is None:
        raise ValueError("Proefpost niet gevonden.")
    key = execution_key_for_post(row)
    feedback = get_feedback(conn, client_id, post_id, key) or {}

    editorial = conn.execute(
        """
        SELECT e.format_id, e.pillar_id, e.hook, f.name AS format_name, p.name AS pillar_name
        FROM post_editorial e
        LEFT JOIN content_formats f ON f.id = e.format_id
        LEFT JOIN content_pillars p ON p.id = e.pillar_id
        WHERE e.post_id = ?
        """,
        (post_id,),
    ).fetchone()
    excel = conn.execute(
        """
        SELECT rating_text, insight_text, action_text, source_label
        FROM post_assessments WHERE post_id = ? ORDER BY id DESC LIMIT 1
        """,
        (post_id,),
    ).fetchone()

    proposed_format = (feedback.get("corrected_format") or row["ai_format_code"] or "").strip()
    proposed_pillar = (feedback.get("corrected_pillar") or row["ai_pillar"] or "").strip()
    proposed_hook = (feedback.get("corrected_hook") or row["ai_hook"] or "").strip()

    formats = {
        r["name"]: r["id"]
        for r in conn.execute(
            "SELECT id, name FROM content_formats WHERE client_id = ?",
            (client_id,),
        ).fetchall()
    }
    pillars = {
        r["name"]: r["id"]
        for r in conn.execute(
            "SELECT id, name FROM content_pillars WHERE client_id = ?",
            (client_id,),
        ).fetchall()
    }

    def field(name: str, current: str, proposed: str, resolvable: bool) -> dict[str, Any]:
        return {
            "field": name,
            "current": current or "",
            "proposed": proposed or "",
            "changed": (current or "") != (proposed or "") and bool(proposed),
            "resolvable": resolvable,
            "note": (
                None
                if resolvable or not proposed
                else "Waarde niet gevonden in legenda — kies handmatig in Logs of corrigeer eerst."
            ),
        }

    current_format = (editorial["format_name"] if editorial else "") or ""
    current_pillar = (editorial["pillar_name"] if editorial else "") or ""
    current_hook = (editorial["hook"] if editorial else "") or ""

    return {
        "post_id": post_id,
        "execution_key": key,
        "feedback_id": feedback.get("id"),
        "excel_unchanged": {
            "source_label": excel["source_label"] if excel else None,
            "rating_text": excel["rating_text"] if excel else None,
            "insight_text": excel["insight_text"] if excel else None,
            "action_text": excel["action_text"] if excel else None,
            "note": "Historische Excel-bron wordt nooit overschreven door overnemen naar Logs.",
        },
        "fields": [
            field(
                "contentformat",
                current_format,
                proposed_format,
                (not proposed_format)
                or proposed_format in formats
                or proposed_format.lower() in {"niet vast te stellen", "geen passend bestaand format"},
            ),
            field(
                "contentpijler",
                current_pillar,
                proposed_pillar,
                (not proposed_pillar)
                or proposed_pillar in pillars
                or proposed_pillar.lower() == "niet vast te stellen",
            ),
            field("hook", current_hook, proposed_hook, True),
        ],
        "legend_lookup": {
            "format_ids": formats,
            "pillar_ids": pillars,
        },
    }


def adopt_to_logs(conn, client_id: int, post_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Apply selected fields to Logs editorial, with revision history. Never touches Excel assessments."""
    ensure_feedback_tables(conn)
    preview = logs_adopt_preview(conn, client_id, post_id)
    selected = set(body.get("fields") or [])
    allowed = {"contentformat", "contentpijler", "hook"}
    if not selected:
        raise ValueError("Kies minstens één veld om over te nemen.")
    if not selected.issubset(allowed):
        raise ValueError("Ongeldige veldkeuze.")

    editorial = conn.execute(
        "SELECT format_id, pillar_id, hook FROM post_editorial WHERE post_id = ?",
        (post_id,),
    ).fetchone()
    format_id = editorial["format_id"] if editorial else None
    pillar_id = editorial["pillar_id"] if editorial else None
    hook = (editorial["hook"] if editorial else "") or ""

    formats = preview["legend_lookup"]["format_ids"]
    pillars = preview["legend_lookup"]["pillar_ids"]
    field_map = {f["field"]: f for f in preview["fields"]}
    now = _now()
    applied: list[dict[str, Any]] = []
    run = conn.execute(
        "SELECT id FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    feedback_id = preview.get("feedback_id")

    for name in selected:
        item = field_map[name]
        proposed = item["proposed"]
        if not proposed:
            continue
        if name == "contentformat":
            if proposed.lower() in {"niet vast te stellen", "geen passend bestaand format"}:
                raise ValueError(
                    "‘Niet vast te stellen’ / ‘Geen passend bestaand format’ kan niet als Logs-format worden overgenomen."
                )
            if proposed not in formats:
                raise ValueError(f"Format ‘{proposed}’ staat niet in de legenda.")
            old = item["current"]
            format_id = formats[proposed]
            applied.append({"field": name, "old": old, "new": proposed})
        elif name == "contentpijler":
            if proposed.lower() == "niet vast te stellen":
                raise ValueError("‘Niet vast te stellen’ kan niet als Logs-pijler worden overgenomen.")
            if proposed not in pillars:
                raise ValueError(f"Pijler ‘{proposed}’ staat niet in de legenda.")
            old = item["current"]
            pillar_id = pillars[proposed]
            applied.append({"field": name, "old": old, "new": proposed})
        elif name == "hook":
            old = item["current"]
            hook = proposed
            applied.append({"field": name, "old": old, "new": proposed})

    if not applied:
        raise ValueError("Geen toepasbare wijzigingen geselecteerd.")

    try:
        save_editorial(
            conn,
            client_id,
            post_id=post_id,
            format_id=format_id,
            pillar_id=pillar_id,
            hook=hook,
        )
    except LegendInputError as exc:
        raise ValueError(str(exc)) from exc

    for change in applied:
        conn.execute(
            """
            INSERT INTO post_editorial_revisions (
                client_id, post_id, field_name, old_value, new_value,
                source, source_detail, trial_run_id, feedback_id, adopted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                post_id,
                change["field"],
                change["old"],
                change["new"],
                "ai_trial_adopt",
                f"execution_key={preview['execution_key']}",
                run["id"] if run else None,
                feedback_id,
                now,
            ),
        )

    return {
        "ok": True,
        "applied": applied,
        "excel_untouched": True,
        "preview_after": logs_adopt_preview(conn, client_id, post_id),
        "trial": get_trial(conn, client_id)["trial"],
    }


def attach_feedback_to_trial_posts(conn, client_id: int, posts: list[dict[str, Any]]) -> None:
    """Mutate trial post dicts in place with feedback for their execution key."""
    ensure_feedback_tables(conn)
    for post in posts:
        # Reconstruct a minimal row for key generation from live result.
        live = post.get("live_ai_result") or {}
        fake = {
            "post_id": post["post_id"],
            "status": post.get("status"),
            "request_payload_json": json.dumps(
                {
                    "_live_ai_result": live,
                },
                ensure_ascii=False,
            ),
        }
        # Prefer live from payload already on post.
        if post.get("request_payload"):
            fake["request_payload_json"] = json.dumps(post["request_payload"], ensure_ascii=False)
        key = execution_key_for_post(fake)
        post["execution_key"] = key
        post["human_feedback_record"] = get_feedback(conn, client_id, post["post_id"], key)
        seeded = seed_post_review_items(post=post)
        if post["human_feedback_record"]:
            post["joint_verdict"] = post["human_feedback_record"]["verdict_display"]
            existing_items = post["human_feedback_record"].get("item_decisions") or []
            post["human_feedback_record"]["item_decisions"] = _merge_post_items(seeded, existing_items)
            if not post["human_feedback_record"].get("ai_original"):
                post["human_feedback_record"]["ai_original"] = {
                    "proposed_format_code": post.get("ai_format_code") or "",
                    "proposed_pillar": post.get("ai_pillar") or "",
                    "proposed_hook": post.get("ai_hook") or "",
                    "ai_insight": post.get("ai_insight") or "",
                    "ai_action": post.get("ai_action") or "",
                }
        elif post.get("ai_insight") or post.get("ai_format_code"):
            post["joint_verdict"] = "Alleen AI-analyse; niet menselijk beoordeeld"
            post["review_items_seed"] = seeded
        else:
            post["review_items_seed"] = seeded
