"""Prepare a small Red Rock AI post-analysis trial without calling a paid API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from maaike.ai_status import public_ai_status
from maaike.ai_trial_media import prepare_post_media
from maaike.ai_trial_request import PROMPT_VERSION, build_request_package

TRIAL_KEY = "redrock-postanalyse-v1"

# Official Gemini Developer API pricing (ai.google.dev/gemini-api/docs/pricing), verified 2026-10-30.
# This is the model configured in .env (AI_MODEL). Not Claude — do not relabel as Claude.
OFFICIAL_RATES = {
    "provider": "Google Gemini Developer API",
    "model": "gemini-3.5-flash-lite",
    "currency": "USD",
    "input_per_1m": 0.30,
    "output_per_1m": 2.50,
    "rate_date": "2026-10-30",
    "source_url": "https://ai.google.dev/gemini-api/docs/pricing",
    "model_docs_url": "https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite",
    "verified_inputs": ["text", "image", "video", "audio", "pdf"],
    "notes": (
        "Paid tier Standard op de Gemini Developer API. "
        "Input $0.30 / 1M tokens (text/image/video/audio); output $2.50 / 1M (incl. thinking). "
        "Model ondersteunt video/audio volgens Google-docs; deze app stuurt in de proef "
        "afbeeldingen + eventuele lokale reel-frames, geen ruwe videobytes en geen audio. "
        "Geen stilzwijgende switch naar Claude."
    ),
}

# Fixed Red Rock trial selection: image / carousel / reel with media + Excel assessment for later compare only.
DEFAULT_TRIAL_POSTS = (
    {
        "post_id": 31,
        "role": "image",
        "reason": (
            "Instagram-afbeelding met bereikbare media-URL en caption; Excel-format was nvt. "
            "Geen dedicated image-format in legenda — AI mag C-codes niet automatisch toewijzen."
        ),
    },
    {
        "post_id": 16,
        "role": "carousel",
        "reason": "Carrousel met C05-definitie, meerdere slides (waarvan beeld bereikbaar) en Excel-beoordeling voor latere vergelijking.",
    },
    {
        "post_id": 8,
        "role": "reel",
        "reason": "Reel R07 met video-URL + thumbnail; frames verspreid over de hele clip (dicht in 0–3s). Geen audio/transcript; geen claim van volledige videoanalyse.",
    },
)

SOCIAL_AGENT_DIR = Path(__file__).resolve().parents[1] / "data" / "imports" / "redrock" / "social_agent"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def ensure_ai_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ai_prompt_catalog (
            id INTEGER PRIMARY KEY,
            purpose TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_label TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            body_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'catalogued',
            notes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(purpose, source_path, prompt_version)
        );

        CREATE TABLE IF NOT EXISTS ai_cost_rates (
            id INTEGER PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            currency TEXT NOT NULL,
            input_per_1m REAL,
            output_per_1m REAL,
            rate_date TEXT NOT NULL,
            source_url TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            UNIQUE(provider, model, rate_date)
        );

        CREATE TABLE IF NOT EXISTS ai_trial_runs (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            trial_key TEXT NOT NULL,
            status TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            prepared_at TEXT NOT NULL,
            executed_at TEXT,
            capability_json TEXT NOT NULL DEFAULT '{}',
            estimate_json TEXT NOT NULL DEFAULT '{}',
            notes_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(client_id, trial_key),
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );

        CREATE TABLE IF NOT EXISTS ai_trial_posts (
            id INTEGER PRIMARY KEY,
            trial_run_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            selection_reason TEXT NOT NULL DEFAULT '',
            request_payload_json TEXT NOT NULL DEFAULT '{}',
            media_access_json TEXT NOT NULL DEFAULT '{}',
            ai_observations_json TEXT NOT NULL DEFAULT '[]',
            ai_format_code TEXT NOT NULL DEFAULT '',
            ai_format_rationale TEXT NOT NULL DEFAULT '',
            ai_format_uncertainty TEXT NOT NULL DEFAULT '',
            ai_pillar TEXT NOT NULL DEFAULT '',
            ai_hook TEXT NOT NULL DEFAULT '',
            ai_insight TEXT NOT NULL DEFAULT '',
            ai_action TEXT NOT NULL DEFAULT '',
            human_feedback TEXT NOT NULL DEFAULT '',
            joint_verdict TEXT NOT NULL DEFAULT '',
            excel_assessment_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'prepared',
            UNIQUE(trial_run_id, post_id),
            FOREIGN KEY(trial_run_id) REFERENCES ai_trial_runs(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        );

        CREATE TABLE IF NOT EXISTS ai_usage_events (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            post_id INTEGER,
            trial_run_id INTEGER,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            extra_tool_cost REAL,
            extra_media_cost REAL,
            currency TEXT,
            estimated_cost REAL,
            actual_cost REAL,
            cost_known INTEGER NOT NULL DEFAULT 0,
            rate_date TEXT,
            notes TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(post_id) REFERENCES posts(id),
            FOREIGN KEY(trial_run_id) REFERENCES ai_trial_runs(id)
        );
        """
    )


