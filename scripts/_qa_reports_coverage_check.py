"""QA-only: coverage for 1 month, 3 months, and a sparse period. No paid AI."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA_DB = ROOT / "data" / "maaike_redrock_qa_demo.db"
OUT = ROOT / "data" / "imports" / "redrock" / "_qa_reports_coverage_check.json"


def _brief(coverage: dict) -> dict:
    sync = coverage.get("meta_sync") or {}
    return {
        "analysis": coverage.get("analysis_period"),
        "comparison": coverage.get("comparison_period"),
        "posts_in_analysis": coverage.get("posts_in_analysis"),
        "posts_by_platform": coverage.get("posts_by_platform"),
        "posts_in_comparison": coverage.get("posts_in_comparison"),
        "comparison_by_platform": coverage.get("comparison_by_platform"),
        "stories": coverage.get("stories"),
        "missing_layers": coverage.get("missing_layers"),
        "coverage_uncertain": sync.get("coverage_uncertain"),
        "coverage_proven_complete": sync.get("coverage_proven_complete"),
        "last_sync_status": sync.get("last_status"),
        "execute_uses_stored_data": coverage.get("execute_uses_stored_data"),
        "sync_mechanics": coverage.get("sync_mechanics"),
    }


def main() -> None:
    from maaike.db import connect
    from maaike.migrate import apply_migrations
    from maaike.reports import inspect_client_report_data
    from maaike.report_execute import execution_preview
    from maaike.post_fetch import _MAX_PAGES, _PAGE_LIMIT

    assert QA_DB.exists()
    conn = connect(QA_DB)
    apply_migrations(conn)

    client = conn.execute(
        """
        SELECT id, name, last_fetch_status, last_fetch_detail, last_fetch_at,
               last_fetch_from, last_fetch_until, last_fetch_instagram, last_fetch_facebook
        FROM clients WHERE id = 1
        """
    ).fetchone()

    one_month = inspect_client_report_data(
        conn, 1, period_year=2026, period_month=9, linked_trend_report_id=15
    )
    three_months = inspect_client_report_data(
        conn,
        1,
        start="2026-08-01",
        end="2026-10-31",
        compare_start="2026-05-01",
        compare_end="2026-07-31",
        linked_trend_report_id=15,
    )
    sparse = inspect_client_report_data(
        conn, 1, period_year=2026, period_month=11, linked_trend_report_id=15
    )

    preview20 = None
    row20 = conn.execute(
        "SELECT id, status FROM client_reports WHERE id = 20 AND client_id = 1"
    ).fetchone()
    if row20:
        preview20 = execution_preview(conn, 1, 20)

    out = {
        "qa_db": str(QA_DB),
        "paid_generation": False,
        "sync_code": {
            "module": "maaike/post_fetch.py → fetch_client_posts",
            "date_filter_on_api": False,
            "page_limit": _PAGE_LIMIT,
            "max_pages": _MAX_PAGES,
            "max_posts_per_platform_per_run": _PAGE_LIMIT * _MAX_PAGES,
            "first_vs_later": "same path",
            "guarantees_last_3_months": False,
            "linkedin_via_meta_sync": False,
        },
        "red_rock_last_sync": dict(client) if client else None,
        "one_month_sep_2026": {
            "missing": one_month.get("missing"),
            "coverage": _brief(one_month["data_coverage"]),
        },
        "three_months_aug_oct_2026": {
            "missing": three_months.get("missing"),
            "coverage": _brief(three_months["data_coverage"]),
        },
        "sparse_nov_2026_missing_posts": {
            "missing": sparse.get("missing"),
            "coverage": _brief(sparse["data_coverage"]),
        },
        "execution_preview_report_20": {
            "status": row20["status"] if row20 else None,
            "has_coverage": bool((preview20 or {}).get("data_coverage")),
            "coverage": _brief((preview20 or {}).get("data_coverage") or {}),
        }
        if row20
        else None,
        "where_maaike_sees_this": (one_month["data_coverage"] or {}).get("where_maaike_can_verify"),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    conn.close()


if __name__ == "__main__":
    main()
