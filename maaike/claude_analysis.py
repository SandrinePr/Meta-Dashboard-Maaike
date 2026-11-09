"""Claude post analysis using Maaike Social Agent prompt files. Never invents prompts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values

from maaike.activity_log import record_activity
from maaike.presentation import overview_record
from maaike.report_metrics import build_period_metrics, trend_lookback_bounds, _parse_day
from maaike.repository import list_formats, list_posts
from maaike.strategy import get_strategy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOCIAL_AGENT_DIR = PROJECT_ROOT / "data" / "imports" / "redrock" / "social_agent"
ENV_FILE = PROJECT_ROOT / ".env"
PROMPT_VERSION = "maaike-performance-analyse-v2"

REQUIRED_FILES = (
    "Performance-analyse richtlijnen.txt",
    "Role - Algemene instructies.txt",
    "Kwaliteitsstandaard.txt",
)

# Prefer CLAUDE_API_KEY; fall back to ANTHROPIC_API_KEY.
_KEY_VARS = ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _read(name: str) -> str:
    path = SOCIAL_AGENT_DIR / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def resolve_claude_api_key() -> dict[str, Any]:
    """Resolve Claude key without logging the value.

    Project ``.env`` wins over process/user environment so a stale shell key
    cannot override a newly set file value.
    """
    file_vals = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    for var in _KEY_VARS:
        value = str(file_vals.get(var) or "").strip()
        if value:
            return {
                "key": value,
                "variable": var,
                "source": "dotenv",
                "env_file": str(ENV_FILE.name),
            }
    for var in _KEY_VARS:
        value = os.getenv(var, "").strip()
        if value:
            return {
                "key": value,
                "variable": var,
                "source": "process",
                "env_file": str(ENV_FILE.name),
            }
    return {
        "key": "",
        "variable": None,
        "source": "missing",
        "env_file": str(ENV_FILE.name),
    }


def load_analysis_prompt_bundle() -> dict[str, Any]:
    bodies = {name: _read(name) for name in REQUIRED_FILES}
    missing = [name for name, body in bodies.items() if not body]
    system_parts = [
        "Je werkt voor Red Rock Agency. Gebruik uitsluitend de meegeleverde instructies en postgegevens.",
        "Verzin geen cijfers. Ontbrekende metrics zijn onbekend, niet 0.",
        "Lever insight, actie en beoordeling (Goed/Gemiddeld/Slecht) volgens de richtlijnen.",
        "Als vergelijkingsposts, format-tab of periodeoverzicht ontbreken: benoem die beperking "
        "expliciet en trek geen ongefundeerde patroonconclusies.",
        "",
    ]
    for name in REQUIRED_FILES:
        system_parts.append(f"=== {name} ===")
        system_parts.append(bodies[name][:20000] if bodies[name] else f"(ONTBREEKT: {name})")
        system_parts.append("")
    return {
        "prompt_version": PROMPT_VERSION,
        "files": {
            name: {"chars": len(bodies[name]), "loaded": bool(bodies[name])} for name in REQUIRED_FILES
        },
        "missing_files": missing,
        "system_text": "\n".join(system_parts),
        "system_chars": sum(len(p) for p in system_parts),
        "ready": not missing,
        "data_expectations": {
            "prefers_period_post_set": True,
            "prefers_format_catalog": True,
            "prefers_visual_review_via_permalink": True,
            "single_post_limitation": (
                "Maaike's performance analysis targets a period overview (Post performance), "
                "format tab and comparison. A single-post analysis is useful for insight/action/"
                "rating of that post, but must not claim unsupported format or period patterns."
            ),
        },
    }


def claude_connection_status() -> dict[str, Any]:
    resolved = resolve_claude_api_key()
    key = resolved["key"]
    model = (
        str(dotenv_values(ENV_FILE).get("CLAUDE_MODEL") or "").strip()
        if ENV_FILE.exists()
        else ""
    ) or os.getenv("CLAUDE_MODEL", "").strip() or "claude-sonnet-4-5"
    base = (
        str(dotenv_values(ENV_FILE).get("CLAUDE_API_BASE") or "").strip()
        if ENV_FILE.exists()
        else ""
    ) or os.getenv("CLAUDE_API_BASE", "").strip() or "https://api.anthropic.com"
    notes = [
        "The key stays server-side. AI Connections only shows present/missing.",
        "Analyses start only via an explicit execute action.",
        f"Preferred: set CLAUDE_API_KEY in {ENV_FILE.name} (project root). That value wins over a process environment.",
        "Alternative in the same file: ANTHROPIC_API_KEY (only if CLAUDE_API_KEY is missing).",
    ]
    if resolved["source"] == "process":
        notes.append(
            "Current key comes from the process environment, not from .env. "
            "Set CLAUDE_API_KEY in .env to override an old process value; then restart the API."
        )
    elif resolved["source"] == "missing":
        notes.append("No Claude key found in .env or the process environment.")
    return {
        "provider": "Anthropic Claude API",
        "configured": bool(key),
        "has_api_key": bool(key),
        "key_variable": resolved["variable"],
        "key_source": resolved["source"],
        "model": model,
        "base_host": base.replace("https://", "").replace("http://", "").split("/")[0],
        "missing_setting": None if key else "CLAUDE_API_KEY in .env (projectroot)",
        "env_file_hint": f"{ENV_FILE.name} in projectroot (server-side; nooit in de frontend)",
        "notes": notes,
    }


def probe_claude_connection() -> dict[str, Any]:
    """Minimal live check. Never returns or logs the key value."""
    status = claude_connection_status()
    if not status["configured"]:
        return {
            "ok": False,
            "reachable": False,
            "http_status": None,
            "detail": f"No key. Set {status['missing_setting']}.",
            "key_variable": status["key_variable"],
            "key_source": status["key_source"],
            "model": status["model"],
        }
    resolved = resolve_claude_api_key()
    base = (
        str(dotenv_values(ENV_FILE).get("CLAUDE_API_BASE") or "").strip()
        if ENV_FILE.exists()
        else ""
    ) or os.getenv("CLAUDE_API_BASE", "").strip() or "https://api.anthropic.com"
    url = f"{base.rstrip('/')}/v1/messages"
    try:
        response = requests.post(
            url,
            headers={
                "content-type": "application/json",
                "x-api-key": resolved["key"],
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": status["model"],
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Antwoord met precies: ok"}],
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "reachable": False,
            "http_status": None,
            "detail": f"Network error: {exc.__class__.__name__}",
            "key_variable": status["key_variable"],
            "key_source": status["key_source"],
            "model": status["model"],
        }
    ok = response.status_code == 200
    detail = "Claude reachable." if ok else "Claude rejected or failed."
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not ok and isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            detail = str(err.get("message"))
            if "key" in detail.lower():
                detail = (
                    "Key rejected by Anthropic. Replace CLAUDE_API_KEY in .env "
                    "and restart the API."
                )
    return {
        "ok": ok,
        "reachable": ok,
        "http_status": response.status_code,
        "detail": detail,
        "key_variable": status["key_variable"],
        "key_source": status["key_source"],
        "model": status["model"],
    }


def ensure_analysis_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS post_ai_analyses (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            insight_text TEXT NOT NULL DEFAULT '',
            action_text TEXT NOT NULL DEFAULT '',
            rating_text TEXT NOT NULL DEFAULT '',
            raw_response_json TEXT NOT NULL DEFAULT '{}',
            usage_json TEXT NOT NULL DEFAULT '{}',
            input_snapshot_json TEXT NOT NULL DEFAULT '{}',
            error_text TEXT NOT NULL DEFAULT '',
            actual_cost_usd REAL,
            cost_known INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        );
        """
    )