def sync_prompt_catalog(conn) -> list[dict[str, Any]]:
    """Register real Social Agent files found on disk. Never invent prompt bodies."""
    ensure_ai_tables(conn)
    catalog = [
        {
            "purpose": "postanalyse",
            "filename": "Performance-analyse richtlijnen.docx",
            "label": "Workflows / Performance-analyse richtlijnen.docx",
            "notes": "Richtlijnen voor performance-/postanalyse inclusief formatcodes, insight, actie en beoordeling.",
        },
        {
            "purpose": "trends",
            "filename": "Trendrapport - opbouw en aanpak.docx",
            "label": "Workflows / Trendrapport - opbouw en aanpak.docx",
            "notes": "Opbouw trendrapport. Nog niet uitgevoerd.",
        },
        {
            "purpose": "klantrapport",
            "filename": "Klantrapport - opbouw en aanpak.docx",
            "label": "Workflows / Klantrapport - opbouw en aanpak.docx",
            "notes": "Opbouw klantrapport. Nog niet uitgevoerd.",
        },
        {
            "purpose": "algemene_instructies",
            "filename": "Role - Algemene instructies.docx",
            "label": "Bestanden agent / Role - Algemene instructies.docx",
            "notes": "Algemene rol-instructies van de social agent.",
        },
        {
            "purpose": "kwaliteit",
            "filename": "Kwaliteitsstandaard.docx",
            "label": "Workflows / Kwaliteitsstandaard.docx",
            "notes": "Kwaliteitsstandaard voor agentoutput.",
        },
        {
            "purpose": "actieplan",
            "filename": "Actieplan - werkwijze.docx",
            "label": "Workflows / Actieplan - werkwijze.docx",
            "notes": "Werkwijze actieplan.",
        },
        {
            "purpose": "rapportopbouw",
            "filename": "Rapportopbouw - werkwijze.docx",
            "label": "Workflows / Rapportopbouw - werkwijze.docx",
            "notes": "Algemene rapportopbouw.",
        },
        {
            "purpose": "formatdefinities",
            "filename": "",
            "label": "Excel Formats-tabblad + content_formats in DB",
            "notes": "Formatcodes C01–C13, R01–R14, LZC01/LZR01/LZR02 met omschrijvingen. Geen apart cluster-promptbestand gevonden in Bestanden agent.",
            "body": "",
            "path": "data/imports/redrock/RRO_Social_strategie_overzicht_2026.xlsx#Formats",
        },
    ]
    now = _now()
    out: list[dict[str, Any]] = []
    for item in catalog:
        if item["purpose"] == "formatdefinities":
            path = item["path"]
            body = item.get("body") or ""
            status = "catalogued"
        else:
            file_path = SOCIAL_AGENT_DIR / item["filename"]
            txt_path = file_path.with_suffix(".txt")
            path = str(file_path.relative_to(Path(__file__).resolve().parents[1])) if file_path.exists() else item["label"]
            if txt_path.exists():
                body = txt_path.read_text(encoding="utf-8")
                status = "loaded"
            elif file_path.exists():
                body = ""
                status = "downloaded_not_extracted"
            else:
                body = ""
                status = "missing_on_disk"
                path = f"SharePoint: Bestanden agent / {item['label']}"
        # One canonical row per purpose+version (avoid duplicate missing/loaded paths).
        conn.execute(
            "DELETE FROM ai_prompt_catalog WHERE purpose = ? AND prompt_version = ?",
            (item["purpose"], PROMPT_VERSION),
        )
        conn.execute(
            """
            INSERT INTO ai_prompt_catalog (
                purpose, source_path, source_label, prompt_version, body_text, status, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["purpose"],
                path,
                item["label"],
                PROMPT_VERSION,
                body,
                status,
                item["notes"],
                now,
            ),
        )
        out.append(
            {
                "purpose": item["purpose"],
                "source_path": path,
                "source_label": item["label"],
                "status": status,
                "chars": len(body),
                "notes": item["notes"],
            }
        )
    # Explicit note: no dedicated cluster prompt found
    conn.execute(
        "DELETE FROM ai_prompt_catalog WHERE purpose = ? AND prompt_version = ?",
        ("clusters", PROMPT_VERSION),
    )
    conn.execute(
        """
        INSERT INTO ai_prompt_catalog (
            purpose, source_path, source_label, prompt_version, body_text, status, notes, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "clusters",
            "SharePoint: Bestanden agent (Workflows + Role)",
            "Geen apart cluster-promptbestand gevonden",
            PROMPT_VERSION,
            "",
            "not_found",
            "In Bestanden agent / Workflows staan Trendrapport, Klantrapport, Performance-analyse, Actieplan, Rapportopbouw en Kwaliteitsstandaard. Geen bestand met ‘cluster’ in de naam aangetroffen.",
            now,
        ),
    )
    out.append(
        {
            "purpose": "clusters",
            "source_path": "SharePoint: Bestanden agent (Workflows + Role)",
            "source_label": "Geen apart cluster-promptbestand gevonden",
            "status": "not_found",
            "chars": 0,
            "notes": "Geen cluster-promptbestand met die naam in de bekeken map.",
        }
    )
    return out


def upsert_official_rates(conn) -> dict[str, Any]:
    ensure_ai_tables(conn)
    conn.execute(
        """
        INSERT INTO ai_cost_rates (
            provider, model, currency, input_per_1m, output_per_1m, rate_date, source_url, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, model, rate_date) DO UPDATE SET
            currency = excluded.currency,
            input_per_1m = excluded.input_per_1m,
            output_per_1m = excluded.output_per_1m,
            source_url = excluded.source_url,
            notes = excluded.notes
        """,
        (
            OFFICIAL_RATES["provider"],
            OFFICIAL_RATES["model"],
            OFFICIAL_RATES["currency"],
            OFFICIAL_RATES["input_per_1m"],
            OFFICIAL_RATES["output_per_1m"],
            OFFICIAL_RATES["rate_date"],
            OFFICIAL_RATES["source_url"],
            OFFICIAL_RATES["notes"],
        ),
    )
    return dict(OFFICIAL_RATES)


