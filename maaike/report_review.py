"""Human review for client/trend reports: AI original → feedback → final → Approved."""

from __future__ import annotations

import json
from typing import Any

from maaike.ai_trial import _now

ITEM_DECISIONS = frozenset({"accept", "correct", "reject", "add", ""})
REVIEW_STATUSES = frozenset(
    {"", "awaiting_review", "in_review", "final_draft", "approved"}
)
REVIEW_STATUS_LABELS = {
    "": "No review",
    "awaiting_review": "Awaiting review",
    "in_review": "In review",
    "final_draft": "Final draft",
    "approved": "Approved",
}

CLIENT_ANSWER_LABELS = {
    "beter": "What went better?",
    "slechter": "What went worse?",
    "verklaring": "Explanation",
    "herhalen": "What to repeat?",
    "stoppen": "What to stop?",
    "testen": "What to test?",
}

CLIENT_CHAPTER_LABELS = {
    "input_brainstorm": "Input brainstorm / planning",
    "per_kanaal": "Per channel",
    "seo_serp": "SEO and SERP",
    "concurrenten": "Competitors and best practices",
    "hooks_formats_testen": "Hooks and formats to test",
    "laten_liggen_aanscherpen": "Leave or refine",
}

CLIENT_ACTION_PLAN_LABELS = {
    "planning_note": "Action plan: planning note",
    "hoofdfocus": "Action plan: main focus",
    "waarom_nu": "Action plan: why now",
    "actions": "Action plan: concrete actions",
    "stop_or_test_decisions": "Action plan: stop or test",
    "watch_outs": "Action plan: watch-outs",
}

TREND_CHAPTER_LABELS = {
    "positionering": "Positioning",
    "managementsamenvatting": "Management summary",
    "belangrijkste_trends": "Key trends",
    "platform_verschuivingen": "Platform shifts",
    "contentkansen": "Content opportunities",
    "zoekclusters": "Search clusters",
    "conclusie": "Conclusion",
}


