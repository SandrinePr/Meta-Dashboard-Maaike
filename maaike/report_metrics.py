"""Python-side period metrics for client reports. AI must not invent numbers."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def previous_equal_length(start: date, end: date) -> tuple[date, date]:
    """Previous period with the same number of calendar days, ending the day before start."""
    if end < start:
        raise ValueError("Einddatum ligt vóór startdatum.")
    length_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length_days - 1)
    return prev_start, prev_end


def resolve_period_window(
    *,
    period_year: int | None = None,
    period_month: int | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    compare_start: str | date | None = None,
    compare_end: str | date | None = None,
) -> dict[str, Any]:
    """Resolve primary + comparison windows. Default comparison = equal-length previous."""
    if start is not None and end is not None:
        start_d = start if isinstance(start, date) else _parse_day(str(start))
        end_d = end if isinstance(end, date) else _parse_day(str(end))
        if start_d is None or end_d is None:
            raise ValueError("Ongeldige periode-datums.")
        if end_d < start_d:
            raise ValueError("Einddatum ligt vóór startdatum.")
        mode = "custom"
        year = start_d.year
        month = start_d.month
    elif period_year is not None and period_month is not None:
        if not (1 <= int(period_month) <= 12):
            raise ValueError("Ongeldige maand.")
        start_d, end_d = month_bounds(int(period_year), int(period_month))
        mode = "calendar_month"
        year = int(period_year)
        month = int(period_month)
    else:
        raise ValueError("Geef een kalendermaand of start/eind-datums op.")

    if compare_start is not None and compare_end is not None:
        c_start = compare_start if isinstance(compare_start, date) else _parse_day(str(compare_start))
        c_end = compare_end if isinstance(compare_end, date) else _parse_day(str(compare_end))
        if c_start is None or c_end is None:
            raise ValueError("Ongeldige vergelijkingsdatums.")
        if c_end < c_start:
            raise ValueError("Vergelijking: einddatum ligt vóór startdatum.")
        compare_mode = "custom"
    else:
        c_start, c_end = previous_equal_length(start_d, end_d)
        compare_mode = "previous_equal_length"

    primary_len = (end_d - start_d).days + 1
    compare_len = (c_end - c_start).days + 1
    return {
        "mode": mode,
        "year": year,
        "month": month,
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "length_days": primary_len,
        "compare_mode": compare_mode,
        "previous_start": c_start.isoformat(),
        "previous_end": c_end.isoformat(),
        "compare_length_days": compare_len,
        "lengths_equal": primary_len == compare_len,
        "label": f"{start_d.isoformat()} to {end_d.isoformat()}",
        "compare_label": f"{c_start.isoformat()} to {c_end.isoformat()}",
    }


def trend_lookback_bounds(run_year: int, run_month: int) -> dict[str, Any]:
    """Terugblik: 21e vorige maand t/m 20e runmaand (Social Agent trendinstructie)."""
    if run_month == 1:
        prev_y, prev_m = run_year - 1, 12
    else:
        prev_y, prev_m = run_year, run_month - 1
    start = date(prev_y, prev_m, 21)
    end = date(run_year, run_month, 20)
    # Vooruitblik = runmaand + 2
    fwd_m = run_month + 2
    fwd_y = run_year
    while fwd_m > 12:
        fwd_m -= 12
        fwd_y += 1
    return {
        "run_year": run_year,
        "run_month": run_month,
        "lookback_start": start.isoformat(),
        "lookback_end": end.isoformat(),
        "planning_year": fwd_y,
        "planning_month": fwd_m,
        "title_hint": f"Created in {run_year}-{run_month:02d} | For {fwd_y}-{fwd_m:02d}",
    }


def _metric_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def collect_period_posts(conn, client_id: int, start: date, end: date) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.id, p.platform, p.content_kind, p.published_at, p.permalink, p.caption,
               p.views, p.likes, p.comments, p.shares, p.saves, p.clicks, p.reach,
               f.name AS format_name, pl.name AS pillar_name, e.hook
        FROM posts p
        LEFT JOIN post_editorial e ON e.post_id = p.id
        LEFT JOIN content_formats f ON f.id = e.format_id
        LEFT JOIN content_pillars pl ON pl.id = e.pillar_id
        WHERE p.client_id = ?
        ORDER BY p.published_at DESC
        """,
        (client_id,),
    ).fetchall()
    out = []
    for row in rows:
        pub = _parse_day(row["published_at"])
        if pub is None or pub < start or pub > end:
            continue
        out.append(
            {
                "post_id": row["id"],
                "platform": row["platform"],
                "content_kind": row["content_kind"],
                "published_at": row["published_at"],
                "published_date": pub.isoformat(),
                "permalink": row["permalink"],
                "caption_preview": (row["caption"] or "")[:160],
                "format_name": row["format_name"] or "",
                "pillar_name": row["pillar_name"] or "",
                "hook": row["hook"] or "",
                "metrics": {
                    "views": _metric_int(row["views"]),
                    "likes": _metric_int(row["likes"]),
                    "comments": _metric_int(row["comments"]),
                    "shares": _metric_int(row["shares"]),
                    "saves": _metric_int(row["saves"]),
                    "clicks": _metric_int(row["clicks"]),
                    "reach": _metric_int(row["reach"]),
                },
                "metrics_note": (
                    "Lifetime-/snapshotcijfers op de post; géén gemeten groei binnen de maand "
                    "tenzij apart gemeten."
                ),
            }
        )
    return out


