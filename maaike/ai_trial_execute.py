"""Execute the prepared Red Rock AI trial: at most 3 paid calls, hard budget USD 0.10."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import requests

from ai.config import chat_completions_url, is_configured, load_ai_config
from maaike.ai_trial import (
    OFFICIAL_RATES,
    PROMPT_VERSION,
    TRIAL_KEY,
    _now,
    ensure_ai_tables,
    get_trial,
)
from maaike.ai_trial_request import PROMPT_VERSION as REQUEST_PROMPT_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUDGET_USD = 0.10
MAX_CALLS = 3
REQUEST_TIMEOUT_S = 120
MAX_OUTPUT_TOKENS = 2000

_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "evidence_ref": {"type": "string"},
                    "fact": {"type": "string"},
                },
                "required": ["evidence_ref", "fact"],
            },
        },
        "proposed_format_code": {"type": "string"},
        "format_rationale": {"type": "string"},
        "format_uncertainty": {"type": "string"},
        "proposed_pillar": {"type": "string"},
        "proposed_hook": {"type": "string"},
        "ai_insight": {"type": "string"},
        "ai_action": {"type": "string"},
        "hypotheses": {"type": "array", "items": {"type": "string"}},
        "unassessable": {"type": "array", "items": {"type": "string"}},
        "limitations_acknowledged": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "observations",
        "proposed_format_code",
        "format_rationale",
        "format_uncertainty",
        "proposed_pillar",
        "proposed_hook",
        "ai_insight",
        "ai_action",
        "hypotheses",
        "unassessable",
        "limitations_acknowledged",
    ],
}


def _image_part(path: Path) -> dict[str, Any]:
    encoded = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    if suffix == "jpg":
        suffix = "jpeg"
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/{suffix};base64,{encoded}"},
    }


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks)
    return ""


def _usage_from_body(body: dict[str, Any]) -> dict[str, Any]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return {
            "reported": False,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }

    def _token(name: str) -> int | None:
        value = usage.get(name)
        return value if isinstance(value, int) else None

    return {
        "reported": True,
        "prompt_tokens": _token("prompt_tokens"),
        "completion_tokens": _token("completion_tokens"),
        "total_tokens": _token("total_tokens"),
    }


def _cost_usd(prompt_tokens: int | None, completion_tokens: int | None) -> tuple[float | None, bool]:
    if prompt_tokens is None or completion_tokens is None:
        return None, False
    cost = (prompt_tokens / 1_000_000) * OFFICIAL_RATES["input_per_1m"] + (
        completion_tokens / 1_000_000
    ) * OFFICIAL_RATES["output_per_1m"]
    return round(cost, 6), True


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _normalize_result(raw: dict[str, Any], *, role: str, limitations: list[str]) -> dict[str, Any]:
    observations = []
    for item in raw.get("observations") or []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("evidence_ref") or "").strip()
        fact = str(item.get("fact") or "").strip()
        if ref and fact:
            observations.append({"evidence_ref": ref, "fact": fact})
    format_code = str(raw.get("proposed_format_code") or "").strip() or "Niet vast te stellen"
    if role == "image" and format_code.upper().startswith("C"):
        format_code = "Geen passend bestaand format"
    hypotheses = [str(x).strip() for x in (raw.get("hypotheses") or []) if str(x).strip()]
    unassessable = [str(x).strip() for x in (raw.get("unassessable") or []) if str(x).strip()]
    ack = [str(x).strip() for x in (raw.get("limitations_acknowledged") or []) if str(x).strip()]
    for lim in limitations:
        if lim and lim not in ack:
            ack.append(lim)
    # Do not invent spoken-hook claims for reels without audio.
    if role == "reel":
        spoken_note = "Gesproken tekst/hook niet beoordeeld: geen audio of transcript meegestuurd."
        if spoken_note not in unassessable:
            unassessable.append(spoken_note)
    if role == "carousel":
        video_note = "Eén carrousel-videoslide is niet volledig als bewegend beeld beschikbaar."
        if video_note not in unassessable and any("video" in (lim or "").lower() for lim in limitations):
            unassessable.append(video_note)
    return {
        "observations": observations,
        "proposed_format_code": format_code,
        "format_rationale": str(raw.get("format_rationale") or "").strip(),
        "format_uncertainty": str(raw.get("format_uncertainty") or "").strip() or "onbekend",
        "proposed_pillar": str(raw.get("proposed_pillar") or "").strip() or "Niet vast te stellen",
        "proposed_hook": str(raw.get("proposed_hook") or "").strip() or "Niet vast te stellen",
        "ai_insight": str(raw.get("ai_insight") or "").strip(),
        "ai_action": str(raw.get("ai_action") or "").strip(),
        "hypotheses": hypotheses,
        "unassessable": unassessable,
        "limitations_acknowledged": ack,
    }


def _verify_media(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ready = []
    for item in images:
        rel = str(item.get("path") or "")
        path = PROJECT_ROOT / rel
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        ready.append({**item, "abs_path": str(path), "bytes_on_disk": path.stat().st_size})
    return ready


def _budget_precheck(estimate: dict[str, Any]) -> dict[str, Any]:
    band = estimate.get("trial_estimated_usd") or {}
    high = band.get("high")
    low = band.get("low")
    ok = isinstance(high, (int, float)) and high <= BUDGET_USD
    return {
        "budget_usd": BUDGET_USD,
        "max_calls": MAX_CALLS,
        "estimate_low": low,
        "estimate_high": high,
        "within_budget": ok,
        "rate": estimate.get("rate") or OFFICIAL_RATES,
        "note": (
            f"Schatting high USD {high} ligt binnen hard budget USD {BUDGET_USD}."
            if ok
            else f"Schatting high USD {high} overschrijdt budget USD {BUDGET_USD}."
        ),
    }


def execute_prepared_trial(conn, client_id: int) -> dict[str, Any]:
    """Run at most 3 paid analyses for the prepared Red Rock trial. No retries."""
    ensure_ai_tables(conn)
    if REQUEST_PROMPT_VERSION != PROMPT_VERSION:
        raise ValueError("Promptversie-mismatch tussen request builder en trial-module.")
    if not is_configured():
        raise ValueError("AI is niet geconfigureerd (AI_BASE_URL / AI_API_KEY / AI_MODEL).")

    run = conn.execute(
        "SELECT * FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    if run is None:
        raise ValueError("Geen voorbereide AI-proef voor deze klant.")
    if run["status"] == "running":
        raise ValueError("Uitvoering loopt al. Geen nieuwe aanvraag gestart.")
    if run["status"] == "completed" and run["executed_at"]:
        raise ValueError(
            "Er is al een echte uitvoering opgeslagen. Open de pagina om resultaten te bekijken; "
            "er start geen nieuwe aanvraag."
        )

    estimate = json.loads(run["estimate_json"] or "{}")
    precheck = _budget_precheck(estimate)
    if not precheck["within_budget"]:
        raise ValueError(precheck["note"])

    posts = list(
        conn.execute(
            """
            SELECT t.* FROM ai_trial_posts t
            JOIN posts p ON p.id = t.post_id
            WHERE t.trial_run_id = ? AND p.client_id = ?
            ORDER BY CASE t.role WHEN 'image' THEN 1 WHEN 'carousel' THEN 2 ELSE 3 END, t.id
            """,
            (run["id"], client_id),
        ).fetchall()
    )
    if len(posts) != MAX_CALLS:
        raise ValueError(f"Verwacht precies {MAX_CALLS} proefposts, gevonden {len(posts)}.")

    # Verify media before any paid call.
    media_plans: list[dict[str, Any]] = []
    for row in posts:
        payload = json.loads(row["request_payload_json"] or "{}")
        media_prep = payload.get("media_prep") or {}
        images = _verify_media(media_prep.get("images_for_model") or [])
        if not images:
            raise ValueError(
                f"Post {row['post_id']} ({row['role']}): geen lokale media om mee te sturen. "
                "Geen betaalde aanvraag gestart."
            )
        # Excel must stay out of the model request.
        if payload.get("excel_assessment_included") or payload.get("excel_insight_included"):
            raise ValueError("Excel-beoordeling mag niet in de AI-aanvraag zitten.")
        media_plans.append(
            {
                "row": row,
                "payload": payload,
                "media_prep": media_prep,
                "images": images,
                "limitations": list(media_prep.get("limitations") or []),
            }
        )

    config = load_ai_config()
    conn.execute(
        "UPDATE ai_trial_runs SET status = 'running' WHERE id = ?",
        (run["id"],),
    )

    call_count = 0
    spent = 0.0
    spent_known = True
    outcomes: list[dict[str, Any]] = []

    for plan in media_plans:
        if call_count >= MAX_CALLS:
            break
        if spent_known and spent >= BUDGET_USD:
            outcomes.append(
                {
                    "post_id": plan["row"]["post_id"],
                    "status": "skipped_budget",
                    "error": "Restbudget ontoereikend; geen verdere aanvraag.",
                }
            )
            break

        row = plan["row"]
        payload = plan["payload"]
        system_text = str(payload.get("system_text") or "")
        user_text = str(payload.get("user_text") or "")
        if not system_text or not user_text:
            raise ValueError(f"Post {row['post_id']}: ontbrekende prompttekst; geen aanvraag.")

        user_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    user_text
                    + "\n\nBeoordeel alleen wat je in de meegestuurde beelden en caption ziet. "
                    "Claim geen audio, gesproken hook of niet-meegestuurde slides/video."
                ),
            }
        ]
        for img in plan["images"]:
            label = img.get("role") or "image"
            ts = img.get("timestamp_s")
            ts_bit = f" @ {ts}s" if ts is not None else ""
            user_content.append({"type": "text", "text": f"MEDIA {label}{ts_bit}:"})
            user_content.append(_image_part(Path(img["abs_path"])))

        started = _now()
        call_count += 1
        request_body = {
            "model": config.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "maaike_postanalyse_trial",
                    "strict": True,
                    "schema": _RESPONSE_SCHEMA,
                },
            },
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_content},
            ],
        }

        usage = {
            "reported": False,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }
        raw_text = ""
        http_status = None
        error = None
        parsed: dict[str, Any] | None = None
        validation_info: dict[str, Any] | None = None
        try:
            response = requests.post(
                chat_completions_url(config.base_url),
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
                timeout=REQUEST_TIMEOUT_S,
            )
            http_status = response.status_code
            # No automatic retry — record usage even on failure when present.
            try:
                body = response.json()
            except ValueError:
                body = {}
            usage = _usage_from_body(body) if isinstance(body, dict) else usage
            if response.ok:
                raw_text = _message_text((body.get("choices") or [{}])[0].get("message", {}).get("content"))
                extracted = _extract_json(raw_text)
                if extracted:
                    from maaike.ai_response_validate import validate_post_analysis

                    candidate = _normalize_result(
                        extracted,
                        role=row["role"],
                        limitations=plan["limitations"],
                    )
                    validation = validate_post_analysis(
                        candidate,
                        raw_text=raw_text,
                        role=row["role"],
                        limitations=plan["limitations"],
                    )
                    validation_info = validation.as_dict()
                    if validation.usable and validation.normalized:
                        parsed = validation.normalized
                    else:
                        error = (
                            validation.user_message
                            or "AI-antwoord voldoet niet aan het vaste postanalyse-formaat."
                        )
                        parsed = None
                else:
                    error = "Ongeldig of leeg JSON-antwoord van het model."
            else:
                error = f"HTTP {response.status_code} van AI-aanbieder (geen herhaling)."
        except requests.RequestException as exc:
            error = f"Netwerkfout zonder herhaling: {exc.__class__.__name__}"

        actual_cost, cost_known = _cost_usd(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        if cost_known and actual_cost is not None:
            spent += actual_cost
        else:
            spent_known = False

        finished = _now()
        status = "completed" if parsed is not None else "failed"
        live_blob = {
            "executed_at": finished,
            "provider": "Google Gemini Developer API",
            "model": config.model,
            "prompt_version": PROMPT_VERSION,
            "images_sent": [
                {
                    "role": i.get("role"),
                    "path": i.get("path"),
                    "bytes": i.get("bytes_on_disk"),
                    "timestamp_s": i.get("timestamp_s"),
                }
                for i in plan["images"]
            ],
            "limitations": plan["limitations"],
            "result": parsed,
            "raw_excerpt": (raw_text or "")[:2000],
            "raw_response": (raw_text or "")[:50000],
            "error": error,
            "http_status": http_status,
            "usage": usage,
            "actual_cost_usd": actual_cost if cost_known else None,
            "cost_known": cost_known,
            "budget": {"cap_usd": BUDGET_USD, "spent_so_far_usd": round(spent, 6) if spent_known else None},
            "accepted_automatically": False,
            "excel_included_in_request": False,
            "analysis_usable": parsed is not None,
            "validation": validation_info,
        }
        new_payload = dict(payload)
        new_payload["_live_ai_result"] = live_blob
        # Drop prior mock acceptance markers; do not auto-accept.
        new_payload.pop("_accepted_proposal", None)

        if parsed is not None:
            conn.execute(
                """
                UPDATE ai_trial_posts SET
                    request_payload_json = ?,
                    ai_observations_json = ?,
                    ai_format_code = ?,
                    ai_format_rationale = ?,
                    ai_format_uncertainty = ?,
                    ai_pillar = ?,
                    ai_hook = ?,
                    ai_insight = ?,
                    ai_action = ?,
                    status = 'completed',
                    joint_verdict = CASE
                        WHEN trim(coalesce(human_feedback,'')) = '' THEN
                            'Alleen AI-analyse aanwezig — geen gezamenlijk eindoordeel zonder menselijke beoordeling.'
                        ELSE joint_verdict
                    END
                WHERE trial_run_id = ? AND post_id = ?
                """,
                (
                    json.dumps(new_payload, ensure_ascii=False),
                    json.dumps(parsed["observations"], ensure_ascii=False),
                    parsed["proposed_format_code"],
                    parsed["format_rationale"],
                    parsed["format_uncertainty"],
                    parsed["proposed_pillar"],
                    parsed["proposed_hook"],
                    parsed["ai_insight"],
                    parsed["ai_action"],
                    run["id"],
                    row["post_id"],
                ),
            )
        else:
            conn.execute(
                """
                UPDATE ai_trial_posts SET
                    request_payload_json = ?,
                    status = 'failed',
                    joint_verdict = CASE
                        WHEN trim(coalesce(human_feedback,'')) = '' THEN
                            'Geen bruikbaar AI-resultaat — geen gezamenlijk eindoordeel.'
                        ELSE joint_verdict
                    END
                WHERE trial_run_id = ? AND post_id = ?
                """,
                (
                    json.dumps(new_payload, ensure_ascii=False),
                    run["id"],
                    row["post_id"],
                ),
            )

        conn.execute(
            """
            UPDATE ai_usage_events SET
                started_at = ?,
                finished_at = ?,
                status = ?,
                provider = ?,
                model = ?,
                prompt_version = ?,
                prompt_tokens = ?,
                completion_tokens = ?,
                total_tokens = ?,
                currency = ?,
                actual_cost = ?,
                cost_known = ?,
                rate_date = ?,
                notes = ?
            WHERE trial_run_id = ? AND post_id = ?
            """,
            (
                started,
                finished,
                status if parsed is not None else "failed_may_still_cost",
                "Google Gemini Developer API",
                config.model,
                PROMPT_VERSION,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
                OFFICIAL_RATES["currency"],
                actual_cost if cost_known else None,
                1 if cost_known else 0,
                OFFICIAL_RATES["rate_date"],
                (
                    f"Echte aanvraag; {len(plan['images'])} beelden meegestuurd. "
                    + (
                        f"Kosten USD {actual_cost} op tarief {OFFICIAL_RATES['rate_date']}."
                        if cost_known
                        else "Kosten onbekend (tokens ontbreken); niet als 0 opgeslagen."
                    )
                    + (f" Fout: {error}" if error else "")
                ),
                run["id"],
                row["post_id"],
            ),
        )
        outcomes.append(
            {
                "post_id": row["post_id"],
                "role": row["role"],
                "status": status,
                "images_sent": len(plan["images"]),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "actual_cost_usd": actual_cost if cost_known else None,
                "cost_known": cost_known,
                "error": error,
                "format": None if parsed is None else parsed["proposed_format_code"],
            }
        )

    total_cost = round(spent, 6) if spent_known else None
    ok_posts = sum(1 for o in outcomes if o.get("status") == "completed")
    run_status = "completed" if ok_posts > 0 else "failed"
    notes = json.loads(run["notes_json"] or "[]")
    notes = [
        n
        for n in notes
        if "Geen betaalde AI-aanvraag" not in str(n)
    ]
    notes.extend(
        [
            f"Echte uitvoering: {call_count} aanvraag(en), max {MAX_CALLS}, budget USD {BUDGET_USD}.",
            (
                f"Werkelijke kostenproef: USD {total_cost}."
                if total_cost is not None
                else "Werkelijke totale kosten onbekend (ontbrekende tokenrapportage)."
            ),
            f"Bruikbare postanalyses: {ok_posts}/{len(outcomes)} (runstatus={run_status}).",
            "Formatvoorstellen niet automatisch geaccepteerd; Excel/editorial niet overschreven.",
            "Pagina herladen start geen nieuwe aanvraag.",
            precheck["note"],
        ]
    )
    conn.execute(
        """
        UPDATE ai_trial_runs SET
            status = ?,
            executed_at = ?,
            provider = ?,
            model = ?,
            prompt_version = ?,
            notes_json = ?
        WHERE id = ?
        """,
        (
            run_status,
            _now(),
            "Google Gemini Developer API",
            config.model,
            PROMPT_VERSION,
            json.dumps(notes, ensure_ascii=False),
            run["id"],
        ),
    )
    result = get_trial(conn, client_id)
    result["execution_summary"] = {
        "precheck": precheck,
        "calls": call_count,
        "max_calls": MAX_CALLS,
        "spent_usd": total_cost,
        "spent_known": spent_known,
        "outcomes": outcomes,
        "auto_accepted": False,
    }
    return result