def ensure_report_review_tables(conn) -> None:
    from maaike.reports import ensure_report_tables

    ensure_report_tables(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS client_report_reviews (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            report_id INTEGER NOT NULL,
            execution_key TEXT NOT NULL,
            ai_original_json TEXT NOT NULL DEFAULT '{}',
            item_feedback_json TEXT NOT NULL DEFAULT '[]',
            final_version_text TEXT NOT NULL DEFAULT '',
            reviewer_name TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT,
            approved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(client_id, report_id, execution_key),
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(report_id) REFERENCES client_reports(id)
        );

        CREATE INDEX IF NOT EXISTS idx_report_reviews_report
            ON client_report_reviews(client_id, report_id, execution_key);
        """
    )
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(client_report_reviews)").fetchall()}
    if "previous_approved_json" not in cols:
        conn.execute(
            "ALTER TABLE client_report_reviews ADD COLUMN previous_approved_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "warning_acks_json" not in cols:
        conn.execute(
            "ALTER TABLE client_report_reviews ADD COLUMN warning_acks_json TEXT NOT NULL DEFAULT '[]'"
        )


def execution_key_for_report(row: dict[str, Any] | Any) -> str:
    """Stable key for one AI/mock execution of one report version."""
    rid = int(row["id"] if not isinstance(row, dict) else row["id"])
    version = int(row["version"] if not isinstance(row, dict) else row.get("version") or 1)
    executed = str(
        (row["executed_at"] if not isinstance(row, dict) else row.get("executed_at")) or ""
    ).strip()
    status = str(
        (row["status"] if not isinstance(row, dict) else row.get("status")) or ""
    ).strip()
    is_mock = int(
        row["is_mock"] if not isinstance(row, dict) else (1 if row.get("is_mock") else 0)
    )
    if not executed:
        return f"{rid}|v{version}|pending|{status}"
    return f"{rid}|v{version}|{executed}|mock={is_mock}|{status}"


def _parse_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def extract_review_items(report_type: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Build editable conclusion/advice items from an AI (or mock) report body."""
    from maaike.ai_response_validate import normalize_trend_chapters

    items: list[dict[str, Any]] = []
    body = body or {}
    if report_type == "client":
        answers = body.get("six_answers") or {}
        for key, label in CLIENT_ANSWER_LABELS.items():
            text = str(answers.get(key) or "").strip()
            items.append(
                {
                    "key": f"six_answers.{key}",
                    "label": label,
                    "ai_text": text,
                    "decision": "",
                    "human_text": "",
                }
            )
        chapters = body.get("chapters") or {}
        if isinstance(chapters, dict):
            for key, label in CLIENT_CHAPTER_LABELS.items():
                text = str(chapters.get(key) or "").strip()
                items.append(
                    {
                        "key": f"chapters.{key}",
                        "label": label,
                        "ai_text": text,
                        "decision": "",
                        "human_text": "",
                    }
                )
        plan = body.get("action_plan") or {}
        if isinstance(plan, dict):
            for key, label in CLIENT_ACTION_PLAN_LABELS.items():
                val = plan.get(key)
                if isinstance(val, list):
                    text = "\n".join(str(x).strip() for x in val if str(x).strip())
                else:
                    text = str(val or "").strip()
                items.append(
                    {
                        "key": f"action_plan.{key}",
                        "label": label,
                        "ai_text": text,
                        "decision": "",
                        "human_text": "",
                    }
                )
        # Explicit human-approval reminder item (never auto-approved).
        items.append(
            {
                "key": "action_plan.human_approval",
                "label": "Action plan: human approval before planning",
                "ai_text": (
                    "Actieplan vereist menselijke controle/goedkeuring vóór gebruik in planning. "
                    "Review status must reach Approved before treating actions as final."
                ),
                "decision": "",
                "human_text": "",
            }
        )
    else:
        chapters = normalize_trend_chapters(body.get("chapters") or {})
        for key, label in TREND_CHAPTER_LABELS.items():
            val = chapters.get(key)
            if isinstance(val, list):
                text = json.dumps(val, ensure_ascii=False)
            else:
                text = str(val or "").strip()
            items.append(
                {
                    "key": f"chapters.{key}",
                    "label": label,
                    "ai_text": text,
                    "decision": "",
                    "human_text": "",
                }
            )
        distinctions = body.get("distinctions") or {}
        for key in ("facts", "trends", "suggestions"):
            val = distinctions.get(key) or []
            items.append(
                {
                    "key": f"distinctions.{key}",
                    "label": f"Onderscheid: {key}",
                    "ai_text": json.dumps(val, ensure_ascii=False) if val else "",
                    "decision": "",
                    "human_text": "",
                }
            )
    # Free-form addition slot always available.
    items.append(
        {
            "key": "addition.staff",
            "label": "Eigen aanvulling",
            "ai_text": "",
            "decision": "add",
            "human_text": "",
        }
    )
    return items


def _migrate_legacy_item_fields(prev: dict[str, Any], ai_text: str) -> dict[str, Any]:
    """Map old accept/correct/reject/add fields onto feedback + edited_text without data loss."""
    decision = str(prev.get("decision") or "")
    if decision not in ITEM_DECISIONS:
        decision = ""
    human = str(prev.get("human_text") or "").strip()
    feedback = str(prev.get("feedback") or "").strip()
    edited = prev.get("edited_text")
    edited_text = "" if edited is None else str(edited)
    edited_by = str(prev.get("edited_by") or "").strip()
    edited_at = str(prev.get("edited_at") or "").strip()

    # Prefer explicit new fields; otherwise derive from legacy decisions.
    if edited is None:
        if decision == "correct" and human:
            edited_text = human
        elif decision == "add" and human:
            edited_text = human
        else:
            edited_text = ""
    if decision == "reject":
        note = "Previously marked as reject (legacy review choice)."
        if note.lower() not in feedback.lower():
            feedback = f"{feedback}\n{note}".strip() if feedback else note
    elif decision in {"correct", "add"} and human and human not in feedback and edited_text != human:
        # Keep legacy staff wording visible if it wasn't used as edited text.
        feedback = f"{feedback}\n{human}".strip() if feedback else human

    return {
        "decision": decision,
        "human_text": human,
        "feedback": feedback,
        "edited_text": edited_text,
        "edited_by": edited_by,
        "edited_at": edited_at,
        "ai_text": ai_text,
    }


def current_item_text(item: dict[str, Any]) -> str:
    """Readable report text for one section: edited text if set, otherwise AI original."""
    edited = str(item.get("edited_text") or "").strip()
    if edited:
        return edited
    if str(item.get("decision") or "") == "reject" and not edited:
        # Legacy reject without replacement: omit from composed document.
        return ""
    return str(item.get("ai_text") or "").strip()


def item_is_edited(item: dict[str, Any]) -> bool:
    edited = str(item.get("edited_text") or "").strip()
    if not edited:
        return False
    return edited != str(item.get("ai_text") or "").strip()


def _merge_items(
    seeded: list[dict[str, Any]], existing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_key = {str(i.get("key")): i for i in existing if isinstance(i, dict)}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for seed in seeded:
        key = str(seed["key"])
        seen.add(key)
        prev = by_key.get(key) or {}
        ai_text = str(seed.get("ai_text") or "")
        migrated = _migrate_legacy_item_fields(prev, ai_text)
        out.append(
            {
                "key": key,
                "label": seed["label"],
                "ai_text": ai_text,
                "decision": migrated["decision"],
                "human_text": migrated["human_text"],
                "feedback": migrated["feedback"],
                "edited_text": migrated["edited_text"],
                "edited_by": migrated["edited_by"],
                "edited_at": migrated["edited_at"],
                "is_edited": bool(migrated["edited_text"].strip())
                and migrated["edited_text"].strip() != ai_text.strip(),
            }
        )
    for key, prev in by_key.items():
        if key in seen:
            continue
        ai_text = str(prev.get("ai_text") or "")
        migrated = _migrate_legacy_item_fields(prev, ai_text)
        out.append(
            {
                "key": key,
                "label": str(prev.get("label") or key),
                "ai_text": ai_text,
                "decision": migrated["decision"],
                "human_text": migrated["human_text"],
                "feedback": migrated["feedback"],
                "edited_text": migrated["edited_text"],
                "edited_by": migrated["edited_by"],
                "edited_at": migrated["edited_at"],
                "is_edited": bool(migrated["edited_text"].strip())
                and migrated["edited_text"].strip() != ai_text.strip(),
            }
        )
    return out


def build_final_from_items(items: list[dict[str, Any]]) -> str:
    """Compose concept/final document text from saved edits + unchanged AI sections (no AI call)."""
    lines: list[str] = []
    for item in items:
        key = str(item.get("key") or "")
        if key in {"action_plan.human_approval"}:
            continue
        label = str(item.get("label") or key)
        text = current_item_text(item)
        if not text:
            continue
        if key == "addition.staff" and not str(item.get("edited_text") or "").strip():
            continue
        lines.append(f"{label}\n\n{text}")
    return "\n\n".join(lines)


def _row_has_column(row, name: str) -> bool:
    try:
        keys = set(row.keys())
    except Exception:
        return False
    return name in keys


def _review_out(row) -> dict[str, Any]:
    status = str(row["review_status"] or "")
    previous_approved = []
    if _row_has_column(row, "previous_approved_json"):
        previous_approved = _parse_json(row["previous_approved_json"], [])
        if not isinstance(previous_approved, list):
            previous_approved = []
    warning_acks = []
    if _row_has_column(row, "warning_acks_json"):
        warning_acks = _parse_json(row["warning_acks_json"], [])
        if not isinstance(warning_acks, list):
            warning_acks = []
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "report_id": row["report_id"],
        "execution_key": row["execution_key"],
        "ai_original": _parse_json(row["ai_original_json"], {}),
        "item_feedback": _parse_json(row["item_feedback_json"], []),
        "final_version_text": row["final_version_text"] or "",
        "reviewer_name": row["reviewer_name"] or "",
        "review_status": status,
        "review_status_label": REVIEW_STATUS_LABELS.get(status, status or "No review"),
        "reviewed_at": row["reviewed_at"],
        "approved_at": row["approved_at"],
        "is_approved": status == "approved",
        "previous_approved": previous_approved,
        "warning_acknowledgements": warning_acks,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def warning_ack_key(point: dict[str, Any]) -> str:
    kind = str(point.get("kind") or "")
    location = str(point.get("location") or "")
    note = str(point.get("note") or point.get("summary_nl") or "")[:120]
    return f"{kind}|{location}|{note}"


def get_review_for_report(conn, client_id: int, report_row) -> dict[str, Any] | None:
    ensure_report_review_tables(conn)
    key = execution_key_for_report(report_row)
    row = conn.execute(
        """
        SELECT * FROM client_report_reviews
        WHERE client_id = ? AND report_id = ? AND execution_key = ?
        """,
        (client_id, int(report_row["id"]), key),
    ).fetchone()
    if row is None:
        return None
    return _review_out(row)


def _body_analysis_usable(report_row) -> bool:
    raw = report_row["body_json"] if not isinstance(report_row, dict) else report_row.get("body_json")
    try:
        body = json.loads(raw or "{}") if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        return False
    if not isinstance(body, dict):
        return False
    if body.get("analysis_usable") is False:
        return False
    grounding = body.get("source_grounding")
    if isinstance(grounding, dict) and (
        grounding.get("ok") is False or grounding.get("unfounded_claims")
    ):
        return False
    status = str(
        (report_row["status"] if not isinstance(report_row, dict) else report_row.get("status")) or ""
    )
    if status not in {"completed", "mock_completed"}:
        return False
    # Usable client/trend content must expose the canonical blocks.
    report_type = str(
        (report_row["report_type"] if not isinstance(report_row, dict) else report_row.get("report_type"))
        or ""
    )
    if report_type == "client":
        answers = body.get("six_answers") or {}
        return isinstance(answers, dict) and any(str(answers.get(k) or "").strip() for k in CLIENT_ANSWER_LABELS)
    if report_type == "trend":
        chapters = body.get("chapters") or {}
        return isinstance(chapters, dict) and any(str(v or "").strip() for v in chapters.values() if not isinstance(v, list) or v)
    return False


def review_summary_for_list(conn, client_id: int, report_row) -> dict[str, Any]:
    """Compact review fields for report lists (never invent Approved)."""
    ensure_report_review_tables(conn)
    executed = bool(report_row["executed_at"])
    status = str(report_row["status"] or "")
    key = execution_key_for_report(report_row)
    review = get_review_for_report(conn, client_id, report_row)
    # List queries may omit body_json; only enforce body usability when present.
    try:
        has_body = True
        if isinstance(report_row, dict):
            has_body = "body_json" in report_row or "body" in report_row
        else:
            keys = set(report_row.keys())  # sqlite3.Row
            has_body = "body_json" in keys
    except Exception:
        has_body = False
    usable = _body_analysis_usable(report_row) if has_body else status in {"completed", "mock_completed"}
    if not executed or status == "prepared":
        return {
            "execution_key": key,
            "review_status": "",
            "review_status_label": "No AI run",
            "is_approved": False,
            "reviewer_name": "",
            "can_review": False,
            "analysis_usable": False,
        }
    if status == "failed" or (has_body and not usable):
        return {
            "execution_key": key,
            "review_status": "",
            "review_status_label": "Analysis unusable",
            "is_approved": False,
            "reviewer_name": "",
            "can_review": False,
            "analysis_usable": False,
        }
    if review is None:
        return {
            "execution_key": key,
            "review_status": "awaiting_review",
            "review_status_label": REVIEW_STATUS_LABELS["awaiting_review"],
            "is_approved": False,
            "reviewer_name": "",
            "can_review": True,
            "analysis_usable": True,
        }
    return {
        "execution_key": key,
        "review_status": review["review_status"] or "awaiting_review",
        "review_status_label": review["review_status_label"],
        "is_approved": review["is_approved"],
        "reviewer_name": review["reviewer_name"],
        "can_review": True,
        "analysis_usable": True,
        "approved_at": review.get("approved_at"),
    }


def attach_review_to_report_payload(conn, client_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Enrich get_report result with review + seeded items (no mutation of AI body)."""
    ensure_report_review_tables(conn)
    report = payload["report"]
    key = execution_key_for_report(report)
    body = report.get("body") or {}
    seeded = extract_review_items(str(report.get("report_type") or ""), body)
    review = get_review_for_report(conn, client_id, report)
    summary = review_summary_for_list(conn, client_id, report)

    if review:
        items = _merge_items(seeded, review.get("item_feedback") or [])
        ai_original = review.get("ai_original") or body
        final_text = review.get("final_version_text") or ""
    else:
        items = seeded
        ai_original = body if summary.get("can_review") else {}
        final_text = ""

    payload["review"] = {
        **summary,
        "execution_key": key,
        "record": review,
        "ai_original": ai_original,
        "item_feedback": items,
        "final_version_text": final_text,
        "reviewer_name": (review or {}).get("reviewer_name") or "",
        "previous_approved": (review or {}).get("previous_approved") or [],
        "warning_acknowledgements": (review or {}).get("warning_acknowledgements") or [],
        "workflow": [
            "AI draft",
            "Edit / feedback",
            "Concept assembled",
            "Approved",
        ],
    }
    return payload


def _items_have_staff_activity(items: list[dict[str, Any]]) -> bool:
    for item in items:
        key = str(item.get("key") or "")
        if key == "addition.staff" and not (
            str(item.get("edited_text") or "").strip()
            or str(item.get("feedback") or "").strip()
            or str(item.get("human_text") or "").strip()
        ):
            continue
        if str(item.get("feedback") or "").strip():
            return True
        if str(item.get("edited_text") or "").strip():
            return True
        if str(item.get("human_text") or "").strip():
            return True
        if str(item.get("decision") or "") in {"accept", "correct", "reject", "add"} and key != "addition.staff":
            return True
    return False


def save_report_review(conn, client_id: int, report_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Save per-section feedback/edits, auto-compose concept text, or explicitly approve."""
    ensure_report_review_tables(conn)
    row = conn.execute(
        "SELECT * FROM client_reports WHERE id = ? AND client_id = ?",
        (report_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Report not found for this client.")

    executed = bool(row["executed_at"])
    status = str(row["status"] or "")
    if not executed or status == "prepared":
        raise ValueError(
            "Without an AI/mock run there is no staff review or approval. "
            "Preparation is not a finished analysis."
        )
    if status not in {"completed", "mock_completed"}:
        raise ValueError(
            f'Report status "{status}" does not allow review. '
            "Unusable or failed AI answers cannot be approved; check the error and raw_response."
        )
    if not _body_analysis_usable(row):
        raise ValueError(
            "This report cannot be approved: the AI answer does not match the fixed format "
            "or is marked unusable. The original answer is kept for review."
        )

    key = execution_key_for_report(row)
    ai_body = _parse_json(row["body_json"], {})
    seeded = extract_review_items(str(row["report_type"] or ""), ai_body)

    payload = body or {}
    reviewer_name = str(payload.get("reviewer_name") or "").strip()
    raw_items = payload.get("item_feedback")
    if raw_items is None:
        existing_items = conn.execute(
            """
            SELECT item_feedback_json FROM client_report_reviews
            WHERE client_id = ? AND report_id = ? AND execution_key = ?
            """,
            (client_id, report_id, key),
        ).fetchone()
        raw_items = _parse_json(existing_items["item_feedback_json"], []) if existing_items else []
    if not isinstance(raw_items, list):
        raise ValueError("item_feedback must be a list.")

    # Stamp editor metadata on items that changed in this request.
    now = _now()
    editor = reviewer_name or str(payload.get("edited_by") or "").strip()
    stamped: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if "edited_text" in item or "feedback" in item:
            if editor and (
                str(item.get("edited_text") or "").strip()
                or str(item.get("feedback") or "").strip()
            ):
                if not str(item.get("edited_by") or "").strip():
                    item["edited_by"] = editor
                if not str(item.get("edited_at") or "").strip():
                    item["edited_at"] = now
        stamped.append(item)

    items = _merge_items(seeded, stamped)
    for item in items:
        if item["decision"] not in ITEM_DECISIONS:
            raise ValueError(f"Invalid decision for {item['key']}.")

    # Concept text is always assembled from saved edits + unchanged AI sections (no AI call).
    # Feedback is stored separately and never becomes report text automatically.
    final_version_text = build_final_from_items(items)
    # Legacy override: only when caller explicitly disables compose and supplies text.
    if payload.get("compose_final_from_items") is False and str(
        payload.get("final_version_text") or ""
    ).strip():
        final_version_text = str(payload.get("final_version_text") or "").strip()

    approve = bool(payload.get("approve"))
    grounding = ai_body.get("source_grounding") if isinstance(ai_body, dict) else None
    if approve and isinstance(grounding, dict) and (
        grounding.get("ok") is False
        or grounding.get("unfounded_claims")
        or grounding.get("status") == "unfounded_claims_require_human_review"
    ):
        raise ValueError(
            "This report cannot be approved: unfounded Ahrefs/SEO/competitor/trend claims "
            "require human correction first. Original AI output is preserved for review."
        )
    existing = conn.execute(
        """
        SELECT * FROM client_report_reviews
        WHERE client_id = ? AND report_id = ? AND execution_key = ?
        """,
        (client_id, report_id, key),
    ).fetchone()

    previous_approved: list[Any] = []
    if existing and _row_has_column(existing, "previous_approved_json"):
        previous_approved = _parse_json(existing["previous_approved_json"], [])
        if not isinstance(previous_approved, list):
            previous_approved = []

    warning_acks: list[Any] = []
    if existing and _row_has_column(existing, "warning_acks_json"):
        warning_acks = _parse_json(existing["warning_acks_json"], [])
        if not isinstance(warning_acks, list):
            warning_acks = []
    if "warning_acknowledgements" in payload:
        incoming = payload.get("warning_acknowledgements")
        if not isinstance(incoming, list):
            raise ValueError("warning_acknowledgements must be a list.")
        warning_acks = incoming

    if approve:
        if not reviewer_name:
            raise ValueError("Enter the reviewer name before approval.")
        if not final_version_text.strip():
            raise ValueError("Nothing to approve: the report has no readable sections.")
        # Content warnings must be consciously handled before approval.
        from maaike.client_report_view import default_review_attention_points

        open_points = default_review_attention_points(ai_body if isinstance(ai_body, dict) else {})
        ack_map = {
            str(a.get("key") or ""): a
            for a in warning_acks
            if isinstance(a, dict) and str(a.get("status") or "") in {"addressed", "accepted"}
        }
        missing_acks = [
            p for p in open_points if warning_ack_key(p) not in ack_map
        ]
        if missing_acks:
            raise ValueError(
                f"Open review points must be addressed or accepted with a note before approval "
                f"({len(missing_acks)} remaining). Open Review notes to handle them."
            )
        review_status = "approved"
        approved_at = now
        reviewed_at = now
    else:
        if _items_have_staff_activity(items) or final_version_text:
            review_status = "final_draft" if final_version_text else "in_review"
        else:
            review_status = "awaiting_review"
        approved_at = None
        if existing and existing["review_status"] == "approved":
            # Editing after approval reopens as concept and archives the prior approval.
            previous_approved.append(
                {
                    "approved_at": existing["approved_at"],
                    "reviewer_name": existing["reviewer_name"],
                    "final_version_text": existing["final_version_text"],
                    "item_feedback": _parse_json(existing["item_feedback_json"], []),
                    "superseded_at": now,
                }
            )
            review_status = "final_draft" if final_version_text else "in_review"
        reviewed_at = now if review_status != "awaiting_review" else (
            existing["reviewed_at"] if existing else None
        )
        if not reviewer_name and existing:
            reviewer_name = str(existing["reviewer_name"] or "")

    ai_original_json = json.dumps(ai_body, ensure_ascii=False)
    items_json = json.dumps(items, ensure_ascii=False)
    previous_json = json.dumps(previous_approved, ensure_ascii=False)
    acks_json = json.dumps(warning_acks, ensure_ascii=False)

    if existing:
        conn.execute(
            """
            UPDATE client_report_reviews SET
                ai_original_json = ?,
                item_feedback_json = ?,
                final_version_text = ?,
                reviewer_name = ?,
                review_status = ?,
                reviewed_at = ?,
                approved_at = ?,
                previous_approved_json = ?,
                warning_acks_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                ai_original_json,
                items_json,
                final_version_text,
                reviewer_name,
                review_status,
                reviewed_at,
                approved_at,
                previous_json,
                acks_json,
                now,
                existing["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO client_report_reviews (
                client_id, report_id, execution_key,
                ai_original_json, item_feedback_json, final_version_text,
                reviewer_name, review_status, reviewed_at, approved_at,
                previous_approved_json, warning_acks_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                report_id,
                key,
                ai_original_json,
                items_json,
                final_version_text,
                reviewer_name,
                review_status,
                reviewed_at,
                approved_at,
                previous_json,
                acks_json,
                now,
                now,
            ),
        )

    from maaike.reports import get_report

    return attach_review_to_report_payload(conn, client_id, get_report(conn, client_id, report_id))
