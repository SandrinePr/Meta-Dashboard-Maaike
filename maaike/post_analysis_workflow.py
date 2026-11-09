"""Post-level media inventory + prepare/save insight workflow for Maaike.

Reuses AI Trial media/request helpers. Opening or preparing does not call a paid model.
Reviewed insights are stored in post_ai_analyses so client reports can attach them.
"""

from __future__ import annotations

import json
from typing import Any

from maaike.ai_trial import (
    OFFICIAL_RATES,
    _capability_report,
    _media_access,
    _media_urls,
    _now,
    _post_metrics,
)
from maaike.ai_trial_media import classify_urls, prepare_post_media
from maaike.ai_trial_request import PROMPT_VERSION, build_request_package
from maaike.ai_status import public_ai_status
from maaike.claude_analysis import ensure_analysis_tables, get_analysis


def _role_for_kind(content_kind: str | None) -> str:
    kind = str(content_kind or "").lower()
    if "carousel" in kind or kind == "album":
        return "carousel"
    if "reel" in kind:
        return "reel"
    if "story" in kind:
        return "story"
    if kind in {"video", "added_video", "added_videos"}:
        return "reel"
    return "image"


def _figma_for_post(conn, client_id: int, post_id: int) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT id, node_id, source_url, page_name, period_year, period_month, code,
                   content_kind, format_raw, format_usable, pillar_raw, pillar_usable,
                   hook_raw, hook_usable, link_status
            FROM figma_planning_items
            WHERE client_id = ? AND linked_post_id = ?
            ORDER BY id
            """,
            (client_id, post_id),
        ).fetchall()
    except Exception:
        return []
    out = []
    for row in rows:
        out.append(
            {
                "source": "figma_planning",
                "item_id": row["id"],
                "node_id": row["node_id"],
                "source_url": row["source_url"],
                "page_name": row["page_name"],
                "period_year": row["period_year"],
                "period_month": row["period_month"],
                "code": row["code"],
                "content_kind": row["content_kind"],
                "format_raw": row["format_raw"],
                "format_usable": bool(row["format_usable"]),
                "pillar_raw": row["pillar_raw"],
                "pillar_usable": bool(row["pillar_usable"]),
                "hook_raw": row["hook_raw"],
                "hook_usable": bool(row["hook_usable"]),
                "link_status": row["link_status"],
                "note": "Planned Figma material — not published Meta media.",
            }
        )
    return out


def inventory_for_post(conn, client_id: int, post_id: int) -> dict[str, Any]:
    """What Maaike can see vs what a prepare step can send to the model."""
    post = conn.execute(
        """
        SELECT id, client_id, platform, content_kind, media_urls, permalink, caption, published_at
        FROM posts WHERE id = ? AND client_id = ?
        """,
        (post_id, client_id),
    ).fetchone()
    if post is None:
        raise ValueError("Post not found for this client.")

    urls = _media_urls(post["media_urls"])
    classified = classify_urls(urls)
    role = _role_for_kind(post["content_kind"])
    access = _media_access(post["content_kind"], urls)

    uploads: list[dict[str, Any]] = []
    try:
        from maaike.post_media_upload import list_post_media

        uploads = list_post_media(conn, client_id, post_id)
    except Exception:
        uploads = []

    figma = _figma_for_post(conn, client_id, post_id)
    limitations: list[str] = []
    if role == "reel":
        has_video = any(c.get("guessed_kind") == "video" for c in classified) or any(
            u.get("kind") == "video" for u in uploads
        )
        has_image = any(c.get("guessed_kind") == "image" for c in classified) or any(
            u.get("kind") == "image" for u in uploads
        )
        if has_image and not has_video:
            limitations.append(
                "Reel appears to have thumbnail/image only — no full video bytes for the model."
            )
        elif not has_video and not has_image:
            limitations.append("No reachable reel media (no video, no thumbnail).")
        else:
            limitations.append("Reel video is prepared as sampled frames, not full video/audio.")
    if role == "story":
        if not urls and not uploads:
            limitations.append("No story media available for this post.")
    if role == "carousel" and len(classified) + len(uploads) <= 1:
        limitations.append("Carousel may be incomplete — fewer than two slides found.")
    if not urls and not uploads:
        limitations.append("No published Meta media URLs and no uploads.")

    return {
        "post_id": post_id,
        "client_id": client_id,
        "platform": post["platform"],
        "content_kind": post["content_kind"],
        "analysis_role": role,
        "permalink": post["permalink"],
        "published_at": post["published_at"],
        "caption_preview": (post["caption"] or "")[:240],
        "published_media": {
            "source": "meta_sync_or_import",
            "urls": classified,
            "count": len(classified),
        },
        "uploaded_media": {
            "source": "manual_upload",
            "assets": uploads,
            "count": len(uploads),
        },
        "figma_planning": {
            "source": "figma_planning_items",
            "items": figma,
            "count": len(figma),
            "note": "Shown separately from published material.",
        },
        "media_access": access,
        "limitations": limitations,
        "ai_can_use_on_prepare": {
            "caption": True,
            "images_or_frames": bool(urls or uploads),
            "full_video_bytes": False,
            "audio": False,
            "figma_assets_as_published": False,
        },
        "paid_call_on_open": False,
        "paid_call_on_prepare": False,
    }


def prepare_post_analysis(
    conn,
    client_id: int,
    post_id: int,
    *,
    download_media: bool = True,
) -> dict[str, Any]:
    """Prepare one post for analysis without a paid model call."""
    ensure_analysis_tables(conn)
    inventory = inventory_for_post(conn, client_id, post_id)
    post = conn.execute(
        """
        SELECT id, client_id, platform, content_kind, media_urls, permalink, caption, published_at
        FROM posts WHERE id = ? AND client_id = ?
        """,
        (post_id, client_id),
    ).fetchone()
    urls = _media_urls(post["media_urls"])
    role = inventory["analysis_role"]

    legend = conn.execute(
        """
        SELECT name, explanation FROM content_formats
        WHERE client_id = ? AND length(trim(explanation)) > 0
        ORDER BY name
        """,
        (client_id,),
    ).fetchall()
    legend_formats = [{"code": r["name"], "explanation": r["explanation"]} for r in legend]
    pillars = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM content_pillars WHERE client_id = ? ORDER BY name",
            (client_id,),
        ).fetchall()
    ]

    local_assets = None
    try:
        from maaike.post_media_upload import local_paths_for_analysis

        local_assets = local_paths_for_analysis(conn, client_id, post_id) or None
        # Ignore tiny stub uploads (<1 KB) so real Meta/cache media can be used.
        if local_assets:
            usable = [a for a in local_assets if int(a.get("bytes") or 0) >= 1000]
            local_assets = usable or None
    except Exception:
        local_assets = None

    if download_media and (urls or local_assets):
        media_prep = prepare_post_media(
            client_id=client_id,
            post_id=post_id,
            role=role if role != "story" else "image",
            content_kind=post["content_kind"],
            media_urls=urls,
            local_assets=local_assets,
        )
        # Expired Meta CDN URLs: reuse previously cached trial/local files when present.
        if not (media_prep.get("images_for_model") or []) and not local_assets:
            from pathlib import Path

            from maaike.ai_trial_media import MEDIA_ROOT, PROJECT_ROOT

            cache_dir = MEDIA_ROOT / f"client_{client_id}" / f"post_{post_id}"
            cached: list[dict[str, Any]] = []
            if cache_dir.is_dir():
                index = 0
                for path in sorted(cache_dir.glob("part_*")):
                    if not path.is_file() or path.stat().st_size <= 0:
                        continue
                    index += 1
                    rel = path.relative_to(PROJECT_ROOT).as_posix()
                    suffix = path.suffix.lower()
                    kind = "video" if suffix in {".mp4", ".mov", ".m4v", ".webm"} else "image"
                    cached.append(
                        {
                            "index": index,
                            "kind": kind,
                            "path": rel,
                            "bytes": path.stat().st_size,
                        }
                    )
            if cached:
                media_prep = prepare_post_media(
                    client_id=client_id,
                    post_id=post_id,
                    role=role if role != "story" else "image",
                    content_kind=post["content_kind"],
                    media_urls=[],
                    local_assets=cached,
                )
                media_prep["media_source"] = "local_cache_after_cdn_miss"
                media_prep.setdefault("limitations", []).append(
                    "Meta media URL was unreachable; used previously cached local media."
                )
    else:
        media_prep = {
            "coverage": "none" if not urls and not local_assets else "skipped_download",
            "images_for_model": [],
            "missing": inventory["limitations"] or ["no media"],
            "limitations": inventory["limitations"],
            "full_video_to_model": False,
            "audio_to_model": False,
            "media_url_count": len(urls),
            "media_source": "uploads" if local_assets else ("skipped" if urls else "none"),
        }

    post_dict = {
        "id": post["id"],
        "platform": post["platform"],
        "content_kind": post["content_kind"],
        "permalink": post["permalink"],
        "published_at": post["published_at"],
        "caption": post["caption"] or "",
        "media_urls": urls,
    }
    request_package = build_request_package(
        role=role if role in {"image", "carousel", "reel"} else "image",
        post=post_dict,
        media_prep=media_prep,
        all_formats=legend_formats,
        pillars=pillars,
        metrics=_post_metrics(conn, post_id),
    )

    # Cost estimate only — not an execute.
    image_n = len(media_prep.get("images_for_model") or [])
    est_input_tokens = 2500 + image_n * 800
    est_output_tokens = 900
    low = round(
        (est_input_tokens / 1_000_000) * OFFICIAL_RATES["input_per_1m"]
        + (est_output_tokens / 1_000_000) * OFFICIAL_RATES["output_per_1m"],
        4,
    )
    high = round(low * 1.6, 4)

    role_for_model = role if role in {"image", "carousel", "reel"} else "image"
    media_for_model = []
    for img in media_prep.get("images_for_model") or []:
        media_for_model.append(
            {
                "index": img.get("index"),
                "role": img.get("role"),
                "path": img.get("path"),
                "bytes": img.get("bytes"),
                "timestamp_s": img.get("timestamp_s"),
                "source": img.get("source"),
            }
        )

    snapshot = {
        "prepared_at": _now(),
        "inventory": inventory,
        "role": role_for_model,
        "media_prep": media_prep,
        "media_prep_summary": {
            "coverage": media_prep.get("coverage"),
            "images_for_model": image_n,
            "image_roles": [m.get("role") for m in media_for_model],
            "missing": media_prep.get("missing"),
            "limitations": media_prep.get("limitations"),
            "full_video_to_model": media_prep.get("full_video_to_model"),
            "audio_to_model": media_prep.get("audio_to_model"),
            "media_source": media_prep.get("media_source"),
        },
        "executable": {
            "system_text": request_package.get("system_text") or "",
            "user_text": request_package.get("user_text") or "",
            "images_for_model": media_for_model,
            "limitations": list(media_prep.get("limitations") or []),
            "prompt_version": PROMPT_VERSION,
            "role": role_for_model,
        },
        "request_package": {
            "prompt_version": PROMPT_VERSION,
            "system_chars": len(str((request_package or {}).get("system_text") or "")),
            "user_chars": len(str((request_package or {}).get("user_text") or "")),
            "image_parts": image_n,
        },
        "cost_estimate_usd": {
            "low": low,
            "high": high,
            "currency": "USD",
            "model": OFFICIAL_RATES["model"],
            "provider": OFFICIAL_RATES["provider"],
            "note": "Estimate only. Prepare does not call a paid API. Execute needs explicit confirm.",
        },
        "paid_call": False,
    }

    started = _now()
    cur = conn.execute(
        """
        INSERT INTO post_ai_analyses (
            client_id, post_id, provider, model, prompt_version, status,
            started_at, finished_at, insight_text, action_text, rating_text,
            raw_response_json, usage_json, input_snapshot_json, error_text,
            actual_cost_usd, cost_known
        ) VALUES (?, ?, ?, ?, ?, 'prepared', ?, NULL, '', '', '', '{}', ?, ?, '', NULL, 0)
        """,
        (
            client_id,
            post_id,
            OFFICIAL_RATES["provider"],
            OFFICIAL_RATES["model"],
            PROMPT_VERSION,
            started,
            json.dumps({"status": "prepared_not_executed", "estimate": snapshot["cost_estimate_usd"]}, ensure_ascii=False),
            json.dumps(snapshot, ensure_ascii=False),
        ),
    )
    analysis_id = int(cur.lastrowid)
    return {
        "analysis_id": analysis_id,
        "status": "prepared_not_executed",
        "paid_call": False,
        "inventory": inventory,
        "media_prep": snapshot["media_prep_summary"],
        "media_for_model": media_for_model,
        "cost_estimate_usd": snapshot["cost_estimate_usd"],
        "capability": _capability_report(public_ai_status()),
        "execute_requires_confirm": True,
        "note": (
            "Preparation stored. No paid model call. "
            "Review media + estimate, then Execute with confirm=true, or save a manual insight."
        ),
    }


def execute_prepared_post_analysis(
    conn,
    client_id: int,
    post_id: int,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one paid Gemini post analysis from a prepared snapshot.

    Requires body.confirm == true. Does not run on open/prepare/reload.
    """
    from pathlib import Path

    import requests

    from ai.config import chat_completions_url, is_configured, load_ai_config
    from maaike.ai_response_validate import validate_post_analysis
    from maaike.ai_trial_execute import (
        MAX_OUTPUT_TOKENS,
        PROJECT_ROOT,
        REQUEST_TIMEOUT_S,
        _RESPONSE_SCHEMA,
        _cost_usd,
        _extract_json,
        _image_part,
        _message_text,
        _normalize_result,
        _usage_from_body,
        _verify_media,
    )

    ensure_analysis_tables(conn)
    body = body or {}
    if not body.get("confirm"):
        raise ValueError(
            "Execute requires confirm=true after reviewing the cost estimate. No paid call started."
        )
    if not is_configured():
        raise ValueError("AI is niet geconfigureerd (AI_BASE_URL / AI_API_KEY / AI_MODEL).")

    analysis_id = body.get("analysis_id")
    row = None
    if analysis_id is not None:
        row = conn.execute(
            """
            SELECT * FROM post_ai_analyses
            WHERE id = ? AND client_id = ? AND post_id = ?
            """,
            (int(analysis_id), client_id, post_id),
        ).fetchone()
    if row is None:
        row = conn.execute(
            """
            SELECT * FROM post_ai_analyses
            WHERE client_id = ? AND post_id = ? AND status = 'prepared'
            ORDER BY id DESC LIMIT 1
            """,
            (client_id, post_id),
        ).fetchone()
    if row is None:
        raise ValueError("No prepared analysis found. Run Prepare first.")
    if row["status"] not in {"prepared", "failed"}:
        if row["status"] == "completed" and (row["insight_text"] or "").strip():
            raise ValueError(
                f"Analysis #{row['id']} is already completed. Open saved insight instead of re-running."
            )

    snapshot = json.loads(row["input_snapshot_json"] or "{}")
    executable = snapshot.get("executable") or {}
    system_text = str(executable.get("system_text") or "")
    user_text = str(executable.get("user_text") or "")
    role = str(executable.get("role") or snapshot.get("role") or "image")
    limitations = list(executable.get("limitations") or [])
    images = _verify_media(executable.get("images_for_model") or [])
    estimate = snapshot.get("cost_estimate_usd") or {}
    high = estimate.get("high")
    max_allowed = float(body.get("max_cost_usd") or 0.05)
    if isinstance(high, (int, float)) and high > max_allowed:
        raise ValueError(
            f"Estimate high USD {high} exceeds max_cost_usd USD {max_allowed}. No paid call started."
        )
    if not system_text or not user_text:
        raise ValueError("Prepared prompt is incomplete. Prepare again. No paid call started.")
    if not images:
        raise ValueError(
            "No local image/frame files ready for the model. Prepare again with reachable media. "
            "No paid call started."
        )

    config = load_ai_config()
    started = _now()
    conn.execute(
        "UPDATE post_ai_analyses SET status = 'running', started_at = ?, error_text = '' WHERE id = ?",
        (started, row["id"]),
    )

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                user_text
                + "\n\nBeoordeel alleen wat je in de meegestuurde beelden en caption ziet. "
                "Claim geen audio, gesproken hook of niet-meegestuurde slides/video. "
                "Scheid zichtbare details, meetbare cijfers en hypotheses. "
                "Lage interactiecijfers bewijzen niet dat het format de oorzaak was."
            ),
        }
    ]
    for img in images:
        label = img.get("role") or "image"
        ts = img.get("timestamp_s")
        ts_bit = f" @ {ts}s" if ts is not None else ""
        user_content.append({"type": "text", "text": f"MEDIA {label}{ts_bit}:"})
        user_content.append(_image_part(Path(img["abs_path"])))

    request_body = {
        "model": config.model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "maaike_postanalyse",
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
    error = None
    parsed: dict[str, Any] | None = None
    http_status = None
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
        try:
            body_json = response.json()
        except ValueError:
            body_json = {}
        usage = _usage_from_body(body_json) if isinstance(body_json, dict) else usage
        if response.ok:
            raw_text = _message_text((body_json.get("choices") or [{}])[0].get("message", {}).get("content"))
            extracted = _extract_json(raw_text)
            if extracted:
                candidate = _normalize_result(extracted, role=role, limitations=limitations)
                validation = validate_post_analysis(
                    candidate,
                    raw_text=raw_text,
                    role=role,
                    limitations=limitations,
                )
                if validation.usable and validation.normalized:
                    parsed = validation.normalized
                else:
                    error = validation.user_message or "AI response not usable."
            else:
                error = "Invalid or empty JSON from model."
        else:
            error = f"HTTP {response.status_code} from AI provider (no retry)."
    except requests.RequestException as exc:
        error = f"Network error without retry: {exc.__class__.__name__}"

    finished = _now()
    actual_cost, cost_known = _cost_usd(usage.get("prompt_tokens"), usage.get("completion_tokens"))
    insight = (parsed or {}).get("ai_insight") or ""
    action = (parsed or {}).get("ai_action") or ""
    rating = (parsed or {}).get("proposed_format_code") or ""
    status = "completed" if parsed else "failed"
    usage_out = {
        **usage,
        "status": status,
        "http_status": http_status,
        "actual_cost_usd": actual_cost if cost_known else None,
        "cost_known": cost_known,
        "images_sent": len(images),
        "image_roles": [i.get("role") for i in images],
        "model": config.model,
        "notes": "Single-post execute from Social posts Media & insight.",
    }
    conn.execute(
        """
        UPDATE post_ai_analyses SET
            status = ?,
            finished_at = ?,
            insight_text = ?,
            action_text = ?,
            rating_text = ?,
            raw_response_json = ?,
            usage_json = ?,
            error_text = ?,
            actual_cost_usd = ?,
            cost_known = ?,
            provider = ?,
            model = ?
        WHERE id = ?
        """,
        (
            status,
            finished,
            insight,
            action,
            rating,
            json.dumps({"text": (raw_text or "")[:20000], "parsed": parsed}, ensure_ascii=False),
            json.dumps(usage_out, ensure_ascii=False),
            error or "",
            actual_cost if cost_known else None,
            1 if cost_known else 0,
            OFFICIAL_RATES["provider"],
            config.model,
            row["id"],
        ),
    )
    if status == "completed":
        conn.execute(
            """
            INSERT INTO post_assessments (
                post_id, source, source_label, rating_text, insight_text, action_text, imported_at
            ) VALUES (?, 'post_analysis_execute', ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                f"{OFFICIAL_RATES['provider']} {config.model}",
                rating or None,
                insight,
                action,
                finished,
            ),
        )
    result = get_analysis(conn, client_id, int(row["id"]))
    result["paid_call"] = True
    result["cost_estimate_usd"] = estimate
    result["media_sent"] = [
        {"role": i.get("role"), "path": i.get("path"), "timestamp_s": i.get("timestamp_s")}
        for i in images
    ]
    result["error"] = error
    return result


def save_reviewed_insight(
    conn,
    client_id: int,
    post_id: int,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save Maaike's reviewed insight/action so client reports can attach it."""
    ensure_analysis_tables(conn)
    owned = conn.execute(
        "SELECT id FROM posts WHERE id = ? AND client_id = ?",
        (post_id, client_id),
    ).fetchone()
    if owned is None:
        raise ValueError("Post not found for this client.")

    body = body or {}
    insight = str(body.get("insight_text") or body.get("insight") or "").strip()
    action = str(body.get("action_text") or body.get("action") or "").strip()
    rating = str(body.get("rating_text") or body.get("rating") or "").strip()
    if not insight and not action:
        raise ValueError("Enter at least an insight or an action before saving.")

    source_analysis_id = body.get("source_analysis_id")
    provider = str(body.get("provider") or "Specialist reviewed").strip() or "Specialist reviewed"
    model = str(body.get("model") or "manual").strip() or "manual"
    finished = _now()

    # Prefer updating a prepared row when provided; otherwise insert completed.
    updated_id = None
    if source_analysis_id is not None:
        row = conn.execute(
            """
            SELECT id, status FROM post_ai_analyses
            WHERE id = ? AND client_id = ? AND post_id = ?
            """,
            (int(source_analysis_id), client_id, post_id),
        ).fetchone()
        if row is not None:
            conn.execute(
                """
                UPDATE post_ai_analyses SET
                    status = 'completed',
                    finished_at = ?,
                    insight_text = ?,
                    action_text = ?,
                    rating_text = ?,
                    provider = ?,
                    model = ?,
                    error_text = ''
                WHERE id = ?
                """,
                (finished, insight, action, rating, provider, model, int(row["id"])),
            )
            updated_id = int(row["id"])

    if updated_id is None:
        cur = conn.execute(
            """
            INSERT INTO post_ai_analyses (
                client_id, post_id, provider, model, prompt_version, status,
                started_at, finished_at, insight_text, action_text, rating_text,
                raw_response_json, usage_json, input_snapshot_json, error_text,
                actual_cost_usd, cost_known
            ) VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, '{}', ?, '{}', '', NULL, 0)
            """,
            (
                client_id,
                post_id,
                provider,
                model,
                PROMPT_VERSION,
                finished,
                finished,
                insight,
                action,
                rating,
                json.dumps(
                    {
                        "status": "completed",
                        "notes": "Specialist-reviewed insight saved from Social posts.",
                        "cost_known": False,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        updated_id = int(cur.lastrowid)

    conn.execute(
        """
        INSERT INTO post_assessments (
            post_id, source, source_label, rating_text, insight_text, action_text, imported_at
        ) VALUES (?, 'specialist_reviewed', ?, ?, ?, ?, ?)
        """,
        (
            post_id,
            f"{provider} ({model})",
            rating or None,
            insight,
            action,
            finished,
        ),
    )
    return get_analysis(conn, client_id, updated_id)


def analysis_panel(conn, client_id: int, post_id: int) -> dict[str, Any]:
    """Combined panel payload for Social posts → post details."""
    ensure_analysis_tables(conn)
    inventory = inventory_for_post(conn, client_id, post_id)

    analyses = [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, post_id, provider, model, prompt_version, status,
                   started_at, finished_at, insight_text, action_text, rating_text,
                   cost_known, actual_cost_usd, error_text
            FROM post_ai_analyses
            WHERE client_id = ? AND post_id = ?
            ORDER BY id DESC
            LIMIT 8
            """,
            (client_id, post_id),
        ).fetchall()
    ]
    for row in analyses:
        row["cost_known"] = bool(row.get("cost_known"))

    trial = conn.execute(
        """
        SELECT t.post_id, t.status, t.ai_insight, t.ai_action, t.ai_format_code,
               t.joint_verdict, r.executed_at, r.model, r.prompt_version
        FROM ai_trial_posts t
        JOIN ai_trial_runs r ON r.id = t.trial_run_id
        WHERE t.post_id = ? AND r.client_id = ?
        ORDER BY t.id DESC LIMIT 1
        """,
        (post_id, client_id),
    ).fetchone()

    excel = conn.execute(
        """
        SELECT source, source_label, rating_text, insight_text, action_text, imported_at
        FROM post_assessments WHERE post_id = ?
        ORDER BY id DESC LIMIT 3
        """,
        (post_id,),
    ).fetchone()
    # Prefer latest specialist/excel rows list
    assessments = [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, source, source_label, rating_text, insight_text, action_text, imported_at
            FROM post_assessments WHERE post_id = ?
            ORDER BY id DESC LIMIT 5
            """,
            (post_id,),
        ).fetchall()
    ]

    latest_completed = next((a for a in analyses if a.get("status") == "completed"), None)
    draft_insight = ""
    draft_action = ""
    draft_rating = ""
    if latest_completed:
        draft_insight = latest_completed.get("insight_text") or ""
        draft_action = latest_completed.get("action_text") or ""
        draft_rating = latest_completed.get("rating_text") or ""
    elif trial:
        draft_insight = trial["ai_insight"] or ""
        draft_action = trial["ai_action"] or ""

    return {
        "inventory": inventory,
        "analyses": analyses,
        "assessments": assessments,
        "ai_trial": dict(trial) if trial else None,
        "excel_or_prior": dict(excel) if excel else None,
        "draft": {
            "insight_text": draft_insight,
            "action_text": draft_action,
            "rating_text": draft_rating,
            "source_analysis_id": latest_completed["id"] if latest_completed else None,
        },
        "report_note": (
            "Completed analyses on this post are attached when you prepare a client report "
            "for a period that includes this post."
        ),
        "paid_call_on_open": False,
        "ai_trial_is_internal": True,
        "ai_trial_location": "Settings → AI Connections → AI Trial",
    }