def _sum_known(posts: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    values = [p["metrics"].get(metric) for p in posts]
    known = [v for v in values if v is not None]
    missing = len(values) - len(known)
    return {
        "metric": metric,
        "sum": sum(known) if known else None,
        "known_count": len(known),
        "missing_count": missing,
        "missing_not_zero": True,
        "average_over_known": (round(sum(known) / len(known), 2) if known else None),
    }


def _bucket_posts(
    posts: list[dict[str, Any]],
    field: str,
    empty_label: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    unclassified: list[dict[str, Any]] = []
    for post in posts:
        raw = post.get(field)
        text = str(raw).strip() if raw is not None else ""
        key = text or empty_label
        buckets.setdefault(key, []).append(post)
        if not text:
            unclassified.append(
                {
                    "post_id": post.get("post_id"),
                    "published_at": post.get("published_at"),
                    "platform": post.get("platform"),
                    "caption_preview": post.get("caption_preview"),
                    "permalink": post.get("permalink"),
                }
            )
    return buckets, unclassified


def _finalize_group_bucket(
    bucket: dict[str, list[dict[str, Any]]],
    *,
    empty_label: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, group_posts in bucket.items():
        reach = _sum_known(group_posts, "reach")
        likes = _sum_known(group_posts, "likes")
        views = _sum_known(group_posts, "views")
        comments = _sum_known(group_posts, "comments")
        rows.append(
            {
                "name": name,
                "is_unclassified": name == empty_label,
                "post_count": len(group_posts),
                "totals": {
                    "reach": reach["sum"],
                    "likes": likes["sum"],
                    "views": views["sum"],
                    "comments": comments["sum"],
                },
                "averages": {
                    "reach": reach["average_over_known"],
                    "likes": likes["average_over_known"],
                    "views": views["average_over_known"],
                    "comments": comments["average_over_known"],
                },
                "available_counts": {
                    "reach": reach["known_count"],
                    "likes": likes["known_count"],
                    "views": views["known_count"],
                    "comments": comments["known_count"],
                },
                "missing_counts": {
                    "reach": reach["missing_count"],
                    "likes": likes["missing_count"],
                    "views": views["missing_count"],
                    "comments": comments["missing_count"],
                },
                # Backward-compatible flat fields
                "reach_sum": reach["sum"],
                "reach_avg": reach["average_over_known"],
                "likes_sum": likes["sum"],
                "views_sum": views["sum"],
                "known_reach_posts": reach["known_count"],
                "comparison_fairness": (
                    "Vergelijk alleen groepen met bekende meetwaarden; "
                    "ontbrekende cijfers tellen niet als 0. "
                    "Verschillende postaantallen maken groepen niet 1-op-1 vergelijkbaar."
                ),
            }
        )
    rows.sort(
        key=lambda r: (
            1 if r["is_unclassified"] else 0,
            r["reach_sum"] is None,
            -(r["reach_sum"] or 0),
            -r["post_count"],
            r["name"],
        )
    )
    return rows


def aggregate_posts(posts: list[dict[str, Any]]) -> dict[str, Any]:
    by_platform: dict[str, int] = {}
    for post in posts:
        plat = post.get("platform") or "onbekend"
        by_platform[plat] = by_platform.get(plat, 0) + 1

    fmt_bucket, fmt_unclassified = _bucket_posts(posts, "format_name", "(geen format)")
    pillar_bucket, pillar_unclassified = _bucket_posts(posts, "pillar_name", "(geen pijler)")
    hook_bucket, hook_unclassified = _bucket_posts(posts, "hook", "(geen hook)")

    totals = {
        name: _sum_known(posts, name)
        for name in ("views", "likes", "comments", "shares", "saves", "clicks", "reach")
    }
    averages = {name: totals[name]["average_over_known"] for name in totals}
    available_counts = {name: totals[name]["known_count"] for name in totals}
    missing_counts = {name: totals[name]["missing_count"] for name in totals}

    return {
        "post_count": len(posts),
        "by_platform": by_platform,
        "totals": totals,
        "averages": averages,
        "available_counts": available_counts,
        "missing_counts": missing_counts,
        "by_format": _finalize_group_bucket(fmt_bucket, empty_label="(geen format)"),
        "by_pillar": _finalize_group_bucket(pillar_bucket, empty_label="(geen pijler)"),
        "by_hook": _finalize_group_bucket(hook_bucket, empty_label="(geen hook)"),
        "unclassified": {
            "format": {"count": len(fmt_unclassified), "posts": fmt_unclassified},
            "pillar": {"count": len(pillar_unclassified), "posts": pillar_unclassified},
            "hook": {"count": len(hook_unclassified), "posts": hook_unclassified},
        },
        "caveats": [
            "Snapshot-cijfers zijn geen bewezen maandgroei.",
            "Ontbrekende metrics worden niet als 0 meegeteld.",
            "Totalen en gemiddelden staan apart; gemiddelden alleen over bekende waarden.",
            "Zonder gelijke platform/metric/bron is een significant verschil niet claimbaar.",
        ],
    }


def _delta_value(current: Any, previous: Any) -> dict[str, Any]:
    """Absolute + optional %. No misleading % when previous is missing or zero."""
    out: dict[str, Any] = {
        "current": current,
        "previous": previous,
        "absolute": None,
        "pct": None,
        "pct_available": False,
        "pct_note": None,
        "direction": None,
        "direction_label": None,
    }
    if current is None or previous is None:
        out["pct_note"] = "No percentage: missing value in current or previous period."
        out["direction"] = "unknown"
        if current is not None and previous is None:
            out["direction_label"] = "no previous value"
        elif current is None and previous is not None:
            out["direction_label"] = "no current value"
        else:
            out["direction_label"] = "both missing"
        return out
    try:
        cur_f = float(current)
        prev_f = float(previous)
    except (TypeError, ValueError):
        out["pct_note"] = "No percentage: non-numeric value."
        out["direction"] = "unknown"
        out["direction_label"] = "not comparable"
        return out

    absolute = round(cur_f - prev_f, 2)
    out["absolute"] = absolute
    if absolute > 0:
        out["direction"] = "up"
        out["direction_label"] = "higher"
    elif absolute < 0:
        out["direction"] = "down"
        out["direction_label"] = "lower"
    else:
        out["direction"] = "flat"
        out["direction_label"] = "unchanged"

    if prev_f == 0:
        out["pct_note"] = "No percentage: previous period is zero (would be misleading)."
        return out

    out["pct"] = round(100.0 * (cur_f - prev_f) / abs(prev_f), 2)
    out["pct_available"] = True
    return out


def compare_periods(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    *,
    metric: str = "reach",
) -> dict[str, Any]:
    cur = _sum_known(current, metric)
    prev = _sum_known(previous, metric)
    sum_delta = _delta_value(cur["sum"], prev["sum"])
    avg_delta = _delta_value(cur["average_over_known"], prev["average_over_known"])
    count_delta = _delta_value(len(current), len(previous))

    comparable = (
        cur["known_count"] > 0
        and prev["known_count"] > 0
        and cur["sum"] is not None
        and prev["sum"] is not None
    )
    # Keep legacy keys; never invent a % when previous sum is 0 or missing
    delta = sum_delta["absolute"] if comparable else None
    pct = sum_delta["pct"] if comparable and sum_delta["pct_available"] else None

    return {
        "metric": metric,
        "current": cur,
        "previous": prev,
        "current_post_count": len(current),
        "previous_post_count": len(previous),
        "delta_sum": delta,
        "delta_pct_vs_previous_sum": pct,
        "comparable": comparable,
        "claim_significant_difference": False,
        "direction": sum_delta["direction_label"] if comparable else None,
        "deltas": {
            "post_count": count_delta,
            "sum": sum_delta,
            "average_over_known": avg_delta,
        },
        "note": (
            "Differences are descriptive (higher/lower). "
            "No automatic significance claim. "
            "Different post counts and measurement moments limit comparability."
            if comparable
            else "Not enough comparable known measurements for this metric."
        ),
    }


def compare_group_lists(
    current_groups: list[dict[str, Any]],
    previous_groups: list[dict[str, Any]],
    *,
    value_key: str = "reach_sum",
) -> list[dict[str, Any]]:
    prev_map = {g["name"]: g for g in previous_groups}
    names = sorted(
        {g["name"] for g in current_groups} | set(prev_map.keys()),
        key=lambda n: n.lower(),
    )
    rows: list[dict[str, Any]] = []
    for name in names:
        cur = next((g for g in current_groups if g["name"] == name), None)
        prev = prev_map.get(name)
        cur_val = cur.get(value_key) if cur else None
        prev_val = prev.get(value_key) if prev else None
        rows.append(
            {
                "name": name,
                "current_count": cur.get("post_count") if cur else 0,
                "previous_count": prev.get("post_count") if prev else 0,
                "current_value": cur_val,
                "previous_value": prev_val,
                "delta": _delta_value(cur_val, prev_val),
            }
        )
    return rows


def build_period_metrics(
    conn,
    client_id: int,
    *,
    period_year: int | None = None,
    period_month: int | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    compare_start: str | date | None = None,
    compare_end: str | date | None = None,
    attach_enrichment: bool = True,
) -> dict[str, Any]:
    """Collect + aggregate + compare for one client window. No AI."""
    window = resolve_period_window(
        period_year=period_year,
        period_month=period_month,
        start=start,
        end=end,
        compare_start=compare_start,
        compare_end=compare_end,
    )
    start_d = date.fromisoformat(window["start"])
    end_d = date.fromisoformat(window["end"])
    prev_start_d = date.fromisoformat(window["previous_start"])
    prev_end_d = date.fromisoformat(window["previous_end"])

    posts = collect_period_posts(conn, client_id, start_d, end_d)
    prev_posts = collect_period_posts(conn, client_id, prev_start_d, prev_end_d)
    if attach_enrichment:
        posts = attach_assessments_and_ai(conn, client_id, posts)

    metrics = aggregate_posts(posts)
    prev_metrics = aggregate_posts(prev_posts)
    comparison = compare_periods(posts, prev_posts, metric="reach")
    comparison["by_format"] = compare_group_lists(
        metrics["by_format"], prev_metrics["by_format"], value_key="reach_sum"
    )
    comparison["by_pillar"] = compare_group_lists(
        metrics["by_pillar"], prev_metrics["by_pillar"], value_key="reach_sum"
    )
    comparison["by_hook"] = compare_group_lists(
        metrics["by_hook"], prev_metrics["by_hook"], value_key="reach_sum"
    )

    return {
        "period": window,
        "metrics": metrics,
        "previous_metrics": {
            "post_count": prev_metrics["post_count"],
            "totals": prev_metrics["totals"],
            "averages": prev_metrics["averages"],
            "available_counts": prev_metrics["available_counts"],
            "missing_counts": prev_metrics["missing_counts"],
            "by_format": prev_metrics["by_format"],
            "by_pillar": prev_metrics["by_pillar"],
            "by_hook": prev_metrics["by_hook"],
            "unclassified": prev_metrics["unclassified"],
            "by_platform": prev_metrics.get("by_platform") or {},
        },
        "comparison": comparison,
        "posts": posts,
        "previous_post_count": len(prev_posts),
        "ai_analysis_executed": False,
        "ai_must_not_invent_numbers": True,
        "calculation_engine": "python_report_metrics",
    }


def build_analysis_data_coverage(
    conn,
    client_id: int,
    period_bundle: dict[str, Any],
    *,
    stories: dict[str, Any] | None = None,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    """Human-facing coverage card before Execute. No Meta/AI calls.

    Distinguishes *stored* posts for the chosen window from *proven complete*
    Meta coverage (which Synchronise Meta cannot guarantee for a fixed 3 months).
    """
    period = period_bundle.get("period") or {}
    metrics = period_bundle.get("metrics") or {}
    prev_metrics = period_bundle.get("previous_metrics") or {}
    by_platform = dict(metrics.get("by_platform") or {})
    prev_by_platform = dict(prev_metrics.get("by_platform") or {})
    if not prev_by_platform:
        # Recompute lightly from previous window when older snapshots omit by_platform.
        try:
            prev_start = date.fromisoformat(str(period.get("previous_start")))
            prev_end = date.fromisoformat(str(period.get("previous_end")))
            prev_posts = collect_period_posts(conn, client_id, prev_start, prev_end)
            prev_by_platform = aggregate_posts(prev_posts).get("by_platform") or {}
        except Exception:
            prev_by_platform = {}

    client = conn.execute(
        """
        SELECT last_fetch_status, last_fetch_detail, last_fetch_at,
               last_fetch_from, last_fetch_until,
               last_fetch_instagram, last_fetch_facebook
        FROM clients WHERE id = ?
        """,
        (client_id,),
    ).fetchone()
    sync_status = (client["last_fetch_status"] if client else None) or None
    sync_detail = (client["last_fetch_detail"] if client else None) or ""
    sync_at = (client["last_fetch_at"] if client else None) or None
    sync_from = (client["last_fetch_from"] if client else None) or None
    sync_until = (client["last_fetch_until"] if client else None) or None

    analysis_start = str(period.get("start") or "")
    analysis_end = str(period.get("end") or "")
    coverage_known = False
    coverage_uncertain = True
    coverage_note = (
        "Stored post counts are what Analyse uses. Synchronise Meta does not request a "
        "fixed ‘last 3 months’ window: it pages Instagram/Facebook (25 posts/page, max 40 pages) "
        "with no since/until filter. First and later syncs use the same path. "
        "A successful sync still does not prove every Meta post for your analysis month is present."
    )
    if not sync_at:
        coverage_note += " No Meta sync recorded yet — run Synchronise Meta (sidebar) first."
    elif sync_status == "partial" or "more posts" in sync_detail.lower() or "partly" in sync_detail.lower():
        coverage_note += (
            f" Last sync was partial ({sync_status or 'unknown'}). "
            "Facebook/Instagram coverage for this period is uncertain."
        )
    elif sync_status == "complete" and sync_from and sync_until and analysis_start and analysis_end:
        # Window falls inside last fetch span → stored data exists, still not a Meta completeness proof.
        if sync_from[:10] <= analysis_start[:10] and analysis_end[:10] <= sync_until[:10]:
            coverage_uncertain = True
            coverage_note += (
                " Analysis dates fall inside the last sync’s published span, but completeness "
                "is still not proven (Meta may omit older pages; LinkedIn is never synced here)."
            )
        else:
            coverage_note += (
                " Analysis period is partly outside the last sync’s published span — "
                "re-run Synchronise Meta or check Social posts for gaps."
            )
    else:
        coverage_note += f" Last sync status: {sync_status or 'unknown'}."

    stories = stories or {}
    stories_present = bool(stories.get("present")) or int(stories.get("count") or 0) > 0
    missing_list = list(missing or [])
    if not stories_present:
        reason = stories.get("missing_reason") or "No stories/Figma planning items for this analysis period."
        if reason not in missing_list:
            missing_list.append(f"Stories: {reason}")

    linkedin_in_period = sum(
        int(by_platform.get(k) or 0)
        for k in by_platform
        if "linkedin" in str(k).lower()
    )

    return {
        "execute_uses_stored_data": True,
        "execute_note": (
            "Execute uses stored Bruine Beer data only (posts, metrics, strategy, linked trend). "
            "It does not call Synchronise Meta and does not pull a fresh 3-month feed."
        ),
        "analysis_period": {
            "label": period.get("label") or f"{analysis_start} → {analysis_end}",
            "start": analysis_start,
            "end": analysis_end,
            "year": period.get("year"),
            "month": period.get("month"),
            "mode": period.get("mode"),
            "length_days": period.get("length_days"),
        },
        "comparison_period": {
            "label": period.get("compare_label")
            or f"{period.get('previous_start')} → {period.get('previous_end')}",
            "start": period.get("previous_start"),
            "end": period.get("previous_end"),
            "mode": period.get("compare_mode"),
            "length_days": period.get("compare_length_days"),
        },
        "posts_in_analysis": int(metrics.get("post_count") or 0),
        "posts_by_platform": by_platform,
        "posts_in_comparison": int(prev_metrics.get("post_count") or 0),
        "comparison_by_platform": prev_by_platform,
        "stories": {
            "present": stories_present,
            "count": int(stories.get("count") or 0),
            "sources": stories.get("sources") or [],
            "missing_reason": None
            if stories_present
            else (stories.get("missing_reason") or "No stories for this period."),
        },
        "missing_layers": missing_list,
        "meta_sync": {
            "last_status": sync_status,
            "last_at": sync_at,
            "last_detail": sync_detail,
            "last_fetch_from": sync_from,
            "last_fetch_until": sync_until,
            "last_fetch_instagram": client["last_fetch_instagram"] if client else None,
            "last_fetch_facebook": client["last_fetch_facebook"] if client else None,
            "coverage_proven_complete": coverage_known,
            "coverage_uncertain": coverage_uncertain,
            "coverage_note": coverage_note,
            "action": (
                "Sidebar → Synchronise Meta to refresh Instagram/Facebook. "
                "LinkedIn/Excel: Settings → Backup or Social posts import. "
                "Stories: Targets & Strategy → Figma planning."
            ),
        },
        "linkedin_note": (
            f"LinkedIn posts in this analysis window: {linkedin_in_period}. "
            "Synchronise Meta does not fetch LinkedIn — those rows come from Excel/manual import."
        ),
        "where_maaike_can_verify": [
            "Social posts → All posts (filter the analysis month)",
            "Social posts → Activity overview (last Meta sync status)",
            "Targets & Strategy → Figma planning (stories)",
            "Reports → Show figures & prompt input (this coverage card)",
        ],
        "sync_mechanics": {
            "date_filter_on_api": False,
            "page_limit_instagram": 25,
            "page_limit_facebook": 10,
            "page_limit_facebook_on_reduce_data": 5,
            "page_limit": 25,
            "max_pages": 40,
            "max_posts_per_platform_per_run": 1000,
            "first_vs_later_sync": "same path (full page walk until end or max pages)",
            "guarantees_last_3_months": False,
            "facebook_reduce_data_retry": True,
            "linkedin_via_meta": False,
        },
        "coverage_label": (
            "proven_incomplete"
            if sync_status == "partial"
            else ("unknown" if not sync_at else "stored_not_proven_complete")
        ),
    }


def _completed_post_ai_analysis(conn, client_id: int, post_id: int) -> dict[str, Any] | None:
    """Latest completed Claude/post_ai_analyses row for this client+post (status+version checked)."""
    try:
        from maaike.claude_analysis import ensure_analysis_tables

        ensure_analysis_tables(conn)
    except Exception:
        return None
    row = conn.execute(
        """
        SELECT id, client_id, post_id, provider, model, prompt_version, status,
               insight_text, action_text, rating_text, started_at, finished_at,
               cost_known, actual_cost_usd
        FROM post_ai_analyses
        WHERE client_id = ? AND post_id = ? AND status = 'completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (client_id, post_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "source": "post_ai_analyses",
        "id": row["id"],
        "client_id": row["client_id"],
        "post_id": row["post_id"],
        "provider": row["provider"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "status": row["status"],
        "insight_text": row["insight_text"] or "",
        "action_text": row["action_text"] or "",
        "rating_text": row["rating_text"] or "",
        "ai_insight": row["insight_text"] or "",
        "ai_action": row["action_text"] or "",
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "executed_at": row["finished_at"],
        "cost_known": bool(row["cost_known"]),
        "actual_cost_usd": row["actual_cost_usd"],
    }


def attach_assessments_and_ai(conn, client_id: int, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add Excel assessment + completed post AI analyses + trial/feedback (client-scoped)."""
    enriched = []
    for post in posts:
        owned = conn.execute(
            "SELECT id FROM posts WHERE id = ? AND client_id = ?",
            (post["post_id"], client_id),
        ).fetchone()
        if owned is None:
            continue
        excel_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(post_assessments)").fetchall()}
        score_bits = ""
        if "score_value" in excel_cols:
            score_bits = (
                ", score_value, rating_origin, score_origin, "
                "rating_missing_reason, score_missing_reason"
            )
        source_bit = ", source" if "source" in excel_cols else ""
        excel = None
        if "source" in excel_cols:
            excel = conn.execute(
                f"""
                SELECT source_label, rating_text, insight_text, action_text, imported_at
                       {source_bit}{score_bits}
                FROM post_assessments
                WHERE post_id = ? AND source = 'excel_imported'
                ORDER BY id DESC LIMIT 1
                """,
                (post["post_id"],),
            ).fetchone()
        if excel is None:
            excel = conn.execute(
                f"""
                SELECT source_label, rating_text, insight_text, action_text, imported_at
                       {source_bit}{score_bits}
                FROM post_assessments WHERE post_id = ? ORDER BY id DESC LIMIT 1
                """,
                (post["post_id"],),
            ).fetchone()
        trial = conn.execute(
            """
            SELECT t.ai_format_code, t.ai_pillar, t.ai_hook, t.ai_insight, t.ai_action,
                   t.status, t.joint_verdict, r.executed_at, r.model, r.prompt_version
            FROM ai_trial_posts t
            JOIN ai_trial_runs r ON r.id = t.trial_run_id
            WHERE t.post_id = ? AND r.client_id = ?
            ORDER BY t.id DESC LIMIT 1
            """,
            (post["post_id"], client_id),
        ).fetchone()
        feedback = conn.execute(
            """
            SELECT usability, notes, final_verdict, final_verdict_confirmed,
                   corrected_format, corrected_pillar, corrected_hook, updated_at, execution_key
            FROM ai_analysis_feedback
            WHERE client_id = ? AND post_id = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (client_id, post["post_id"]),
        ).fetchone()
        claude = _completed_post_ai_analysis(conn, client_id, post["post_id"])
        trial_payload = None
        if trial is not None:
            trial_payload = {
                "source": "ai_trial_posts",
                **dict(trial),
            }
        item = dict(post)
        item["excel_assessment"] = dict(excel) if excel else None
        # Prefer completed Claude/post_ai_analyses; keep trial separately for inspection.
        item["ai_analysis"] = claude if claude is not None else trial_payload
        item["ai_trial_analysis"] = trial_payload
        item["human_feedback"] = dict(feedback) if feedback else None
        enriched.append(item)
    return enriched


def summarize_attached_ai_analyses(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """Count attached analyses and whether completed Claude rows are in the prompt input."""
    attached = [p.get("ai_analysis") for p in posts if p.get("ai_analysis")]
    completed_claude = [
        a
        for a in attached
        if isinstance(a, dict)
        and a.get("source") == "post_ai_analyses"
        and str(a.get("status") or "") == "completed"
        and a.get("client_id") is not None
        and a.get("post_id") is not None
        and a.get("id") is not None
    ]
    return {
        "ai_analyses": len(attached),
        "completed_post_ai_analyses": len(completed_claude),
        "completed_analysis_ids": [a["id"] for a in completed_claude],
        "completed_post_ids": [a["post_id"] for a in completed_claude],
        "ai_analysis_executed": bool(completed_claude),
        "ai_analysis_status": (
            "completed_analyses_attached" if completed_claude else "not_executed"
        ),
        "ai_analysis_banner": (
            (
                f"{len(completed_claude)} completed Claude/post AI analysis(es) attached "
                f"(ids {', '.join(str(i) for i in [a['id'] for a in completed_claude])}). "
                "Included in client-report prompt input; figures remain Python-calculated."
            )
            if completed_claude
            else (
                "No completed Claude/post AI analyses attached for posts in this period. "
                "Figures and prompt input come from Python/database; there are no post-level "
                "AI conclusions in this input."
            )
        ),
    }
