"""Hourly competitor Business Discovery crawls — prefer off-hours (Europe/Amsterdam).

Why competitors stayed empty: they were only listed in preferences; crawl ran only
when someone manually clicked Link+crawl. Multi-account refresh was disabled.

This scheduler:
- links every saved competitor as a crawl account
- every hour, if outside work hours, fetches one stale competitor (round-robin)
- skips Meta calls Mon–Fri 08:00–18:00 so daytime quota stays free for Maaike analyses
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
WORK_START_HOUR = 8
WORK_END_HOUR = 18  # exclusive: crawls allowed from 18:00 onward
STALE_AFTER_HOURS = 20  # prefer re-crawl after ~a day

_scheduler = None
_started = False
_start_lock = threading.Lock()
_job_lock = threading.Lock()
_last_tick: dict[str, Any] = {
    "at": None,
    "action": "never",
    "detail": "Scheduler not started yet.",
    "client_id": None,
    "username": None,
}


def amsterdam_now() -> datetime:
    return datetime.now(tz=AMSTERDAM)


def is_off_hours(now: datetime | None = None) -> bool:
    """True outside Mon–Fri 08:00–18:00 Europe/Amsterdam (and all weekend)."""
    now = now or amsterdam_now()
    if now.weekday() >= 5:
        return True
    return now.hour < WORK_START_HOUR or now.hour >= WORK_END_HOUR


def schedule_status() -> dict[str, Any]:
    now = amsterdam_now()
    off = is_off_hours(now)
    return {
        "enabled": _started,
        "timezone": "Europe/Amsterdam",
        "work_hours": f"ma–vr {WORK_START_HOUR:02d}:00–{WORK_END_HOUR:02d}:00",
        "crawl_window": "buiten werktijd + weekenden (elk uur één concurrent)",
        "now_local": now.isoformat(),
        "currently_off_hours": off,
        "next_action": (
            "Dit uur: één stale concurrent crawlen"
            if off
            else "Wacht tot na 18:00 (of weekend) — overdag geen competitor-crawl"
        ),
        "last_tick": dict(_last_tick),
    }


def _set_tick(**kwargs: Any) -> None:
    _last_tick.update(kwargs)
    _last_tick["at"] = amsterdam_now().isoformat()


def ensure_competitors_linked(conn, client_id: int) -> list[str]:
    """Make sure every comparison competitor has a crawl-account row."""
    from maaike.account_crawl import link_crawl_account, normalize_username
    from maaike.comparison_service import ensure_tables as ensure_comparison_tables

    ensure_comparison_tables(conn)
    row = conn.execute(
        "SELECT competitors_json FROM client_comparison_preferences WHERE client_id = ?",
        (client_id,),
    ).fetchone()
    if not row:
        return []
    import json

    try:
        names = json.loads(row["competitors_json"] or "[]")
    except json.JSONDecodeError:
        names = []
    linked = []
    for raw in names:
        clean = normalize_username(str(raw))
        if not clean:
            continue
        link_crawl_account(conn, client_id, clean)
        linked.append(clean)
    return linked


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=AMSTERDAM)
    return dt.astimezone(AMSTERDAM)


def pick_next_competitor(conn) -> dict[str, Any] | None:
    """Oldest / never-crawled competitor crawl account across clients with Meta."""
    import json

    from maaike.account_crawl import ensure_crawl_tables, normalize_username
    from maaike.repository import get_client, is_verified_link

    ensure_crawl_tables(conn)
    pref_rows = conn.execute(
        "SELECT client_id, competitors_json FROM client_comparison_preferences"
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    for pref in pref_rows:
        client_id = int(pref["client_id"])
        ensure_competitors_linked(conn, client_id)
        try:
            names = {
                normalize_username(str(x))
                for x in json.loads(pref["competitors_json"] or "[]")
                if str(x).strip()
            }
        except json.JSONDecodeError:
            names = set()
        if not names:
            continue
        client = get_client(conn, client_id)
        if client is None or not is_verified_link(client):
            continue
        for name in names:
            row = conn.execute(
                """
                SELECT username, last_crawled_at, last_crawl_status
                FROM client_crawl_accounts
                WHERE client_id = ? AND username = ? COLLATE NOCASE
                """,
                (client_id, name),
            ).fetchone()
            if row is None:
                continue
            candidates.append(
                {
                    "client_id": client_id,
                    "username": str(row["username"]),
                    "last_crawled_at": row["last_crawled_at"],
                    "last_crawl_status": row["last_crawl_status"],
                }
            )

    now = amsterdam_now()
    stale_before = now - timedelta(hours=STALE_AFTER_HOURS)

    def sort_key(item: dict[str, Any]) -> tuple:
        last = _parse_ts(item.get("last_crawled_at"))
        never = last is None
        return (0 if never else 1, last or datetime.min.replace(tzinfo=AMSTERDAM), item["username"])

    candidates.sort(key=sort_key)
    for item in candidates:
        last = _parse_ts(item.get("last_crawled_at"))
        if (
            last is not None
            and last > stale_before
            and item.get("last_crawl_status") == "completed"
        ):
            continue
        return item
    return None


def crawl_one_competitor(
    conn,
    client_id: int,
    username: str,
    *,
    max_pages: int = 1,
) -> dict[str, Any]:
    from maaike.account_crawl import crawl_account

    return crawl_account(conn, client_id, username, max_pages=max_pages, page_limit=25)


def run_hourly_competitor_tick(*, force: bool = False) -> dict[str, Any]:
    """Called every hour. Crawls at most one competitor unless force=True during work hours."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"skipped": True, "reason": "pytest"}
    if not _job_lock.acquire(blocking=False):
        _set_tick(action="skipped", detail="Vorige competitor-crawl loopt nog.")
        return {"skipped": True, "reason": "busy"}

    try:
        now = amsterdam_now()
        if not force and not is_off_hours(now):
            detail = (
                f"Werktijd ({WORK_START_HOUR:02d}:00–{WORK_END_HOUR:02d}:00) — "
                "geen Meta competitor-crawl; analyses houden voorrang."
            )
            logger.info(detail)
            _set_tick(action="skipped_work_hours", detail=detail, client_id=None, username=None)
            return {"skipped": True, "reason": "work_hours", "detail": detail}

        from maaike.db import transaction

        with transaction() as conn:
            nxt = pick_next_competitor(conn)
            if nxt is None:
                detail = "Geen stale concurrenten (alles recent gecrawld of geen Meta-link)."
                _set_tick(action="idle", detail=detail, client_id=None, username=None)
                return {"skipped": True, "reason": "nothing_due", "detail": detail}

            client_id = nxt["client_id"]
            username = nxt["username"]
            try:
                result = crawl_one_competitor(conn, client_id, username, max_pages=1)
            except ValueError as exc:
                detail = str(exc)
                logger.warning("Competitor crawl @%s client=%s: %s", username, client_id, detail)
                _set_tick(
                    action="failed",
                    detail=detail,
                    client_id=client_id,
                    username=username,
                )
                return {
                    "skipped": False,
                    "ok": False,
                    "client_id": client_id,
                    "username": username,
                    "error": detail,
                }

            detail = (
                f"@{username} · {result.get('status')} · "
                f"{result.get('posts_saved', 0)} posts"
            )
            logger.info("Competitor hourly crawl: client=%s %s", client_id, detail)
            _set_tick(
                action="crawled",
                detail=detail,
                client_id=client_id,
                username=username,
            )
            return {
                "skipped": False,
                "ok": True,
                "client_id": client_id,
                "username": username,
                "result": {
                    "status": result.get("status"),
                    "posts_saved": result.get("posts_saved"),
                    "fetched_at": result.get("fetched_at"),
                },
            }
    except Exception as exc:
        logger.exception("Competitor hourly tick failed")
        _set_tick(action="error", detail=str(exc), client_id=None, username=None)
        return {"skipped": False, "ok": False, "error": str(exc)}
    finally:
        _job_lock.release()


