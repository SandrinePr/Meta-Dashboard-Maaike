"""Weekly report figures from stored measurements only. No Meta and no AI calls."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from analytics.comparison import _period_fetch_complete, selected_accounts
from db.comparison_repository import classify_content_type
from db.database import get_connection

AMSTERDAM = ZoneInfo("Europe/Amsterdam")

NOT_AVAILABLE = "niet beschikbaar"
INSUFFICIENT = "nog onvoldoende meetgegevens"
BASELINE_MAX_GAP = timedelta(hours=48)
RANK_LIMIT = 10

RANKING_BASIS = (
    "Rangschikking op de som van like-toename en reactie-toename tussen twee opgeslagen metingen. "
    "Er wordt alleen gerangschikt als beide cijfers bekend zijn. "
    "Een meting van vóór de week telt alleen mee als die hooguit 48 uur vóór maandag 00:00 ligt. "
    "Anders telt alleen de toename tussen twee metingen binnen de week. "
    "Totaalcijfers sinds publicatie worden niet gebruikt. Een hogere som staat bovenaan."
)

STAND_LABEL = "Stand op meetmoment, geen weektoename"

REPORT_NOTES = (
    "Weektoename is het verschil tussen twee opgeslagen metingen, niet het totaal sinds publicatie.",
    "Een meting vóór de week telt alleen mee als die hooguit 48 uur vóór maandag 00:00 ligt.",
    "Weergaven, bereik en opgeslagen hebben geen meetreeks en zijn daarom niet als weekcijfer beschikbaar.",
    "Facebook heeft geen aparte weekmetingen in dit rapport.",
)

TYPE_LABELS = {
    "reel": "Reel",
    "carousel": "Carrousel",
    "image": "Afbeelding",
    "video": "Video",
    "unknown": "Onbekend",
}

BASIS_BEFORE = "voor_de_week"
BASIS_INSIDE = "binnen_de_week"


def week_containing(day: date) -> tuple[date, date]:
    """Monday–Sunday (Amsterdam calendar) that contains ``day``."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def previous_complete_week(today: date) -> tuple[date, date]:
    """Last Monday–Sunday that ended before ``today``."""
    this_monday = today - timedelta(days=today.weekday())
    previous_sunday = this_monday - timedelta(days=1)
    return previous_sunday - timedelta(days=6), previous_sunday


def format_int(value: int | None) -> str:
    if value is None:
        return NOT_AVAILABLE
    return f"{value:,}".replace(",", ".")


def format_delta(value: int | None, status: str) -> str:
    if status == "unavailable":
        return NOT_AVAILABLE
    if status != "ok" or value is None:
        return INSUFFICIENT
    sign = "+" if value > 0 else ""
    return f"{sign}{format_int(value)}"


def format_avg(value: float | None) -> str:
    if value is None:
        return INSUFFICIENT
    return f"{value:.1f}".replace(".", ",")


def format_published(count: int | None, coverage: str) -> str:
    if coverage == "unavailable" or count is None:
        return NOT_AVAILABLE
    if coverage == "minimum":
        return f"Minimaal {format_int(count)}"
    if coverage == "unknown":
        return f"{format_int(count)} (volledigheid niet bekend)"
    return format_int(count)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_local(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(AMSTERDAM).strftime("%d-%m-%Y %H:%M")


def _format_day(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _week_window(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, time.min, tzinfo=AMSTERDAM)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=AMSTERDAM)
    return start_dt, end_dt


def _display_name(username: str | None, name: str | None, external_id: str | None) -> str:
    if username:
        return f"@{username}"
    if name:
        return name
    if external_id:
        return external_id
    return NOT_AVAILABLE


def _opening_line(text: str | None) -> str | None:
    if not text or not str(text).strip():
        return None
    line = str(text).strip().splitlines()[0].strip()
    if not line:
        return None
    if len(line) > 180:
        return line[:177] + "…"
    return line


def _content_label(media_type: str | None, media_product_type: str | None) -> tuple[str, str]:
    key = classify_content_type(media_type, media_product_type)
    return key, TYPE_LABELS.get(key, TYPE_LABELS["unknown"])


def _latest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda row: (row["_dt"], int(row["id"])))


def _earliest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return min(rows, key=lambda row: (row["_dt"], int(row["id"])))