def _media_urls(raw: str | None) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [text] if text.startswith("http") else []
        urls: list[str] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
                elif isinstance(item, dict):
                    for key in ("url", "media_url", "source_url"):
                        value = item.get(key)
                        if isinstance(value, str) and value.startswith("http"):
                            urls.append(value)
                            break
        return urls
    if text.startswith("http"):
        # Meta sometimes stores multiple URLs separated by whitespace/newlines/commas
        parts = [p.strip() for p in text.replace("\n", " ").replace(",", " ").split() if p.strip().startswith("http")]
        return parts or [text]
    return []


def _media_access(content_kind: str | None, media_urls: list[str]) -> dict[str, Any]:
    kind = (content_kind or "").lower()
    image_like = [u for u in media_urls if any(x in u.lower() for x in (".jpg", ".jpeg", ".png", ".webp", "stp=dst-jpg", "t51."))]
    video_like = [u for u in media_urls if any(x in u.lower() for x in (".mp4", "/v/t2/", "video", "reel"))]
    # Heuristic: Instagram CDN image vs video paths
    if not image_like and not video_like:
        for u in media_urls:
            if "scontent" in u and ".mp4" not in u:
                image_like.append(u)
            elif ".mp4" in u:
                video_like.append(u)

    can_send_images = bool(image_like)
    can_send_all_carousel = "carousel" in kind or "carrousel" in kind
    carousel_count = len(media_urls) if can_send_all_carousel else 0
    is_reel = "reel" in kind or kind == "video"

    limitations: list[str] = []
    first_3s = "niet beoordeelbaar in huidige stack"
    audio = "niet beoordeelbaar in huidige stack"
    video_full = False

    if is_reel:
        if video_like:
            limitations.append(
                "Er is een video-URL beschikbaar, maar de huidige content_describe-stack stuurt géén videobytes naar het model."
            )
            limitations.append("Een eventuele thumbnail/omslagfoto is geen volledige reelanalyse.")
            first_3s = "open — videoframes en audio worden niet meegestuurd"
            audio = "open — gesproken hook/audio wordt niet meegestuurd"
        else:
            limitations.append("Geen bruikbare video-URL; alleen eventuele omslagfoto of niets.")
            first_3s = "open"
            audio = "open"
    elif can_send_all_carousel:
        if media_urls:
            limitations.append(
                f"{len(media_urls)} media-URL(s) gevonden; slides die als afbeelding bereikbaar zijn kunnen mee, "
                "video-slides binnen een carrousel niet als video."
            )
        else:
            limitations.append("Geen media-URL’s voor carrouselslides.")
            can_send_images = False
    else:
        if not can_send_images:
            limitations.append("Geen afbeeldings-URL beschikbaar voor analyse.")

    return {
        "content_kind": content_kind,
        "media_url_count": len(media_urls),
        "image_urls_detected": len(image_like),
        "video_urls_detected": len(video_like),
        "can_send_images": can_send_images,
        "can_send_all_carousel_images": can_send_all_carousel and len(media_urls) > 0,
        "carousel_slide_urls": carousel_count,
        "can_analyze_full_video": video_full,
        "first_3_seconds": first_3s,
        "audio_spoken_hook": audio,
        "limitations": limitations,
        "sample_hosts": sorted({urlparse(u).netloc for u in media_urls if u}),
    }


def _capability_report(ai: dict[str, Any]) -> dict[str, Any]:
    host = ai.get("base_host") or ""
    model = (ai.get("model") or "").strip()
    is_gemini_host = "generativelanguage.googleapis.com" in host
    provider = "Google Gemini Developer API" if is_gemini_host else (host or "onbekend")
    if model and "claude" in model.lower():
        label_warning = "Model-ID bevat 'claude' — niet als Gemini presenteren."
    elif is_gemini_host:
        label_warning = "Resultaten van dit model als Gemini labelen, niet als Claude."
    else:
        label_warning = "Controleer of de geconfigureerde aanbieder overeenkomt met het model-ID."
    return {
        "configured": bool(ai.get("configured")),
        "provider": provider,
        "model": model,
        "exact_model_id": model,
        "base_host": host,
        "is_gemini": is_gemini_host and model.startswith("gemini"),
        "is_claude": "claude" in model.lower() or "anthropic" in host.lower(),
        "label_warning": label_warning,
        "official_model_docs": OFFICIAL_RATES["model_docs_url"],
        "official_pricing": OFFICIAL_RATES["source_url"],
        "model_supports_per_docs": OFFICIAL_RATES["verified_inputs"],
        "app_sends_images": True,
        "app_sends_carousel_images": True,
        "app_sends_full_video_bytes": False,
        "app_sends_local_reel_frames": True,
        "app_sends_full_duration_frames": True,
        "app_sends_audio": False,
        "supports_images": True if ai.get("configured") else False,
        "supports_carousel_images": True if ai.get("configured") else False,
        "supports_video_bytes": False,
        "supports_audio": False,
        "native_gemini_supports_video_audio": True,
        "openai_compat_route": is_gemini_host,
        "notes": [
            f"Geconfigureerd model-ID: {model or '(leeg)'} via {host or '(geen host)'}.",
            "Officiële Gemini 3.5 Flash-Lite docs: text/image/video/audio/PDF-invoer mogelijk (native API).",
            "Deze app gebruikt de OpenAI-compatibele chat/completions-route: caption + afbeeldingen/slides + "
            "timestamped frames over de hele video (dicht in 0–3s); geen ruwe videobytes, geen audio in deze stack.",
            "Beweging tussen frames is niet volledig bekeken; gesproken hook blijft onbekend zonder audio/transcript.",
            "Geen stilzwijgende aanbiederwissel; Gemini-output niet als Claude tonen.",
            "Pagina openen/herladen start geen betaalde AI-aanvraag.",
        ],
    }


