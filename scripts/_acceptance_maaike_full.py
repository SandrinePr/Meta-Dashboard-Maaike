"""Full acceptance evidence pack against QA DB. No paid Meta/AI execute."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "data" / "maaike_redrock_qa_demo.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_acceptance_maaike_full.json"


def main() -> None:
    from maaike.activity_log import list_activity_events
    from maaike.ai_status import public_ai_status
    from maaike.ai_trial import get_trial, prepare_redrock_trial
    from maaike.client_report_pdf import render_client_report_pdf
    from maaike.db import connect
    from maaike.figma_planning import suggest_post_matches
    from maaike.migrate import apply_migrations
    from maaike.post_fetch import _MAX_PAGES, _PAGE_LIMIT
    from maaike.rating import get_rating_settings
    from maaike.report_execute import build_execute_model_input, execution_preview
    from maaike.reports import get_report, inspect_client_report_data
    from maaike.repository import list_formats, list_hooks, list_pillars
    from maaike.strategy import get_strategy

    conn = connect(QA)
    apply_migrations(conn)
    out: dict = {
        "qa_db": str(QA),
        "paid_calls": False,
        "version": {
            "git_tip_note": "working tree has large uncommitted Maaike work beyond last commit 4f73883",
            "qa_reports_checked": [15, 16, 20],
        },
    }

    client = dict(
        conn.execute(
            """
            SELECT id, name, last_fetch_status, last_fetch_detail, last_fetch_at,
                   last_fetch_from, last_fetch_until, last_fetch_instagram, last_fetch_facebook
            FROM clients WHERE id=1
            """
        ).fetchone()
    )
    out["client_sync"] = client
    out["sync_mechanics"] = {
        "page_limit": _PAGE_LIMIT,
        "max_pages": _MAX_PAGES,
        "max_per_platform": _PAGE_LIMIT * _MAX_PAGES,
        "api_date_filter": False,
        "first_equals_later": True,
        "guarantees_3_months": False,
        "linkedin_via_meta": False,
    }

    # Platform month coverage (stored counts — not completeness proof)
    months = ["2026-08", "2026-09", "2026-10", "2026-11"]
    coverage = {}
    for ym in months:
        rows = conn.execute(
            """
            SELECT platform, COUNT(*) n,
                   MIN(published_at) oldest, MAX(published_at) newest
            FROM posts WHERE client_id=1 AND published_at LIKE ?
            GROUP BY platform
            """,
            (ym + "%",),
        ).fetchall()
        coverage[ym] = [dict(r) for r in rows]
    out["stored_posts_by_month_platform"] = coverage
    out["platform_totals"] = [
        dict(r)
        for r in conn.execute(
            """
            SELECT platform, COUNT(*) n, MIN(published_at) oldest, MAX(published_at) newest
            FROM posts WHERE client_id=1 GROUP BY platform
            """
        )
    ]

    # Duplicates by platform+external_id
    dups = conn.execute(
        """
        SELECT platform, external_id, COUNT(*) n
        FROM posts WHERE client_id=1 AND external_id IS NOT NULL AND external_id != ''
        GROUP BY platform, external_id HAVING COUNT(*) > 1
        LIMIT 20
        """
    ).fetchall()
    out["duplicate_external_ids"] = [dict(r) for r in dups]

    # Metrics unknown vs zero sample for Sep
    metric_cols = ["views", "likes", "comments", "shares", "saves", "clicks", "reach"]
    # posts table may store metrics differently — use report metrics path
    inspect_sep = inspect_client_report_data(
        conn, 1, period_year=2026, period_month=9, linked_trend_report_id=15
    )
    inspect_3m = inspect_client_report_data(
        conn,
        1,
        start="2026-08-01",
        end="2026-10-31",
        compare_start="2026-05-01",
        compare_end="2026-07-31",
        linked_trend_report_id=15,
    )
    inspect_nov = inspect_client_report_data(conn, 1, period_year=2026, period_month=11)
    out["inspect"] = {
        "sep": {
            "posts": inspect_sep["metrics"]["post_count"],
            "by_platform": inspect_sep["metrics"].get("by_platform"),
            "missing": inspect_sep["missing"],
            "coverage": {
                k: inspect_sep["data_coverage"].get(k)
                for k in (
                    "execute_uses_stored_data",
                    "posts_by_platform",
                    "stories",
                    "meta_sync",
                )
            },
        },
        "three_months": {
            "posts": inspect_3m["metrics"]["post_count"],
            "by_platform": inspect_3m["metrics"].get("by_platform"),
            "coverage_uncertain": inspect_3m["data_coverage"]["meta_sync"]["coverage_uncertain"],
        },
        "nov_empty": {
            "posts": inspect_nov["metrics"]["post_count"],
            "missing": inspect_nov["missing"],
        },
    }

    # Strategy / legend
    strategy = get_strategy(conn, 1)
    out["strategy"] = {
        "targets_count": len(strategy.get("targets") or []),
        "start_answer_keys": list((strategy.get("start_answers") or {}).keys())[:20],
        "completed_at": strategy.get("completed_at"),
    }
    out["legend_counts"] = {
        "formats": len(list_formats(conn, 1)),
        "pillars": len(list_pillars(conn, 1)),
        "hooks": len(list_hooks(conn, 1)),
    }
    # second client isolation check if exists
    other = conn.execute("SELECT id, name FROM clients WHERE id != 1 LIMIT 1").fetchone()
    if other:
        out["legend_other_client"] = {
            "id": other["id"],
            "name": other["name"],
            "formats": len(list_formats(conn, int(other["id"]))),
        }

    rating = get_rating_settings(conn, 1)
    out["rating_settings"] = rating

    # Figma
    figma = conn.execute(
        """
        SELECT id, code, content_kind, format_raw, pillar_raw, hook_raw, node_id,
               period_year, period_month, format_usable, pillar_usable, hook_usable,
               linked_post_id, link_status, source_url
        FROM figma_planning_items WHERE client_id=1
        """
    ).fetchall()
    out["figma_items"] = [dict(r) for r in figma]
    figma_tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%figma%'"
        ).fetchall()
    ]
    out["figma_tables"] = figma_tables
    out["figma_connection"] = None
    for tname in figma_tables:
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({tname})").fetchall()]
        if "file_key" in cols and "client_id" in cols:
            row = conn.execute(
                f"SELECT * FROM {tname} WHERE client_id=1 ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            out["figma_connection"] = {k: row[k] for k in row.keys()} if row else None
            break
    # B1 suggestions
    b1 = next((dict(r) for r in figma if str(r["code"] or "").upper() == "B1"), None)
    suggestions = []
    if b1:
        try:
            suggestions = suggest_post_matches(conn, 1, int(b1["id"]))
        except Exception as exc:
            suggestions = [{"error": str(exc)}]
    out["figma_b1"] = {"item": b1, "suggestions_top": (suggestions or [])[:5]}

    # AI trial prepare (no execute)
    try:
        trial = prepare_redrock_trial(conn, 1)
        stored = get_trial(conn, 1)
        t = trial.get("trial") if isinstance(trial, dict) else None
        out["ai_trial_prepare"] = {
            "prepare_status": (t or trial or {}).get("status") if isinstance(t or trial, dict) else None,
            "stored_status": (stored.get("trial") or stored).get("status")
            if isinstance(stored, dict)
            else None,
            "keys": list(trial.keys()) if isinstance(trial, dict) else [],
            "paid_on_prepare": False,
        }
    except Exception as exc:
        out["ai_trial_prepare"] = {"error": str(exc)}

    # Claude / AI status (no paid analyse)
    out["ai_status"] = public_ai_status()

    # Post AI analyses present?
    try:
        analyses = conn.execute(
            """
            SELECT id, post_id, status, model, provider, substr(COALESCE(error_text,''),1,80) err
            FROM post_ai_analyses WHERE client_id=1 ORDER BY id DESC LIMIT 10
            """
        ).fetchall()
        out["post_ai_analyses"] = [dict(r) for r in analyses]
    except Exception as exc:
        out["post_ai_analyses"] = {"error": str(exc)}

    # Report #15 / #20
    r15 = get_report(conn, 1, 15)
    r20 = get_report(conn, 1, 20)
    body20 = r20["report"]["body"]
    six = body20.get("six_answers") or {}
    out["report_15"] = {
        "status": r15["report"]["status"],
        "partial": (r15["report"].get("body") or {}).get("partial"),
        "review": (r15.get("review") or {}).get("review_status"),
    }
    out["report_20"] = {
        "status": r20["report"]["status"],
        "model": r20["report"].get("model"),
        "is_mock": r20["report"].get("is_mock"),
        "review": (r20.get("review") or {}).get("review_status"),
        "six_answer_keys": list(six.keys()),
        "six_nonempty": {k: bool(str(v or "").strip()) for k, v in six.items()},
        "unassessable": body20.get("unassessable"),
        "chapters_keys": list((body20.get("chapters") or {}).keys()),
    }
    # PDF check
    pdf_bytes, pdf_pres = render_client_report_pdf(conn, 1, 20)
    pdf_text = ""
    try:
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pdf_text = "\n".join(page.get_text() or "" for page in doc)
    except Exception as exc:
        pdf_text = f"extract_failed:{exc}"
    out["pdf_20"] = {
        "bytes": len(pdf_bytes),
        "content_source": pdf_pres.get("content_source"),
        "has_qa_marker": "QA REAL" in pdf_text,
        "internal_feedback_leaked": "Interne QA-notitie" in pdf_text,
        "sample_chars": len(pdf_text),
    }

    # Model input for #20 (what AI would get) — from snapshot
    snap = r20["report"].get("input_snapshot") or {}
    model_input = build_execute_model_input(r20["report"], snap)
    out["model_input_20_keys"] = list(model_input.keys())
    out["model_input_20_metrics_post_count"] = (model_input.get("metrics") or {}).get("post_count") or (
        model_input.get("python_metrics") or {}
    ).get("post_count")
    preview = execution_preview(conn, 1, 20)
    out["execution_preview_20"] = {
        "paid_call": preview.get("paid_call"),
        "coverage_posts": (preview.get("data_coverage") or {}).get("posts_by_platform"),
        "stories": (preview.get("data_coverage") or {}).get("stories"),
    }

    # Activity series
    activity = list_activity_events(conn, client_id=1, limit=40)
    series20 = next((e for e in activity["events"] if e.get("latest_report_id") == 20), None)
    out["activity_series_20"] = {
        "display_label": (series20 or {}).get("display_label"),
        "has_earlier_failures": (series20 or {}).get("has_earlier_failures"),
        "failed_ids": [a["report_id"] for a in (series20 or {}).get("attempts") or [] if a.get("is_error")],
    }
    out["activity_has_meta_sync"] = any(e["activity_type"] == "meta_sync" for e in activity["events"])

    # Sample posts for media kinds
    kinds = conn.execute(
        """
        SELECT content_kind, platform, COUNT(*) n
        FROM posts WHERE client_id=1 GROUP BY content_kind, platform
        ORDER BY n DESC LIMIT 30
        """
    ).fetchall()
    out["content_kinds"] = [dict(r) for r in kinds]
    post_cols = {c[1] for c in conn.execute("PRAGMA table_info(posts)").fetchall()}
    media_col = next(
        (c for c in ("media_urls", "media_json", "media_urls_json", "thumbnail_url") if c in post_cols),
        None,
    )
    samples = {}
    for kind in ("IMAGE", "CAROUSEL", "VIDEO", "REEL", "STORY"):
        if media_col:
            sql = f"""
                SELECT id, platform, content_kind, published_at,
                       CASE WHEN {media_col} IS NULL OR {media_col}='' THEN 0 ELSE 1 END AS has_media
                FROM posts WHERE client_id=1 AND upper(COALESCE(content_kind,'')) LIKE ?
                ORDER BY published_at DESC LIMIT 1
            """
        else:
            sql = """
                SELECT id, platform, content_kind, published_at, 0 AS has_media
                FROM posts WHERE client_id=1 AND upper(COALESCE(content_kind,'')) LIKE ?
                ORDER BY published_at DESC LIMIT 1
            """
        row = conn.execute(sql, (f"%{kind}%",)).fetchone()
        if row:
            samples[kind] = dict(row)
    out["media_samples"] = samples
    out["posts_media_column"] = media_col

    # Images tab removed?
    out["images_tab"] = {
        "reports_analysis_tabs": "reports_only",
        "working_image_feature": False,
        "note": "Images removed from menu; no replacement post-detail image analysis UI verified as complete.",
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "sep_posts": out["inspect"]["sep"]["posts"], "report20": out["report_20"]["status"], "pdf_marker": out["pdf_20"]["has_qa_marker"]}, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