def refresh_client_competitors(conn, client_id: int, *, max_accounts: int = 3) -> dict[str, Any]:
    """Manual refresh: crawl up to N stale competitors for one client now."""
    from maaike.account_crawl import crawl_account
    from maaike.repository import get_client, is_verified_link

    client = get_client(conn, client_id)
    if client is None:
        raise ValueError("Client not found.")
    if not is_verified_link(client):
        raise ValueError("Connect Meta first — Business Discovery needs the client's IG host.")

    linked = ensure_competitors_linked(conn, client_id)
    if not linked:
        return {
            "client_id": client_id,
            "crawled": [],
            "note": "No competitors on the list yet.",
        }

    rows = conn.execute(
        """
        SELECT username, last_crawled_at, last_crawl_status
        FROM client_crawl_accounts
        WHERE client_id = ?
          AND lower(username) IN ({placeholders})
        ORDER BY
            CASE WHEN last_crawled_at IS NULL OR last_crawled_at = '' THEN 0 ELSE 1 END,
            last_crawled_at ASC
        """.format(placeholders=",".join("?" * len(linked))),
        (client_id, *[n.lower() for n in linked]),
    ).fetchall()

    crawled = []
    errors = []
    for row in rows[: max(1, max_accounts)]:
        username = str(row["username"])
        try:
            result = crawl_account(conn, client_id, username, max_pages=1, page_limit=25)
            crawled.append(
                {
                    "username": username,
                    "status": result.get("status"),
                    "posts_saved": result.get("posts_saved"),
                }
            )
        except ValueError as exc:
            errors.append({"username": username, "error": str(exc)})

    return {
        "client_id": client_id,
        "crawled": crawled,
        "errors": errors,
        "linked": linked,
        "note": (
            "Handmatige refresh (max. {n} accounts). "
            "Automatisch: elk uur buiten werktijd één concurrent."
        ).format(n=max_accounts),
        "schedule": schedule_status(),
    }


def start_competitor_scheduler() -> None:
    """Start hourly APScheduler job in the Maaike web process."""
    global _scheduler, _started
    if os.environ.get("DISABLE_COMPETITOR_SCHEDULER") == "1":
        logger.info("Competitor scheduler disabled via DISABLE_COMPETITOR_SCHEDULER=1")
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _start_lock:
        if _started:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning("APScheduler missing — competitor hourly crawls disabled.")
            return

        scheduler = BackgroundScheduler(timezone=AMSTERDAM)
        scheduler.add_job(
            run_hourly_competitor_tick,
            CronTrigger(minute=12, timezone=AMSTERDAM),
            id="maaike_competitor_hourly",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        _scheduler = scheduler
        _started = True
        _set_tick(
            action="started",
            detail="Uurlijkse competitor-crawl gepland (minuut :12, alleen buiten werktijd).",
        )
        logger.info(
            "Competitor scheduler started (hourly at :12 Europe/Amsterdam, off-hours only)."
        )
        # Catch-up once if we boot during off-hours
        threading.Thread(
            target=lambda: run_hourly_competitor_tick(force=False),
            name="competitor-catchup",
            daemon=True,
        ).start()