def build_post_input_snapshot(conn, client_id: int, post_id: int) -> dict[str, Any]:
    posts = {p.post_id: p for p in list_posts(conn, client_id)}
    post = posts.get(post_id)
    if post is None:
        raise ValueError("Post not found for this client.")
    cells = overview_record(post)

    format_catalog = [
        {
            "name": item.name,
            "explanation": item.explanation or "",
        }
        for item in list_formats(conn, client_id)
    ]
    matched_format = next(
        (f for f in format_catalog if f["name"] and f["name"] == (post.format_name or "")),
        None,
    )

    pub_day = _parse_day(post.published_at)
    period_overview: dict[str, Any] | None = None
    lookback_window: dict[str, Any] | None = None
    context_gaps: list[str] = []
    if pub_day is None:
        context_gaps.append("published_at ontbreekt — geen periodeoverzicht af te leiden.")
    else:
        # Calendar month of the post (Python metrics; same helper as klantrapport).
        try:
            month_bundle = build_period_metrics(
                conn, client_id, period_year=pub_day.year, period_month=pub_day.month
            )
            metrics = month_bundle["metrics"]
            period_overview = {
                "window_mode": "calendar_month_of_post",
                "period": month_bundle["period"],
                "post_count": metrics.get("post_count"),
                "totals": metrics.get("totals"),
                "averages": metrics.get("averages"),
                "by_format": (metrics.get("by_format") or [])[:20],
                "by_pillar": (metrics.get("by_pillar") or [])[:20],
                "by_hook": (metrics.get("by_hook") or [])[:20],
                "comparison": month_bundle.get("comparison"),
                "peer_posts": [
                    {
                        "post_id": p.get("post_id"),
                        "published_date": p.get("published_date"),
                        "content_kind": p.get("content_kind"),
                        "format_name": p.get("format_name"),
                        "pillar_name": p.get("pillar_name"),
                        "hook": p.get("hook"),
                        "metrics": p.get("metrics"),
                        "is_focus_post": p.get("post_id") == post_id,
                    }
                    for p in (month_bundle.get("posts") or [])[:40]
                ],
            }
        except ValueError as exc:
            context_gaps.append(f"Periodeoverzicht (kalendermaand) niet beschikbaar: {exc}")

        # Standard Performance lookback (21e vorige → 20e huidige) around post month.
        lookback = trend_lookback_bounds(pub_day.year, pub_day.month)
        try:
            look_bundle = build_period_metrics(
                conn,
                client_id,
                start=lookback["lookback_start"],
                end=lookback["lookback_end"],
            )
            lookback_window = {
                "window_mode": "performance_lookback_21_to_20",
                "bounds": lookback,
                "period": look_bundle["period"],
                "post_count": (look_bundle["metrics"] or {}).get("post_count"),
                "by_format": ((look_bundle["metrics"] or {}).get("by_format") or [])[:20],
                "comparison": look_bundle.get("comparison"),
            }
        except ValueError as exc:
            context_gaps.append(f"Lookback-periodeoverzicht niet beschikbaar: {exc}")

    if not format_catalog:
        context_gaps.append("Format-tab/catalogus leeg voor deze klant.")
    if post.format_name and matched_format is None:
        context_gaps.append(
            f"Formatcode '{post.format_name}' staat niet in de Format-tab van deze klant."
        )
    elif not (post.format_name or "").strip():
        context_gaps.append("Deze post heeft geen formatcode gekoppeld.")

    strategy = get_strategy(conn, client_id)
    strategy_summary = {
        "completed_at": strategy.get("completed_at"),
        "pending_questions": strategy.get("pending_questions"),
        "start_answer_keys": list((strategy.get("start_answers") or {}).keys()),
        "has_start_answers": bool(strategy.get("start_answers")),
    }
    if not strategy_summary["has_start_answers"]:
        context_gaps.append("Klantstrategie/startantwoorden ontbreken.")

    return {
        "post_id": post_id,
        "platform": post.platform,
        "external_id": post.external_id,
        "published_at": post.published_at,
        "permalink": post.permalink,
        "content_kind": post.content_kind,
        "format_name": post.format_name,
        "format_tab_entry": matched_format,
        "pillar_name": post.pillar_name,
        "hook": post.hook,
        "caption": (post.caption or "")[:4000],
        "metrics": {
            "views": post.views,
            "reach": post.reach,
            "likes": post.likes,
            "comments": post.comments,
            "shares": post.shares,
            "saves": post.saves,
            "clicks": post.clicks,
        },
        "overview_cells": cells,
        "existing_insight": post.insight_text or "",
        "existing_action": post.action_text or "",
        "existing_rating": post.rating_text or "",
        "source_origin": post.source_origin,
        "period_overview": period_overview,
        "performance_lookback": lookback_window,
        "format_catalog": format_catalog,
        "strategy_summary": strategy_summary,
        "context_present": {
            "period_overview": period_overview is not None,
            "performance_lookback": lookback_window is not None,
            "format_catalog": bool(format_catalog),
            "format_tab_match": matched_format is not None,
            "strategy": strategy_summary["has_start_answers"],
            "permalink": bool(post.permalink),
        },
        "context_gaps": context_gaps,
        "ai_must_not_invent_numbers": True,
        "missing_metrics_are_unknown_not_zero": True,
        "single_post_plus_period_context": True,
    }