def _in_window(
    rows: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    return [row for row in rows if start <= row["_dt"] < end]


def _baseline_row(
    rows: list[dict[str, Any]],
    week_start: datetime,
) -> dict[str, Any] | None:
    window_start = week_start - BASELINE_MAX_GAP
    candidates = [row for row in rows if window_start <= row["_dt"] < week_start]
    return _latest(candidates)


def _count_delta(start_row: dict[str, Any], end_row: dict[str, Any], key: str) -> int | None:
    if start_row.get(key) is None or end_row.get(key) is None:
        return None
    return int(end_row[key]) - int(start_row[key])


def _pair_delta(
    rows: list[dict[str, Any]],
    week_start: datetime,
    week_end: datetime,
    *,
    like_key: str = "like_count",
    comment_key: str = "comments_count",
) -> dict[str, Any] | None:
    """Return a week delta only when two stored measurements actually bracket it."""
    inside = _in_window(rows, week_start, week_end)
    end_row = _latest(inside)
    baseline = _baseline_row(rows, week_start)
    if baseline is not None and end_row is not None:
        return {
            "basis": BASIS_BEFORE,
            "start": baseline,
            "end": end_row,
            "likes_delta": _count_delta(baseline, end_row, like_key),
            "comments_delta": _count_delta(baseline, end_row, comment_key),
        }
    if len(inside) >= 2:
        first = _earliest(inside)
        last = _latest(inside)
        if first is not None and last is not None and int(first["id"]) != int(last["id"]):
            return {
                "basis": BASIS_INSIDE,
                "start": first,
                "end": last,
                "likes_delta": _count_delta(first, last, like_key),
                "comments_delta": _count_delta(first, last, comment_key),
            }
    return None


def _basis_label(basis: str, start: datetime, end: datetime) -> str:
    start_label = _format_local(start) or NOT_AVAILABLE
    end_label = _format_local(end) or NOT_AVAILABLE
    if basis == BASIS_BEFORE:
        return (
            f"Toename tussen de meting van {start_label} en de meting van {end_label}. "
            "De eerdere meting ligt vlak vóór de week."
        )
    return (
        f"Toename tussen twee metingen binnen de week ({start_label} en {end_label}). "
        "De tijd vóór de eerste meting zit hier niet in."
    )


def _account_known(conn, account_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 AS found FROM posts WHERE account_id = ?
        UNION ALL
        SELECT 1 FROM account_measurements WHERE account_id = ?
        UNION ALL
        SELECT 1 FROM comparison_fetch_account_results
        WHERE account_id = ? AND status = 'success'
        LIMIT 1
        """,
        (account_id, account_id, account_id),
    ).fetchone()
    return row is not None


def _coverage(conn, account_id: int, known: bool) -> str:
    if not known:
        return "unavailable"
    complete = _period_fetch_complete(conn, account_id)
    if complete is True:
        return "exact"
    if complete is False:
        return "minimum"
    return "unknown"


def _follower_block(
    rows: list[dict[str, Any]],
    week_start: datetime,
    week_end: datetime,
    *,
    known: bool,
) -> dict[str, Any]:
    if not known and not rows:
        return {
            "followers_stand": None,
            "followers_stand_at": None,
            "followers_stand_display": None,
            "followers_delta": None,
            "followers_delta_status": "unavailable",
            "followers_from_display": None,
            "followers_to_display": None,
            "followers_note": "Volgers: niet beschikbaar.",
        }
    inside = _in_window(rows, week_start, week_end)
    end_row = _latest(inside)
    stand = int(end_row["followers_count"]) if end_row and end_row["followers_count"] is not None else None
    pair = _pair_delta(
        rows,
        week_start,
        week_end,
        like_key="followers_count",
        comment_key="followers_count",
    )
    stand_at = _format_local(end_row["_dt"]) if end_row else None
    if pair is None or pair["likes_delta"] is None:
        status = "insufficient" if known or rows else "unavailable"
        if stand is not None and stand_at:
            note = (
                f"Volgersstand op {stand_at}. "
                "Het verschil over de week is nog onvoldoende meetgegevens."
            )
        elif status == "unavailable":
            note = "Volgers: niet beschikbaar."
        else:
            note = "Volgersverschil: nog onvoldoende meetgegevens."
        return {
            "followers_stand": stand,
            "followers_stand_at": end_row["measured_at"] if end_row else None,
            "followers_stand_display": stand_at,
            "followers_delta": None,
            "followers_delta_status": status,
            "followers_from_display": None,
            "followers_to_display": None,
            "followers_note": note,
        }
    note = _basis_label(pair["basis"], pair["start"]["_dt"], pair["end"]["_dt"])
    return {
        "followers_stand": stand,
        "followers_stand_at": end_row["measured_at"] if end_row else None,
        "followers_stand_display": stand_at,
        "followers_delta": pair["likes_delta"],
        "followers_delta_status": "ok",
        "followers_from_display": _format_local(pair["start"]["_dt"]),
        "followers_to_display": _format_local(pair["end"]["_dt"]),
        "followers_note": f"Volgers: {note}",
    }


def _build_summary(
    own: dict[str, Any] | None,
    content_types: list[dict[str, Any]],
) -> str:
    if own is None:
        return "Eigen account: niet beschikbaar. Er is geen weeksamenvatting berekend."
    published = format_published(own["posts_published"], own["posts_published_coverage"])
    parts = [f"Geplaatste posts in deze week: {published}."]
    if own["followers_delta_status"] == "ok":
        parts.append(
            "Verschil in volgers tussen de twee metingen: "
            f"{format_delta(own['followers_delta'], 'ok')}."
        )
    elif own["followers_stand"] is not None:
        parts.append(
            "Volgersstand op de laatste meting in deze week: "
            f"{format_int(own['followers_stand'])}. "
            "Het weekverschil is nog onvoldoende meetgegevens."
        )
    else:
        parts.append(f"Volgersverschil: {format_delta(None, own['followers_delta_status'])}.")
    if own["interaction_status"] == "ok":
        parts.append(
            f"Op {own['comparable_posts']} posts met twee bruikbare metingen is de like-toename "
            f"{format_delta(own['likes_delta'], 'ok')} en de reactie-toename "
            f"{format_delta(own['comments_delta'], 'ok')}."
        )
        if own["excluded_posts"]:
            parts.append(
                f"{own['excluded_posts']} posts tellen niet mee omdat een tweede bruikbare meting ontbreekt."
            )
    else:
        parts.append(
            "Like- en reactietoename: nog onvoldoende meetgegevens."
            if own["interaction_status"] == "insufficient"
            else "Like- en reactietoename: niet beschikbaar."
        )
    compared = [
        row
        for row in content_types
        if row["performance_status"] == "ok" and row["interaction_avg"] is not None
    ]
    if compared:
        bits = [
            f"{row['label']} {format_avg(row['interaction_avg'])} ({row['comparable_posts']} posts)"
            for row in compared
        ]
        parts.append(
            "Gemiddelde interactietoename in deze metingen: "
            + ", ".join(bits)
            + ". Dit geldt alleen voor posts met twee bruikbare metingen en zegt niet dat een soort post altijd beter werkt."
        )
    return " ".join(parts)


def build_weekly_snapshot(
    *,
    period_start: date,
    period_end: date,
    own_account_id: int | None,
    competitor_usernames: list[str],
    built_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a JSON-ready snapshot. Reads SQLite only."""
    if period_start > period_end:
        period_start, period_end = period_end, period_start
    week_start, week_end = _week_window(period_start, period_end)
    moment = built_at or datetime.now(tz=timezone.utc)
    accounts = selected_accounts(own_account_id, competitor_usernames)
    account_ids = [account.account_id for account in accounts]

    empty_notes = list(REPORT_NOTES)
    if not accounts:
        return {
            "version": 1,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "period_label": f"{_format_day(period_start)} t/m {_format_day(period_end)}",
            "timezone": "Europe/Amsterdam",
            "built_at": moment.astimezone(timezone.utc).isoformat(),
            "built_at_display": _format_local(moment),
            "account_label": NOT_AVAILABLE,
            "own_account_id": own_account_id,
            "last_fetch_at": None,
            "last_fetch_display": None,
            "ranking_basis": RANKING_BASIS,
            "notes": empty_notes + ["Geen account geselecteerd."],
            "own": None,
            "competitors": [],
            "published_posts": [],
            "ranked_posts": [],
            "content_types": [],
            "summary": "Eigen account: niet beschikbaar. Er is geen weeksamenvatting berekend.",
            "measurement_window_notice": "Er is geen toename over de volledige week gemeten.",
        }

    placeholders = ",".join("?" for _ in account_ids)
    with get_connection() as conn:
        post_rows = conn.execute(
            f"""
            SELECT p.id AS post_id, p.account_id, p.published_at, p.text, p.permalink,
                   p.media_type, p.media_product_type, p.content_type,
                   a.username, a.name, a.external_id
            FROM posts p
            JOIN accounts a ON a.id = p.account_id
            WHERE p.account_id IN ({placeholders})
              AND p.platform = 'instagram'
            """,
            account_ids,
        ).fetchall()
        measurement_rows = conn.execute(
            f"""
            SELECT pm.id, pm.post_id, pm.measured_at, pm.like_count, pm.comments_count
            FROM post_measurements pm
            JOIN posts p ON p.id = pm.post_id
            WHERE p.account_id IN ({placeholders})
              AND p.platform = 'instagram'
            """,
            account_ids,
        ).fetchall()
        account_measurement_rows = conn.execute(
            f"""
            SELECT id, account_id, measured_at, followers_count
            FROM account_measurements
            WHERE account_id IN ({placeholders})
            """,
            account_ids,
        ).fetchall()
        known = {account_id: _account_known(conn, account_id) for account_id in account_ids}
        coverage = {
            account_id: _coverage(conn, account_id, known[account_id]) for account_id in account_ids
        }

    measurements_by_post: dict[int, list[dict[str, Any]]] = {}
    fetch_moments: list[datetime] = []
    for row in measurement_rows:
        measured = _parse_dt(row["measured_at"])
        if measured is None:
            continue
        fetch_moments.append(measured)
        measurements_by_post.setdefault(int(row["post_id"]), []).append(
            {
                "id": int(row["id"]),
                "measured_at": row["measured_at"],
                "_dt": measured,
                "like_count": row["like_count"],
                "comments_count": row["comments_count"],
            }
        )

    followers_by_account: dict[int, list[dict[str, Any]]] = {}
    for row in account_measurement_rows:
        measured = _parse_dt(row["measured_at"])
        if measured is None:
            continue
        fetch_moments.append(measured)
        followers_by_account.setdefault(int(row["account_id"]), []).append(
            {
                "id": int(row["id"]),
                "measured_at": row["measured_at"],
                "_dt": measured,
                "followers_count": row["followers_count"],
            }
        )

    posts_by_account: dict[int, list[Any]] = {}
    for row in post_rows:
        posts_by_account.setdefault(int(row["account_id"]), []).append(row)

    def account_payload(account) -> dict[str, Any]:
        account_id = account.account_id
        posts = posts_by_account.get(account_id, [])
        published = []
        for post in posts:
            published_at = _parse_dt(post["published_at"])
            if published_at is not None and week_start <= published_at < week_end:
                published.append(post)
        follower = _follower_block(
            followers_by_account.get(account_id, []),
            week_start,
            week_end,
            known=known.get(account_id, False),
        )
        comparable = 0
        excluded = 0
        likes_sum = 0
        comments_sum = 0
        baseline_start = week_start - BASELINE_MAX_GAP
        for post in posts:
            published_at = _parse_dt(post["published_at"])
            if published_at is not None and published_at >= week_end:
                continue
            post_measurements = measurements_by_post.get(int(post["post_id"]), [])
            pair = _pair_delta(post_measurements, week_start, week_end)
            if pair and pair["likes_delta"] is not None and pair["comments_delta"] is not None:
                comparable += 1
                likes_sum += int(pair["likes_delta"])
                comments_sum += int(pair["comments_delta"])
                continue
            published_this_week = (
                published_at is not None and week_start <= published_at < week_end
            )
            touched_this_week = any(
                baseline_start <= row["_dt"] < week_end for row in post_measurements
            )
            if published_this_week or touched_this_week:
                excluded += 1
        if not known.get(account_id, False):
            interaction_status = "unavailable"
            likes_delta = None
            comments_delta = None
            comparable = 0
            excluded = 0
        elif comparable == 0:
            interaction_status = "insufficient"
            likes_delta = None
            comments_delta = None
        else:
            interaction_status = "ok"
            likes_delta = likes_sum
            comments_delta = comments_sum
        if interaction_status == "ok":
            note = (
                f"Som van {comparable} posts met twee bruikbare metingen. "
                f"{excluded} posts tellen niet mee."
            )
        elif interaction_status == "insufficient":
            note = "Er zijn geen twee bruikbare metingen voor likes en reacties."
        else:
            note = "Voor dit account zijn geen metingen opgeslagen."
        cov = coverage.get(account_id, "unavailable")
        return {
            "account_id": account_id,
            "display_name": _display_name(account.username, account.name, account.external_id),
            "role": account.comparison_role or "",
            "known": bool(known.get(account_id, False)),
            "posts_published": None if cov == "unavailable" else len(published),
            "posts_published_coverage": cov,
            **follower,
            "likes_delta": likes_delta,
            "comments_delta": comments_delta,
            "interaction_status": interaction_status,
            "comparable_posts": comparable,
            "excluded_posts": excluded,
            "interaction_note": note,
        }

    blocks = [account_payload(account) for account in accounts]
    own_block = next((block for block in blocks if block["account_id"] == own_account_id), None)
    competitor_blocks = [block for block in blocks if block["account_id"] != own_account_id]
    account_label = own_block["display_name"] if own_block else NOT_AVAILABLE

    published_posts: list[dict[str, Any]] = []
    ranked_input: list[dict[str, Any]] = []
    window_starts: list[datetime] = []
    window_ends: list[datetime] = []
    window_ends: list[datetime] = []
    if own_account_id is not None:
        for post in posts_by_account.get(own_account_id, []):
            published_at = _parse_dt(post["published_at"])
            post_measurements = measurements_by_post.get(int(post["post_id"]), [])
            type_key, type_label = _content_label(post["media_type"], post["media_product_type"])
            opening = _opening_line(post["text"])
            if published_at is not None and week_start <= published_at < week_end:
                inside = _in_window(post_measurements, week_start, week_end)
                stand_row = _latest(inside)
                published_posts.append(
                    {
                        "post_id": int(post["post_id"]),
                        "published_at": post["published_at"],
                        "published_display": _format_local(published_at),
                        "content_type": type_key,
                        "content_label": type_label,
                        "opening_line": opening,
                        "permalink": post["permalink"],
                        "stand_likes": int(stand_row["like_count"])
                        if stand_row and stand_row["like_count"] is not None
                        else None,
                        "stand_comments": int(stand_row["comments_count"])
                        if stand_row and stand_row["comments_count"] is not None
                        else None,
                        "stand_status": "ok" if stand_row else "unavailable",
                        "stand_at_display": _format_local(stand_row["_dt"]) if stand_row else None,
                        "stand_label": STAND_LABEL,
                    }
                )
            pair = _pair_delta(post_measurements, week_start, week_end)
            if not pair or pair["likes_delta"] is None or pair["comments_delta"] is None:
                continue
            if published_at is not None and published_at >= week_end:
                continue
            ranked_input.append(
                {
                    "post_id": int(post["post_id"]),
                    "published_at": post["published_at"],
                    "published_display": _format_local(published_at),
                    "content_type": type_key,
                    "content_label": type_label,
                    "opening_line": opening,
                    "permalink": post["permalink"],
                    "likes_delta": int(pair["likes_delta"]),
                    "comments_delta": int(pair["comments_delta"]),
                    "interaction_delta": int(pair["likes_delta"]) + int(pair["comments_delta"]),
                    "basis": pair["basis"],
                    "basis_label": _basis_label(
                        pair["basis"], pair["start"]["_dt"], pair["end"]["_dt"]
                    ),
                    "from_display": _format_local(pair["start"]["_dt"]),
                    "to_display": _format_local(pair["end"]["_dt"]),
                }
            )
            window_starts.append(pair["start"]["_dt"])
            window_ends.append(pair["end"]["_dt"])

    ranked_input.sort(
        key=lambda row: (
            row["interaction_delta"],
            row["likes_delta"],
            row["published_at"] or "",
            row["post_id"],
        ),
        reverse=True,
    )
    ranked_posts = []
    for index, row in enumerate(ranked_input[:RANK_LIMIT], start=1):
        ranked_posts.append({"rank": index, **row})

    published_posts.sort(key=lambda row: row["published_at"] or "", reverse=True)

    type_keys = {row["content_type"] for row in published_posts} | {
        row["content_type"] for row in ranked_input
    }
    content_types: list[dict[str, Any]] = []
    for type_key in sorted(type_keys):
        label = TYPE_LABELS.get(type_key, TYPE_LABELS["unknown"])
        published_of_type = [row for row in published_posts if row["content_type"] == type_key]
        compared = [row for row in ranked_input if row["content_type"] == type_key]
        if compared:
            likes = sum(row["likes_delta"] for row in compared)
            comments = sum(row["comments_delta"] for row in compared)
            interaction = likes + comments
            performance_status = "ok"
            average = interaction / len(compared)
        else:
            likes = None
            comments = None
            interaction = None
            performance_status = "insufficient"
            average = None
        content_types.append(
            {
                "type": type_key,
                "label": label,
                "published_count": len(published_of_type),
                "comparable_posts": len(compared),
                "likes_delta": likes,
                "comments_delta": comments,
                "interaction_delta": interaction,
                "interaction_avg": average,
                "performance_status": performance_status,
            }
        )

    last_fetch = max(fetch_moments) if fetch_moments else None
    if own_block and own_block.get("followers_delta_status") == "ok":
        start_label = own_block.get("followers_from_display")
        end_label = own_block.get("followers_to_display")
    else:
        start_label = _format_local(min(window_starts)) if window_starts else None
        end_label = _format_local(max(window_ends)) if window_ends else None
    if window_starts and window_ends:
        start_label = _format_local(min(window_starts))
        end_label = _format_local(max(window_ends))
    if start_label and end_label:
        measurement_window_notice = (
            f"De beschikbare toename is alleen gemeten tussen {start_label} en {end_label}, "
            "niet over de volledige week."
        )
    else:
        measurement_window_notice = (
            "Er is geen toename over de volledige week gemeten."
        )
    summary = _build_summary(own_block, content_types)
    if measurement_window_notice:
        summary = f"{measurement_window_notice} {summary}"
    _attach_stored_descriptions(published_posts)
    _attach_stored_descriptions(ranked_posts)
    _attach_stored_descriptions(ranked_input)
    topic_groups = _topic_groups(ranked_input)
    snapshot = {
        "version": 1,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_label": f"{_format_day(period_start)} t/m {_format_day(period_end)}",
        "timezone": "Europe/Amsterdam",
        "built_at": moment.astimezone(timezone.utc).isoformat(),
        "built_at_display": _format_local(moment),
        "account_label": account_label,
        "own_account_id": own_account_id,
        "last_fetch_at": last_fetch.astimezone(timezone.utc).isoformat() if last_fetch else None,
        "last_fetch_display": _format_local(last_fetch),
        "ranking_basis": RANKING_BASIS,
        "notes": empty_notes,
        "own": own_block,
        "competitors": competitor_blocks,
        "published_posts": published_posts,
        "ranked_posts": ranked_posts,
        "ranked_total": len(ranked_input),
        "content_types": content_types,
        "measurement_window_notice": measurement_window_notice,
        "topic_groups": topic_groups,
        "summary": summary,
    }
    return snapshot


def _attach_stored_descriptions(posts: list[dict[str, Any]]) -> None:
    """Add saved content descriptions. Does not call AI."""
    from db.content_repository import descriptions_for_posts

    post_ids = [int(post["post_id"]) for post in posts]
    if not post_ids:
        return
    from ai.content_describe import availability_note

    with get_connection() as conn:
        found = descriptions_for_posts(conn, post_ids)
        part_rows = {
            post_id: [
                {
                    "position": int(row["position"]),
                    "role": row["role"],
                    "available": bool(row["available"]),
                }
                for row in conn.execute(
                    """
                    SELECT post_id, position, role, available
                    FROM post_media_items
                    WHERE post_id = ?
                    ORDER BY position, id
                    """,
                    (post_id,),
                ).fetchall()
            ]
            for post_id in post_ids
        }
    for post in posts:
        item = found.get(int(post["post_id"]))
        if item is None:
            parts = part_rows.get(int(post["post_id"])) or []
            post["content_coverage"] = "Niet geanalyseerd"
            post["content_coverage_note"] = (
                availability_note(parts) if parts else "Nog geen contentbeschrijving opgeslagen."
            )
            post["content_description"] = None
            continue
        post["content_coverage"] = item.coverage
        post["content_coverage_note"] = item.coverage_note
        post["content_description"] = item.description


def _topic_groups(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum stored deltas by described topic and content kind. No invented groups."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for post in posts:
        description = post.get("content_description")
        if not isinstance(description, dict):
            continue
        topic = str(description.get("topic") or "").strip()
        kind = str(description.get("content_kind") or "").strip()
        if not topic and not kind:
            continue
        key = (topic or "onderwerp niet beschreven", kind or "soort niet beschreven")
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "topic": key[0],
                "content_kind": key[1],
                "posts": 0,
                "likes_delta": 0,
                "comments_delta": 0,
            }
            buckets[key] = bucket
        bucket["posts"] += 1
        bucket["likes_delta"] += post["likes_delta"]
        bucket["comments_delta"] += post["comments_delta"]
    groups = list(buckets.values())
    for group in groups:
        group["interaction_delta"] = group["likes_delta"] + group["comments_delta"]
    groups.sort(key=lambda row: (row["interaction_delta"], row["posts"]), reverse=True)
    return groups