def _estimate_cost(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """Rough estimate only; tokens unknown until a real call returns usage."""
    per_post = []
    total_low = 0.0
    total_high = 0.0
    for item in posts:
        media = item.get("media_prep") or {}
        n_img = len(media.get("images_for_model") or [])
        # Prompt texts are large (instructions); images add roughly 300–800 tokens-equivalent band each for estimate.
        base_in = 3500
        if item["role"] == "carousel":
            in_low, in_high = base_in + n_img * 400, base_in + n_img * 900 + 2000
        elif item["role"] == "reel":
            in_low, in_high = base_in + n_img * 350, base_in + n_img * 800 + 1500
        else:
            in_low, in_high = base_in + n_img * 400, base_in + n_img * 800 + 1000
        out_low, out_high = 700, 1800
        cost_low = (in_low / 1_000_000) * OFFICIAL_RATES["input_per_1m"] + (out_low / 1_000_000) * OFFICIAL_RATES["output_per_1m"]
        cost_high = (in_high / 1_000_000) * OFFICIAL_RATES["input_per_1m"] + (out_high / 1_000_000) * OFFICIAL_RATES["output_per_1m"]
        total_low += cost_low
        total_high += cost_high
        per_post.append(
            {
                "post_id": item["post_id"],
                "role": item["role"],
                "images_planned": n_img,
                "assumed_input_tokens": {"low": in_low, "high": in_high, "known": False},
                "assumed_output_tokens": {"low": out_low, "high": out_high, "known": False},
                "estimated_cost_usd": {"low": round(cost_low, 5), "high": round(cost_high, 5)},
                "actual_tokens": None,
                "actual_cost_usd": None,
                "limitations": media.get("limitations") or [],
            }
        )
    return {
        "currency": "USD",
        "rate": OFFICIAL_RATES,
        "status": "estimate_only_not_executed",
        "token_usage_known": False,
        "actual_cost_known": False,
        "display_rule": "Onbekend verbruik of onbekende kosten worden niet als 0 getoond.",
        "trial_estimated_usd": {"low": round(total_low, 5), "high": round(total_high, 5)},
        "per_post": per_post,
        "extra_tool_cost": None,
        "extra_media_cost": None,
        "failed_calls_may_still_cost": True,
    }


def _excel_assessment(conn, post_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT source, source_label, rating_text, insight_text, action_text, source_file, source_sheet, source_row
        FROM post_assessments
        WHERE post_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (post_id,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "source": row["source"],
        "source_label": row["source_label"],
        "rating_text": row["rating_text"],
        "insight_text": row["insight_text"],
        "action_text": row["action_text"],
        "source_file": row["source_file"],
        "source_sheet": row["source_sheet"],
        "source_row": row["source_row"],
        "note": "Apart bewaard voor latere vergelijking; niet opgenomen in de AI-request payload.",
    }


def _post_metrics(conn, post_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT views, likes, comments, shares, saves, clicks, reach
        FROM posts WHERE id = ?
        """,
        (post_id,),
    ).fetchone()
    if row is None:
        return {}
    return {k: row[k] for k in row.keys()}


def prepare_redrock_trial(conn, client_id: int, *, download_media: bool = True) -> dict[str, Any]:
    ensure_ai_tables(conn)
    # Prevent overlapping prepare while a mock/real run is marked running.
    existing = conn.execute(
        "SELECT status FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    if existing and existing["status"] == "running":
        raise ValueError("Er loopt al een uitvoering voor deze klant. Wacht of herlaad het opgeslagen resultaat.")

    catalog = sync_prompt_catalog(conn)
    upsert_official_rates(conn)
    ai = public_ai_status()
    capability = _capability_report(ai)

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

    prepared_posts: list[dict[str, Any]] = []
    for spec in DEFAULT_TRIAL_POSTS:
        post = conn.execute(
            """
            SELECT id, client_id, platform, content_kind, media_urls, permalink, caption, published_at
            FROM posts WHERE id = ? AND client_id = ?
            """,
            (spec["post_id"], client_id),
        ).fetchone()
        if post is None:
            raise ValueError(f"Proefpost {spec['post_id']} hoort niet bij deze klant of ontbreekt.")
        urls = _media_urls(post["media_urls"])
        if not urls:
            raise ValueError(f"Proefpost {spec['post_id']} heeft geen media-URL’s; kies een andere post.")
        local_assets = None
        try:
            from maaike.post_media_upload import local_paths_for_analysis

            local_assets = local_paths_for_analysis(conn, client_id, post["id"]) or None
        except Exception:
            local_assets = None
        if download_media:
            media_prep = prepare_post_media(
                client_id=client_id,
                post_id=post["id"],
                role=spec["role"],
                content_kind=post["content_kind"],
                media_urls=urls,
                local_assets=local_assets,
            )
        else:
            media_prep = {
                "coverage": "skipped_download",
                "images_for_model": [],
                "missing": ["download overgeslagen"],
                "limitations": ["Media niet lokaal opgehaald in deze testmodus."],
                "full_video_to_model": False,
                "audio_to_model": False,
                "media_url_count": len(urls),
                "media_source": "uploads" if local_assets else "skipped",
            }
        access = _media_access(post["content_kind"], urls)
        access["prepared"] = {
            "coverage": media_prep.get("coverage"),
            "images_for_model": len(media_prep.get("images_for_model") or []),
            "missing": media_prep.get("missing"),
            "limitations": media_prep.get("limitations"),
            "full_video_to_model": media_prep.get("full_video_to_model"),
            "audio_to_model": media_prep.get("audio_to_model"),
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
        payload = build_request_package(
            role=spec["role"],
            post=post_dict,
            media_prep=media_prep,
            all_formats=legend_formats,
            pillars=pillars,
            metrics=_post_metrics(conn, post["id"]),
        )
        excel = _excel_assessment(conn, post["id"])
        prepared_posts.append(
            {
                "post_id": post["id"],
                "role": spec["role"],
                "selection_reason": spec["reason"],
                "permalink": post["permalink"],
                "content_kind": post["content_kind"],
                "request_payload": payload,
                "media_access": access,
                "media_prep": media_prep,
                "excel_assessment": excel,
            }
        )

    estimate = _estimate_cost(prepared_posts)
    now = _now()
    conn.execute(
        """
        INSERT INTO ai_trial_runs (
            client_id, trial_key, status, provider, model, prompt_version,
            prepared_at, executed_at, capability_json, estimate_json, notes_json
        ) VALUES (?, ?, 'prepared_not_executed', ?, ?, ?, ?, NULL, ?, ?, ?)
        ON CONFLICT(client_id, trial_key) DO UPDATE SET
            status = 'prepared_not_executed',
            provider = excluded.provider,
            model = excluded.model,
            prompt_version = excluded.prompt_version,
            prepared_at = excluded.prepared_at,
            executed_at = NULL,
            capability_json = excluded.capability_json,
            estimate_json = excluded.estimate_json,
            notes_json = excluded.notes_json
        """,
        (
            client_id,
            TRIAL_KEY,
            capability["provider"],
            capability["model"],
            PROMPT_VERSION,
            now,
            json.dumps(capability, ensure_ascii=False),
            json.dumps(estimate, ensure_ascii=False),
            json.dumps(
                [
                    "Geen betaalde AI-aanvraag uitgevoerd.",
                    "Excel-beoordelingen blijven apart voor menselijke vergelijking.",
                    "Zonder menselijke feedback ontstaat geen gezamenlijk oordeel.",
                    "Dubbele uitvoering wordt geblokkeerd terwijl status=running.",
                ],
                ensure_ascii=False,
            ),
        ),
    )
    run = conn.execute(
        "SELECT id FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    run_id = int(run["id"])
    conn.execute("DELETE FROM ai_trial_posts WHERE trial_run_id = ?", (run_id,))
    conn.execute("DELETE FROM ai_usage_events WHERE trial_run_id = ?", (run_id,))
    for item in prepared_posts:
        conn.execute(
            """
            INSERT INTO ai_trial_posts (
                trial_run_id, post_id, role, selection_reason, request_payload_json,
                media_access_json, excel_assessment_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared')
            """,
            (
                run_id,
                item["post_id"],
                item["role"],
                item["selection_reason"],
                json.dumps(
                    {**item["request_payload"], "media_prep": item["media_prep"]},
                    ensure_ascii=False,
                ),
                json.dumps(item["media_access"], ensure_ascii=False),
                json.dumps(item["excel_assessment"], ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_usage_events (
                client_id, post_id, trial_run_id, provider, model, prompt_version,
                started_at, finished_at, status,
                prompt_tokens, completion_tokens, total_tokens,
                extra_tool_cost, extra_media_cost, currency,
                estimated_cost, actual_cost, cost_known, rate_date, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'prepared_not_executed',
                      NULL, NULL, NULL, NULL, NULL, ?, NULL, NULL, 0, ?, ?)
            """,
            (
                client_id,
                item["post_id"],
                run_id,
                capability["provider"],
                capability["model"] or OFFICIAL_RATES["model"],
                PROMPT_VERSION,
                now,
                OFFICIAL_RATES["currency"],
                OFFICIAL_RATES["rate_date"],
                "Voorbereid; geen aanvraag. Tokenverbruik en werkelijke kosten onbekend (niet als 0 opgeslagen).",
            ),
        )

    return get_trial(conn, client_id)


def get_trial(conn, client_id: int) -> dict[str, Any]:
    ensure_ai_tables(conn)
    run = conn.execute(
        "SELECT * FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    catalog = [
        dict(r)
        for r in conn.execute(
            """
            SELECT purpose, source_path, source_label, prompt_version, status,
                   length(body_text) AS chars, notes, updated_at
            FROM ai_prompt_catalog
            WHERE prompt_version = ?
            ORDER BY purpose
            """,
            (PROMPT_VERSION,),
        ).fetchall()
    ]
    # Drop superseded prep-v1 catalog rows so the UI stays unambiguous.
    conn.execute(
        "DELETE FROM ai_prompt_catalog WHERE prompt_version != ?",
        (PROMPT_VERSION,),
    )
    rates = conn.execute(
        "SELECT * FROM ai_cost_rates ORDER BY rate_date DESC LIMIT 5"
    ).fetchall()
    if run is None:
        return {
            "trial": None,
            "prompt_catalog": catalog,
            "cost_rates": [dict(r) for r in rates],
            "ai_status": public_ai_status(),
        }
    posts = []
    for row in conn.execute(
        """
        SELECT t.*, p.permalink, p.content_kind, p.caption
        FROM ai_trial_posts t
        JOIN posts p ON p.id = t.post_id
        WHERE t.trial_run_id = ?
        ORDER BY CASE t.role WHEN 'image' THEN 1 WHEN 'carousel' THEN 2 ELSE 3 END, t.id
        """,
        (run["id"],),
    ).fetchall():
        posts.append(
            {
                "id": row["id"],
                "post_id": row["post_id"],
                "role": row["role"],
                "selection_reason": row["selection_reason"],
                "permalink": row["permalink"],
                "content_kind": row["content_kind"],
                "caption_preview": (row["caption"] or "")[:160],
                "request_payload": json.loads(row["request_payload_json"] or "{}"),
                "media_access": json.loads(row["media_access_json"] or "{}"),
                "excel_assessment": json.loads(row["excel_assessment_json"] or "{}"),
                "ai_observations": json.loads(row["ai_observations_json"] or "[]"),
                "ai_format_code": row["ai_format_code"],
                "ai_format_rationale": row["ai_format_rationale"],
                "ai_format_uncertainty": row["ai_format_uncertainty"],
                "ai_pillar": row["ai_pillar"],
                "ai_hook": row["ai_hook"],
                "ai_insight": row["ai_insight"],
                "ai_action": row["ai_action"],
                "human_feedback": row["human_feedback"],
                "joint_verdict": _joint_verdict_display(row),
                "accepted_proposal_json": _safe_json(row["request_payload_json"]).get("_accepted_proposal"),
                "live_ai_result": _safe_json(row["request_payload_json"]).get("_live_ai_result"),
                "media_prep": _safe_json(row["request_payload_json"]).get("media_prep"),
                "input_preview": {
                    "system_excerpt": (_safe_json(row["request_payload_json"]).get("messages_preview") or {}).get(
                        "system_excerpt"
                    ),
                    "user_full": (_safe_json(row["request_payload_json"]).get("messages_preview") or {}).get(
                        "user_full"
                    ),
                    "excel_assessment_included": _safe_json(row["request_payload_json"]).get(
                        "excel_assessment_included", False
                    ),
                    "format_pack": _safe_json(row["request_payload_json"]).get("format_pack"),
                    "instruction_bundle": _safe_json(row["request_payload_json"]).get("instruction_bundle"),
                },
                "status": row["status"],
            }
        )
    usage = [
        dict(r)
        for r in conn.execute(
            """
            SELECT id, client_id, post_id, provider, model, prompt_version, started_at, status,
                   prompt_tokens, completion_tokens, total_tokens,
                   extra_tool_cost, extra_media_cost, currency,
                   estimated_cost, actual_cost, cost_known, rate_date, notes
            FROM ai_usage_events
            WHERE trial_run_id = ?
            ORDER BY id
            """,
            (run["id"],),
        ).fetchall()
    ]
    result = {
        "trial": {
            "id": run["id"],
            "trial_key": run["trial_key"],
            "status": run["status"],
            "provider": run["provider"],
            "model": run["model"],
            "prompt_version": run["prompt_version"],
            "prepared_at": run["prepared_at"],
            "executed_at": run["executed_at"],
            "capability": json.loads(run["capability_json"] or "{}"),
            "estimate": json.loads(run["estimate_json"] or "{}"),
            "notes": json.loads(run["notes_json"] or "[]"),
            "posts": posts,
            "usage_events": usage,
        },
        "prompt_catalog": catalog,
        "cost_rates": [dict(r) for r in rates],
        "ai_status": public_ai_status(),
    }
    try:
        from maaike.ai_trial_feedback import attach_feedback_to_trial_posts

        for post in result["trial"]["posts"]:
            post["request_payload"] = post.get("request_payload") or {}
            if post.get("live_ai_result"):
                post["request_payload"]["_live_ai_result"] = post["live_ai_result"]
        attach_feedback_to_trial_posts(conn, client_id, result["trial"]["posts"])
    except Exception:
        pass
    return result


def _safe_json(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _joint_verdict_display(row) -> str:
    human = str(row["human_feedback"] or "").strip()
    stored = str(row["joint_verdict"] or "").strip()
    has_ai = bool(str(row["ai_insight"] or "").strip() or str(row["ai_format_code"] or "").strip())
    if human and has_ai and stored:
        return stored
    if human and not has_ai:
        return "Menselijke notitie opgeslagen; nog geen AI-resultaat — geen gezamenlijk eindoordeel."
    if has_ai and not human:
        return "Alleen AI-analyse aanwezig — geen gezamenlijk eindoordeel zonder menselijke beoordeling."
    return "Nog geen gezamenlijk oordeel — menselijke feedback ontbreekt."


def save_human_feedback(conn, client_id: int, post_id: int, feedback: str) -> dict[str, Any]:
    run = conn.execute(
        "SELECT id FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    if run is None:
        raise ValueError("Geen AI-proef voorbereid voor deze klant.")
    owned = conn.execute(
        "SELECT id FROM posts WHERE id = ? AND client_id = ?",
        (post_id, client_id),
    ).fetchone()
    if owned is None:
        raise ValueError("Post hoort niet bij deze klant.")
    text = str(feedback or "").strip()
    row = conn.execute(
        "SELECT * FROM ai_trial_posts WHERE trial_run_id = ? AND post_id = ?",
        (run["id"], post_id),
    ).fetchone()
    if row is None:
        raise ValueError("Proefpost niet gevonden.")
    has_ai = bool(str(row["ai_insight"] or "").strip() or str(row["ai_format_code"] or "").strip())
    if text and has_ai:
        joint = "AI-analyse + menselijke feedback vastgelegd (gezamenlijke notitie). Historische Excel-velden ongewijzigd."
    elif text:
        joint = "Menselijke notitie opgeslagen; nog geen AI-resultaat — geen gezamenlijk eindoordeel."
    elif has_ai:
        joint = "Alleen AI-analyse aanwezig — geen gezamenlijk eindoordeel zonder menselijke beoordeling."
    else:
        joint = "Nog geen gezamenlijk oordeel — menselijke feedback ontbreekt."
    conn.execute(
        """
        UPDATE ai_trial_posts
        SET human_feedback = ?, joint_verdict = ?
        WHERE trial_run_id = ? AND post_id = ?
        """,
        (text, joint, run["id"], post_id),
    )
    return get_trial(conn, client_id)


def accept_ai_proposal(conn, client_id: int, post_id: int, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Store an accepted proposal without overwriting Excel/editorial history."""
    run = conn.execute(
        "SELECT id FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    if run is None:
        raise ValueError("Geen AI-proef voorbereid voor deze klant.")
    row = conn.execute(
        """
        SELECT t.* FROM ai_trial_posts t
        JOIN posts p ON p.id = t.post_id
        WHERE t.trial_run_id = ? AND t.post_id = ? AND p.client_id = ?
        """,
        (run["id"], post_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Proefpost niet gevonden voor deze klant.")
    payload = _safe_json(row["request_payload_json"])
    accepted = {
        "accepted_at": _now(),
        "format_code": (body or {}).get("format_code", row["ai_format_code"]),
        "pillar": (body or {}).get("pillar", row["ai_pillar"]),
        "hook": (body or {}).get("hook", row["ai_hook"]),
        "insight": (body or {}).get("insight", row["ai_insight"]),
        "action": (body or {}).get("action", row["ai_action"]),
        "overwrote_excel": False,
        "overwrote_editorial": False,
        "note": "Voorstel geaccepteerd in proefopslag; historische Excel/editorial-velden niet overschreven.",
    }
    payload["_accepted_proposal"] = accepted
    conn.execute(
        "UPDATE ai_trial_posts SET request_payload_json = ? WHERE trial_run_id = ? AND post_id = ?",
        (json.dumps(payload, ensure_ascii=False), run["id"], post_id),
    )
    return get_trial(conn, client_id)


def _store_mock_usage_event(
    conn,
    run,
    client_id: int,
    post_id: int,
    usage: dict[str, Any] | None,
    finished: str,
    *,
    status: str = "failed",
) -> None:
    usage = usage or {}
    conn.execute(
        """
        UPDATE ai_usage_events SET
            finished_at = ?,
            status = ?,
            prompt_tokens = ?,
            completion_tokens = ?,
            total_tokens = ?,
            actual_cost = ?,
            cost_known = ?,
            notes = ?
        WHERE trial_run_id = ? AND post_id = ?
        """,
        (
            finished,
            str(usage.get("status") or status),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
            usage.get("actual_cost") if usage.get("cost_known") else None,
            1 if usage.get("cost_known") else 0,
            str(
                usage.get("notes")
                or "Mock/LOCAL_TEST; geen betaalde aanvraag. Onbruikbaar antwoord niet als succes."
            ),
            run["id"],
            post_id,
        ),
    )


def apply_mock_ai_result(
    conn,
    client_id: int,
    post_id: int,
    result: dict[str, Any],
    *,
    usage: dict[str, Any] | None = None,
    raw_text: str | None = None,
) -> dict[str, Any]:
    """Store a mocked AI response for tests. Does not call a paid API.

    Invalid/empty answers are stored as failed (with raw payload) — never as
    mock_completed success. Does not overwrite human feedback rows (execution_key).
    """
    from maaike.ai_response_validate import failed_body_envelope, validate_post_analysis

    run = conn.execute(
        "SELECT * FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    if run is None:
        raise ValueError("Geen AI-proef voorbereid voor deze klant.")
    if run["status"] == "running":
        # allow completing a started mock run
        pass
    row = conn.execute(
        """
        SELECT t.id, t.role, t.request_payload_json FROM ai_trial_posts t
        JOIN posts p ON p.id = t.post_id
        WHERE t.trial_run_id = ? AND t.post_id = ? AND p.client_id = ?
        """,
        (run["id"], post_id, client_id),
    ).fetchone()
    if row is None:
        raise ValueError("Proefpost niet gevonden voor deze klant.")

    finished = _now()
    payload = _safe_json(row["request_payload_json"] if row else "{}")
    limitations = (payload.get("media_prep") or {}).get("limitations") or []
    raw_blob = raw_text if raw_text is not None else json.dumps(result or {}, ensure_ascii=False)
    validation = validate_post_analysis(
        result if isinstance(result, dict) else None,
        raw_text=raw_blob,
        role=str(row["role"] or ""),
        limitations=limitations,
        test_label="LOCAL_TEST / MOCK — geen echte Claude-uitvoering",
    )
    normalized = validation.normalized if validation.usable and validation.normalized else None

    live_blob = {
        "executed_at": finished,
        "provider": run["provider"] or "mock",
        "model": run["model"] or "mock",
        "prompt_version": PROMPT_VERSION,
        "images_sent": [],
        "limitations": limitations,
        "result": normalized,
        "raw_excerpt": (raw_blob or "")[:4000],
        "raw_response": (raw_blob or "")[:50000],
        "error": None if validation.usable else validation.user_message,
        "validation": validation.as_dict(),
        "usage": usage or {},
        "actual_cost_usd": None,
        "cost_known": False,
        "mock": True,
        "test_label": "LOCAL_TEST / MOCK — geen echte Claude-uitvoering",
        "accepted_automatically": False,
        "excel_included_in_request": False,
        "analysis_usable": bool(validation.usable),
    }
    payload["_live_ai_result"] = live_blob
    # New execution_key via executed_at; prior feedback rows remain on old keys.
    payload.pop("_accepted_proposal", None)

    if normalized is not None and validation.usable:
        observations = normalized.get("observations") or []
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
                status = 'mock_completed',
                joint_verdict = CASE
                    WHEN trim(coalesce(human_feedback,'')) = '' THEN
                        'Alleen AI-analyse; niet menselijk beoordeeld'
                    ELSE joint_verdict
                END
            WHERE trial_run_id = ? AND post_id = ?
            """,
            (
                json.dumps(payload, ensure_ascii=False),
                json.dumps(observations, ensure_ascii=False),
                str(normalized.get("proposed_format_code") or ""),
                str(normalized.get("format_rationale") or ""),
                str(normalized.get("format_uncertainty") or ""),
                str(normalized.get("proposed_pillar") or ""),
                str(normalized.get("proposed_hook") or ""),
                str(normalized.get("ai_insight") or ""),
                str(normalized.get("ai_action") or ""),
                run["id"],
                post_id,
            ),
        )
    else:
        fail_envelope = failed_body_envelope(
            label="LOCAL_TEST / MOCK — onbruikbaar AI-antwoord",
            raw_text=raw_blob,
            raw_parsed=result,
            validation=validation,
        )
        live_blob["result"] = None
        live_blob["failed_body"] = fail_envelope
        payload["_live_ai_result"] = live_blob
        conn.execute(
            """
            UPDATE ai_trial_posts SET
                request_payload_json = ?,
                ai_observations_json = '[]',
                ai_format_code = '',
                ai_format_rationale = '',
                ai_format_uncertainty = '',
                ai_pillar = '',
                ai_hook = '',
                ai_insight = '',
                ai_action = '',
                status = 'failed',
                joint_verdict = CASE
                    WHEN trim(coalesce(human_feedback,'')) = '' THEN
                        ?
                    ELSE joint_verdict
                END
            WHERE trial_run_id = ? AND post_id = ?
            """,
            (
                json.dumps(payload, ensure_ascii=False),
                validation.user_message or "AI-antwoord onbruikbaar; niet als geslaagde analyse opgeslagen.",
                run["id"],
                post_id,
            ),
        )
        # Still record usage event below; then raise so callers see the error.
        _store_mock_usage_event(conn, run, client_id, post_id, usage, finished)
        conn.execute(
            """
            UPDATE ai_trial_runs SET status = 'prepared_with_mock_results', executed_at = ?
            WHERE id = ?
            """,
            (finished, run["id"]),
        )
        raise ValueError(validation.user_message or "Onbruikbaar mock-AI-antwoord.")
    usage = usage or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    cost_known = bool(usage.get("cost_known"))
    actual_cost = usage.get("actual_cost") if cost_known else None
    conn.execute(
        """
        UPDATE ai_usage_events SET
            finished_at = ?,
            status = ?,
            prompt_tokens = ?,
            completion_tokens = ?,
            total_tokens = ?,
            actual_cost = ?,
            cost_known = ?,
            notes = ?
        WHERE trial_run_id = ? AND post_id = ?
        """,
        (
            _now(),
            str(usage.get("status") or "mock_completed"),
            prompt_tokens,
            completion_tokens,
            total_tokens,
            actual_cost,
            1 if cost_known else 0,
            str(
                usage.get("notes")
                or "Mockresultaat; geen betaalde aanvraag. Ontbrekende tokens blijven NULL (niet 0)."
            ),
            run["id"],
            post_id,
        ),
    )
    conn.execute(
        "UPDATE ai_trial_runs SET status = 'prepared_with_mock_results', executed_at = ? WHERE id = ?",
        (_now(), run["id"]),
    )
    return get_trial(conn, client_id)


def begin_paid_execution_guard(conn, client_id: int) -> dict[str, Any]:
    """Mark run as running to block double-clicks. Does not call the provider."""
    run = conn.execute(
        "SELECT * FROM ai_trial_runs WHERE client_id = ? AND trial_key = ?",
        (client_id, TRIAL_KEY),
    ).fetchone()
    if run is None:
        raise ValueError("Geen AI-proef voorbereid voor deze klant.")
    if run["status"] == "running":
        raise ValueError("Uitvoering loopt al. Voorkom dubbelklikken; herlaad voor status.")
    if run["status"] == "completed" and run["executed_at"]:
        raise ValueError(
            "Er bestaat al een echte uitvoering. Start geen nieuwe analyse via herladen; "
            "bekijk het opgeslagen resultaat."
        )
    if run["status"] == "prepared_with_mock_results" and run["executed_at"]:
        raise ValueError(
            "Er bestaat al een opgeslagen (mock)resultaat. Herladen start geen nieuwe analyse; "
            "voor een echte run gebruik de uitvoeringsroute na her-voorbereiden."
        )
    conn.execute(
        "UPDATE ai_trial_runs SET status = 'running' WHERE id = ?",
        (run["id"],),
    )
    return get_trial(conn, client_id)