def _estimate_cost_usd(input_tokens: int | None, output_tokens: int | None, model: str) -> tuple[float | None, bool, str]:
    # Public Anthropic Sonnet-class ballpark; exact SKU may differ — mark uncertain.
    # Sonnet 4.5 typical: input ~$3/MTok, output ~$15/MTok (verify on docs when key available).
    rates = {"input_per_1m": 3.0, "output_per_1m": 15.0, "rate_date": "2026-11-02", "assumed_sku": model}
    if input_tokens is None or output_tokens is None:
        return None, False, "Token usage unknown; cost not shown as 0."
    cost = (input_tokens / 1_000_000) * rates["input_per_1m"] + (output_tokens / 1_000_000) * rates[
        "output_per_1m"
    ]
    return round(cost, 6), True, f"Estimate based on assumed rate {rates} — verify Anthropic pricing."


def _parse_json_loose(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"raw": data}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
    return {"insight": text[:2000], "action": "", "rating": ""}


def run_claude_post_analysis(conn, client_id: int, post_id: int) -> dict[str, Any]:
    """One Claude Messages API call. No automatic retries."""
    ensure_analysis_tables(conn)
    bundle = load_analysis_prompt_bundle()
    if not bundle["ready"]:
        raise ValueError(
            "Missing Social Agent prompt files: " + ", ".join(bundle["missing_files"])
        )
    status = claude_connection_status()
    if not status["configured"]:
        raise ValueError(
            f"Claude not configured. Set {status['missing_setting']} ({status['env_file_hint']})."
        )

    snapshot = build_post_input_snapshot(conn, client_id, post_id)
    snapshot["analysis_scope"] = "single_post"
    snapshot["prompt_data_limitation"] = bundle.get("data_expectations", {}).get("single_post_limitation")
    resolved = resolve_claude_api_key()
    api_key = resolved["key"]
    model = status["model"]
    base = (
        str(dotenv_values(ENV_FILE).get("CLAUDE_API_BASE") or "").strip()
        if ENV_FILE.exists()
        else ""
    ) or os.getenv("CLAUDE_API_BASE", "").strip() or "https://api.anthropic.com"
    url = f"{base.rstrip('/')}/v1/messages"
    user_text = (
        "Analyseer deze post volgens de instructies. "
        "De JSON bevat naast de focuspost ook periodeoverzicht, lookback (21e→20e) en Format-tab "
        "wanneer die lokaal beschikbaar zijn. Trek geen patroonconclusies over ontbrekende context "
        "(zie context_gaps). "
        "Antwoord uitsluitend als JSON met keys: insight, action, rating, notes.\n\n"
        + json.dumps(snapshot, ensure_ascii=False)
    )
    started = _now()
    try:
        response = requests.post(
            url,
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model,
                "max_tokens": 1200,
                "temperature": 0.2,
                "system": bundle["system_text"][:100000],
                "messages": [{"role": "user", "content": user_text[:80000]}],
            },
            timeout=120,
        )
    except requests.RequestException as exc:
        finished = _now()
        usage = {
            "status": "failed_network",
            "cost_known": False,
            "actual_cost_usd": None,
            "error": exc.__class__.__name__,
        }
        cur = conn.execute(
            """
            INSERT INTO post_ai_analyses (
                client_id, post_id, provider, model, prompt_version, status,
                started_at, finished_at, error_text, usage_json, input_snapshot_json, cost_known
            ) VALUES (?, ?, 'Anthropic Claude', ?, ?, 'failed', ?, ?, ?, ?, ?, 0)
            """,
            (
                client_id,
                post_id,
                model,
                PROMPT_VERSION,
                started,
                finished,
                f"Network error without retry: {exc.__class__.__name__}",
                json.dumps(usage, ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )
        analysis_id = int(cur.lastrowid)
        record_activity(
            conn,
            client_id=client_id,
            activity_type="ai_analysis",
            status="failed",
            title=f"Claude analysis for post {post_id} failed",
            details=f"Network error: {exc.__class__.__name__}",
            source_ref=str(analysis_id),
            is_error=True,
        )
        # Return saved failure so the surrounding DB transaction can commit.
        return get_analysis(conn, client_id, analysis_id)

    finished = _now()
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        err = body.get("error") if isinstance(body, dict) else None
        message = ""
        if isinstance(err, dict):
            message = str(err.get("message") or "")
        usage = {
            "status": "failed_http",
            "http_status": response.status_code,
            "cost_known": False,
            "actual_cost_usd": None,
            "note": "A failed request may still incur cost; tokens unknown.",
        }
        cur = conn.execute(
            """
            INSERT INTO post_ai_analyses (
                client_id, post_id, provider, model, prompt_version, status,
                started_at, finished_at, error_text, usage_json, input_snapshot_json,
                raw_response_json, cost_known
            ) VALUES (?, ?, 'Anthropic Claude', ?, ?, 'failed', ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                client_id,
                post_id,
                model,
                PROMPT_VERSION,
                started,
                finished,
                message or f"HTTP {response.status_code}",
                json.dumps(usage, ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False),
                json.dumps(body, ensure_ascii=False)[:20000],
            ),
        )
        analysis_id = int(cur.lastrowid)
        if "invalid" in (message or "").lower() and "key" in (message or "").lower():
            message = (
                (message or "invalid x-api-key")
                + " — replace CLAUDE_API_KEY or ANTHROPIC_API_KEY in .env (project root) and restart the API."
            )
            conn.execute(
                "UPDATE post_ai_analyses SET error_text = ? WHERE id = ?",
                (message, analysis_id),
            )
        record_activity(
            conn,
            client_id=client_id,
            activity_type="ai_analysis",
            status="failed",
            title=f"Claude analysis for post {post_id} failed",
            details=message or f"HTTP {response.status_code}",
            source_ref=str(analysis_id),
            is_error=True,
        )
        # Return saved failure (do not raise) so the API transaction commits the row.
        return get_analysis(conn, client_id, analysis_id)

    parts = body.get("content") if isinstance(body, dict) else None
    texts = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(str(part.get("text") or ""))
    raw_text = "\n".join(texts)
    parsed = _parse_json_loose(raw_text)
    insight = str(parsed.get("insight") or parsed.get("Insight") or "").strip()
    action = str(parsed.get("action") or parsed.get("Actie") or parsed.get("actie") or "").strip()
    rating = str(parsed.get("rating") or parsed.get("Beoordeling") or parsed.get("beoordeling") or "").strip()
    usage_meta = body.get("usage") if isinstance(body, dict) else {}
    in_tok = usage_meta.get("input_tokens") if isinstance(usage_meta, dict) else None
    out_tok = usage_meta.get("output_tokens") if isinstance(usage_meta, dict) else None
    cost, known, cost_note = _estimate_cost_usd(in_tok, out_tok, model)
    usage = {
        "status": "completed",
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "actual_cost_usd": cost,
        "cost_known": known,
        "notes": cost_note,
        "prompt_version": PROMPT_VERSION,
    }
    cur = conn.execute(
        """
        INSERT INTO post_ai_analyses (
            client_id, post_id, provider, model, prompt_version, status,
            started_at, finished_at, insight_text, action_text, rating_text,
            raw_response_json, usage_json, input_snapshot_json, error_text,
            actual_cost_usd, cost_known
        ) VALUES (?, ?, 'Anthropic Claude', ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
        """,
        (
            client_id,
            post_id,
            model,
            PROMPT_VERSION,
            started,
            finished,
            insight,
            action,
            rating,
            json.dumps({"text": raw_text[:20000], "usage": usage_meta}, ensure_ascii=False),
            json.dumps(usage, ensure_ascii=False),
            json.dumps(snapshot, ensure_ascii=False),
            cost,
            1 if known else 0,
        ),
    )
    analysis_id = int(cur.lastrowid)
    # Persist into assessments so Logs can reopen insight/action
    conn.execute(
        """
        INSERT INTO post_assessments (
            post_id, source, source_label, rating_text, insight_text, action_text, imported_at
        ) VALUES (?, 'claude_analysis', ?, ?, ?, ?, ?)
        """,
        (post_id, f"Claude {model}", rating or None, insight, action, finished),
    )
    record_activity(
        conn,
        client_id=client_id,
        activity_type="ai_analysis",
        status="completed",
        title=f"Claude analysis for post {post_id}",
        details=f"id={analysis_id}; rating={rating}; cost_known={known}",
        source_ref=str(analysis_id),
    )
    return get_analysis(conn, client_id, analysis_id)


def get_analysis(conn, client_id: int, analysis_id: int) -> dict[str, Any]:
    ensure_analysis_tables(conn)
    row = conn.execute(
        "SELECT * FROM post_ai_analyses WHERE id = ? AND client_id = ?",
        (analysis_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Analysis not found.")
    return {
        "analysis": {
            **dict(row),
            "usage": json.loads(row["usage_json"] or "{}"),
            "input_snapshot": json.loads(row["input_snapshot_json"] or "{}"),
            "raw_response": json.loads(row["raw_response_json"] or "{}"),
            "cost_known": bool(row["cost_known"]),
        }
    }


def list_analyses(conn, client_id: int, *, post_id: int | None = None) -> dict[str, Any]:
    ensure_analysis_tables(conn)
    q = "SELECT id, post_id, provider, model, prompt_version, status, started_at, finished_at, rating_text, cost_known, actual_cost_usd FROM post_ai_analyses WHERE client_id = ?"
    params: list[Any] = [client_id]
    if post_id is not None:
        q += " AND post_id = ?"
        params.append(post_id)
    q += " ORDER BY id DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    return {
        "analyses": rows,
        "prompt_bundle": load_analysis_prompt_bundle(),
        "claude": claude_connection_status(),
    }
