"""Manual post and metric fetch for one connected Maaike client.

Opening a screen does not call this module. A failed metric request never
replaces a number that was measured earlier, and a missing metric is not stored as 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from maaike.db import transaction
from maaike.meta_connect import MetaConnectError, MetaRateLimitError, graph_get, graph_version
from maaike.presentation import format_sync_moment
from maaike.repository import (
    _now,
    apply_metric,
    get_client,
    is_verified_link,
    load_page_secret,
    save_fetch_result,
    upsert_synced_post,
)

_MAX_PAGES = 40
_PAGE_LIMIT = 25
# Facebook Graph often rejects large nested field sets with "Please reduce the amount of data".
_FB_PAGE_LIMIT = 10
_FB_PAGE_LIMIT_LEAN = 5
_IG_INSIGHTS = {
    "views": "views",
    "reach": "reach",
    "saves": "saved",
    "shares": "shares",
    "likes": "likes",
    "comments": "comments",
}

_FB_FIELDS_FULL = (
    "id,message,created_time,permalink_url,status_type,full_picture,"
    "attachments{media_type,url,media,subattachments{media_type,url,media}},shares,"
    "likes.summary(true).limit(0),comments.summary(true).limit(0)"
)
# Keeps the metrics the app stores (likes/comments/shares + picture/attachment urls) with less nesting.
_FB_FIELDS_LEAN = (
    "id,message,created_time,permalink_url,status_type,full_picture,"
    "attachments{media_type,url,subattachments{media_type,url}},shares,"
    "likes.summary(true).limit(0),comments.summary(true).limit(0)"
)


@dataclass
class _Run:
    instagram_count: int = 0
    facebook_count: int = 0
    published: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    insight_failures: int = 0
    truncated: bool = False
    rate_limited: str | None = None


def fetch_client_posts(client_id: int, *, get_json=None) -> dict:
    """Fetch Instagram and Facebook posts for one verified client."""
    with transaction() as conn:
        client = get_client(conn, client_id)
        if client is None:
            raise MetaConnectError("This client is not in the list.")
        if not is_verified_link(client):
            raise MetaConnectError(
                "Fetching posts stays locked until this client is connected and verified."
            )
        secret = load_page_secret(conn, client_id)
        page_name = client.meta_page_name or "Facebook"
        ig_name = f"@{client.meta_ig_username}" if client.meta_ig_username else "Instagram"
    if secret is None:
        raise MetaConnectError("No stored page access. Reconnect.")
    page_id, ig_user_id, page_token = secret
    getter = get_json or graph_get
    version = graph_version()
    root = f"https://graph.facebook.com/{version}"
    run = _Run()
    _fetch_instagram(run, getter, root, ig_user_id, ig_name, page_token, client_id)
    if run.rate_limited is None:
        _fetch_facebook(run, getter, root, page_id, page_name, page_token, client_id)
    report = _report(run)
    with transaction() as conn:
        save_fetch_result(
            conn,
            client_id,
            status=report["status"],
            detail=report["message"],
            fetched_at=_now(),
            period_from=report["period_from"],
            period_until=report["period_until"],
            instagram_count=report["instagram_count"],
            facebook_count=report["facebook_count"],
        )
    return report


def _fetch_instagram(run: _Run, get_json, root: str, ig_user_id: str, account: str, token: str, client_id: int) -> None:
    fields = (
        "id,caption,media_type,media_product_type,permalink,timestamp,media_url,"
        "thumbnail_url,like_count,comments_count,children{media_type,media_url}"
    )
    url = f"{root}/{ig_user_id}/media"
    params = {"fields": fields, "limit": str(_PAGE_LIMIT), "access_token": token}
    _consume(run, "instagram", get_json, url, params, token, client_id, account)


def _is_reduce_data_error(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    return "reduce the amount of data" in text or "reduce the amount" in text


def _fetch_facebook(run: _Run, get_json, root: str, page_id: str, account: str, token: str, client_id: int) -> None:
    """Fetch Facebook with leaner pages; retry smaller pages on Meta reduce-data errors."""
    url = f"{root}/{page_id}/published_posts"
    attempts = (
        (_FB_FIELDS_LEAN, _FB_PAGE_LIMIT, "lean"),
        (_FB_FIELDS_LEAN, _FB_PAGE_LIMIT_LEAN, "lean-small"),
        (_FB_FIELDS_FULL, _FB_PAGE_LIMIT_LEAN, "full-small"),
    )
    last_error: MetaConnectError | None = None
    for fields, limit, mode in attempts:
        before = run.facebook_count
        params = {"fields": fields, "limit": str(limit), "access_token": token}
        try:
            _consume(run, "facebook", get_json, url, params, token, client_id, account)
            if mode != "lean" and run.facebook_count > before:
                run.errors.append(
                    f"Facebook: continued with smaller pages ({mode}, limit {limit}) after a reduce-data response."
                )
            return
        except MetaConnectError as exc:
            last_error = exc
            if not _is_reduce_data_error(exc):
                run.errors.append(f"Facebook: {exc}")
                return
            # Drop this attempt's error and retry leaner; keep any posts already stored.
            continue
        except MetaRateLimitError as exc:
            run.rate_limited = str(exc)
            return
    if last_error is not None:
        run.errors.append(f"Facebook: {last_error}")


def _consume(run, platform, get_json, url, params, token, client_id, account) -> None:
    try:
        for page in _pages(run, get_json, url, params, token):
            with transaction() as conn:
                for item in page:
                    if not isinstance(item, dict):
                        continue
                    if platform == "instagram":
                        stored = _store_instagram(run, conn, get_json, client_id, account, token, item)
                        if stored:
                            run.instagram_count += 1
                    else:
                        stored = _store_facebook(run, conn, get_json, client_id, account, token, item)
                        if stored:
                            run.facebook_count += 1
                    if run.rate_limited:
                        return
    except MetaRateLimitError as exc:
        if platform == "facebook":
            raise
        run.rate_limited = str(exc)
    except MetaConnectError as exc:
        # Facebook fetch retries reduce-data with leaner pages.
        if platform == "facebook":
            raise
        run.errors.append(f"Instagram: {exc}")


def _pages(run: _Run, get_json, url: str, params: dict | None, token: str):
    seen: set[str] = set()
    saw_next = False
    for _ in range(_MAX_PAGES):
        if url in seen:
            run.errors.append("Pagination repeated the same address and was stopped.")
            return
        seen.add(url)
        payload = get_json(url, params, secrets=(token,))
        params = None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            run.errors.append("Meta returned no post list.")
            return
        yield data
        paging = payload.get("paging") if isinstance(payload, dict) else None
        next_url = paging.get("next") if isinstance(paging, dict) else None
        if not isinstance(next_url, str) or not next_url.startswith("https://graph.facebook.com/"):
            return
        saw_next = True
        url = next_url
    if saw_next:
        run.truncated = True


def _store_instagram(run, conn, get_json, client_id, account, token, item) -> bool:
    external_id = str(item.get("id") or "").strip()
    published = _iso(item.get("timestamp"))
    if not external_id or not published:
        return False
    run.published.append(published)
    version = graph_version()
    product = str(item.get("media_product_type") or "").strip().upper()
    post_id = upsert_synced_post(
        conn,
        client_id,
        platform="instagram",
        external_id=external_id,
        published_at=published,
        content_kind=_instagram_kind(item),
        permalink=_https(item.get("permalink")),
        account_name=account,
        caption=_text(item.get("caption")),
        media_urls=_media_urls(item),
        synced_at=_now(),
    )
    metrics = "views,reach,saved,shares,likes,comments"
    if product == "STORY":
        metrics = "views,reach,likes,comments,link_clicks"
    insights, failed = _insights(run, get_json, f"https://graph.facebook.com/{version}/{external_id}/insights", token, metrics)
    _apply_instagram(conn, client_id, post_id, item, insights, failed, product, _now())
    _store_instagram_comments(
        run,
        conn,
        get_json,
        client_id,
        post_id,
        external_id,
        token,
        _https(item.get("permalink")),
    )
    return True


def _store_facebook(run, conn, get_json, client_id, account, token, item) -> bool:
    external_id = str(item.get("id") or "").strip()
    published = _iso(item.get("created_time"))
    if not external_id or not published:
        return False
    run.published.append(published)
    version = graph_version()
    post_id = upsert_synced_post(
        conn,
        client_id,
        platform="facebook",
        external_id=external_id,
        published_at=published,
        content_kind=_facebook_kind(item.get("status_type")),
        permalink=_https(item.get("permalink_url")),
        account_name=account,
        caption=_text(item.get("message")),
        media_urls=_facebook_media(item),
        synced_at=_now(),
    )
    root = f"https://graph.facebook.com/{version}/{external_id}/insights"
    views, views_failed = _insights(run, get_json, root, token, "post_media_view")
    clicks, clicks_failed = _insights(run, get_json, root, token, "post_clicks")
    moment = _now()
    _apply_count(conn, client_id, post_id, "likes", _summary_count(item.get("likes")), "likes.summary", moment, False)
    _apply_count(conn, client_id, post_id, "comments", _summary_count(item.get("comments")), "comments.summary", moment, False)
    _apply_count(conn, client_id, post_id, "shares", _share_count(item.get("shares")), "shares.count", moment, False)
    _apply_named(conn, client_id, post_id, "views", views, "post_media_view", views_failed, moment)
    _apply_named(conn, client_id, post_id, "clicks", clicks, "post_clicks", clicks_failed, moment)
    apply_metric(conn, client_id, post_id, "saves", "unsupported", value=None, source_name="", measured_at=moment)
    apply_metric(conn, client_id, post_id, "reach", "unsupported", value=None, source_name="", measured_at=moment)
    _store_facebook_comments(
        run,
        conn,
        get_json,
        client_id,
        post_id,
        external_id,
        token,
        _https(item.get("permalink_url")),
    )
    return True


def _ensure_comments_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            external_id TEXT NOT NULL,
            text TEXT,
            permalink TEXT,
            published_at TEXT,
            author_name TEXT,
            UNIQUE(client_id, platform, external_id),
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(post_id) REFERENCES posts(id)
        )
        """
    )


def _upsert_comment(conn, *, client_id, post_id, platform, external_id, text, permalink, published_at, author_name) -> None:
    _ensure_comments_table(conn)
    conn.execute(
        """
        INSERT INTO comments (
            client_id, post_id, platform, external_id, text, permalink, published_at, author_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id, platform, external_id) DO UPDATE SET
            post_id = excluded.post_id,
            text = excluded.text,
            permalink = excluded.permalink,
            published_at = excluded.published_at,
            author_name = excluded.author_name
        """,
        (client_id, post_id, platform, external_id, text, permalink, published_at, author_name),
    )


def _store_instagram_comments(run, conn, get_json, client_id, post_id, media_id, token, post_permalink) -> None:
    """Store comment bodies for Filter posts. Failures do not wipe existing comments."""
    version = graph_version()
    url = f"https://graph.facebook.com/{version}/{media_id}/comments"
    params = {
        "fields": "id,text,timestamp,username",
        "limit": "25",
        "access_token": token,
    }
    try:
        payload = get_json(url, params, secrets=(token,))
    except MetaRateLimitError as exc:
        run.rate_limited = str(exc)
        return
    except MetaConnectError as exc:
        run.errors.append(f"Instagram comments: {exc}")
        return
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict):
            continue
        external_id = str(item.get("id") or "").strip()
        if not external_id:
            continue
        _upsert_comment(
            conn,
            client_id=client_id,
            post_id=post_id,
            platform="instagram",
            external_id=external_id,
            text=_text(item.get("text")),
            permalink=post_permalink,
            published_at=_iso(item.get("timestamp")),
            author_name=_text(item.get("username")),
        )


def _store_facebook_comments(run, conn, get_json, client_id, post_id, post_external_id, token, post_permalink) -> None:
    version = graph_version()
    url = f"https://graph.facebook.com/{version}/{post_external_id}/comments"
    params = {
        "fields": "id,message,created_time,from",
        "limit": "25",
        "access_token": token,
    }
    try:
        payload = get_json(url, params, secrets=(token,))
    except MetaRateLimitError as exc:
        run.rate_limited = str(exc)
        return
    except MetaConnectError as exc:
        run.errors.append(f"Facebook comments: {exc}")
        return
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict):
            continue
        external_id = str(item.get("id") or "").strip()
        if not external_id:
            continue
        author = item.get("from") if isinstance(item.get("from"), dict) else {}
        _upsert_comment(
            conn,
            client_id=client_id,
            post_id=post_id,
            platform="facebook",
            external_id=external_id,
            text=_text(item.get("message")),
            permalink=post_permalink,
            published_at=_iso(item.get("created_time")),
            author_name=_text(author.get("name")),
        )


def _insights(run, get_json, url: str, token: str, metric: str) -> tuple[dict[str, int] | None, bool]:
    if run.rate_limited:
        return None, True
    try:
        payload = get_json(
            url,
            {"metric": metric, "period": "lifetime", "access_token": token},
            secrets=(token,),
        )
    except MetaRateLimitError as exc:
        run.rate_limited = str(exc)
        run.insight_failures += 1
        return None, True
    except MetaConnectError as exc:
        if exc.code == 100:
            return {}, False
        run.insight_failures += 1
        run.errors.append("An insights request failed. Earlier measured figures were kept.")
        return None, True
    return _insight_map(payload), False


def _apply_instagram(conn, client_id, post_id, item, insights, failed, product, moment) -> None:
    parsed = insights or {}
    for metric, source in _IG_INSIGHTS.items():
        if failed:
            apply_metric(conn, client_id, post_id, metric, "failed", value=None, source_name=source, measured_at=moment)
            continue
        if source in parsed:
            apply_metric(
                conn, client_id, post_id, metric, "measured",
                value=parsed[source], source_name=source, measured_at=moment,
            )
            continue
        fallback = _instagram_fallback(metric, item)
        if fallback is not None:
            apply_metric(
                conn, client_id, post_id, metric, "measured",
                value=fallback, source_name=_fallback_source(metric), measured_at=moment,
            )
        else:
            apply_metric(conn, client_id, post_id, metric, "unavailable", value=None, source_name=source, measured_at=moment)
    if product == "STORY" and not failed and "link_clicks" in parsed:
        apply_metric(
            conn, client_id, post_id, "clicks", "measured",
            value=parsed["link_clicks"], source_name="link_clicks", measured_at=moment,
        )
    elif product == "STORY" and failed:
        apply_metric(conn, client_id, post_id, "clicks", "failed", value=None, source_name="link_clicks", measured_at=moment)
    elif product == "STORY":
        apply_metric(conn, client_id, post_id, "clicks", "unavailable", value=None, source_name="link_clicks", measured_at=moment)
    else:
        apply_metric(conn, client_id, post_id, "clicks", "unsupported", value=None, source_name="", measured_at=moment)


def _apply_named(conn, client_id, post_id, metric, parsed, source, failed, moment) -> None:
    if failed or parsed is None:
        apply_metric(conn, client_id, post_id, metric, "failed", value=None, source_name=source, measured_at=moment)
        return
    if source in parsed:
        apply_metric(conn, client_id, post_id, metric, "measured", value=parsed[source], source_name=source, measured_at=moment)
        return
    if parsed == {} and source == "post_clicks":
        apply_metric(conn, client_id, post_id, metric, "unsupported", value=None, source_name=source, measured_at=moment)
        return
    apply_metric(conn, client_id, post_id, metric, "unavailable", value=None, source_name=source, measured_at=moment)


def _apply_count(conn, client_id, post_id, metric, value, source, moment, failed) -> None:
    if failed:
        apply_metric(conn, client_id, post_id, metric, "failed", value=None, source_name=source, measured_at=moment)
    elif value is None:
        apply_metric(conn, client_id, post_id, metric, "unavailable", value=None, source_name=source, measured_at=moment)
    else:
        apply_metric(conn, client_id, post_id, metric, "measured", value=value, source_name=source, measured_at=moment)


def _instagram_fallback(metric: str, item: dict) -> int | None:
    if metric == "likes":
        return _number(item.get("like_count"))
    if metric == "comments":
        return _number(item.get("comments_count"))
    return None


def _fallback_source(metric: str) -> str:
    if metric == "likes":
        return "like_count"
    if metric == "comments":
        return "comments_count"
    return metric


def _report(run: _Run) -> dict:
    period_from = min(run.published) if run.published else None
    period_until = max(run.published) if run.published else None
    counts = f"Instagram: {run.instagram_count} posts. Facebook: {run.facebook_count} posts."
    if period_from and period_until:
        period = (
            f" Period from {format_sync_moment(period_from)} to {format_sync_moment(period_until)}."
        )
    else:
        period = " There is no publication period because no posts were fetched."
    extra = ""
    if run.truncated:
        extra += " There are more posts than this run fetches. Fetch again later."
    if run.insight_failures:
        extra += " Insights failed for some posts. Earlier measured figures were kept."
    if run.errors:
        extra += " " + " ".join(dict.fromkeys(run.errors))
    if run.rate_limited:
        status = "partial" if run.instagram_count or run.facebook_count else "failed"
        message = f"{run.rate_limited} {counts}{period}{extra}"
    elif run.errors or run.insight_failures or run.truncated:
        status = "partial" if run.instagram_count or run.facebook_count else "failed"
        message = f"Fetch partly succeeded. {counts}{period}{extra}"
    else:
        status = "complete"
        message = f"Fetch fully succeeded. {counts}{period}"
    return {
        "status": status,
        "message": " ".join(message.split()),
        "instagram_count": run.instagram_count,
        "facebook_count": run.facebook_count,
        "period_from": period_from,
        "period_until": period_until,
    }


def _insight_map(payload: dict) -> dict[str, int]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return {}
    found: dict[str, int] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = _insight_value(item)
        if isinstance(name, str) and name and value is not None:
            found[name] = value
    return found


def _insight_value(item: dict) -> int | None:
    total = item.get("total_value")
    if isinstance(total, dict):
        number = _number(total.get("value"))
        if number is not None:
            return number
    values = item.get("values")
    if isinstance(values, list) and values and isinstance(values[-1], dict):
        return _number(values[-1].get("value"))
    return None


def _summary_count(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    summary = value.get("summary")
    if not isinstance(summary, dict):
        return None
    return _number(summary.get("total_count"))


def _share_count(value: object) -> int | None:
    if isinstance(value, dict):
        return _number(value.get("count"))
    return _number(value)


def _number(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _iso(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    return text or None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned[:5000] or None


def _https(value: object) -> str | None:
    if isinstance(value, str) and value.startswith("https://"):
        return value
    return None


def _media_urls(item: dict) -> str | None:
    found: list[str] = []
    _push_url(found, item.get("media_url"))
    _push_url(found, item.get("thumbnail_url"))
    children = item.get("children")
    data = children.get("data") if isinstance(children, dict) else None
    if isinstance(data, list):
        for child in data:
            if isinstance(child, dict):
                _push_url(found, child.get("media_url"))
    return "\n".join(found[:8]) or None


def _facebook_media(item: dict) -> str | None:
    found: list[str] = []
    _push_url(found, item.get("full_picture"))
    attachments = item.get("attachments")
    data = attachments.get("data") if isinstance(attachments, dict) else None
    if isinstance(data, list):
        for attachment in data:
            if not isinstance(attachment, dict):
                continue
            _push_url(found, attachment.get("url"))
            media = attachment.get("media")
            if isinstance(media, dict):
                image = media.get("image")
                if isinstance(image, dict):
                    _push_url(found, image.get("src"))
            sub = attachment.get("subattachments")
            nested = sub.get("data") if isinstance(sub, dict) else None
            if isinstance(nested, list):
                for child in nested:
                    if isinstance(child, dict):
                        _push_url(found, child.get("url"))
    return "\n".join(found[:8]) or None


def _push_url(found: list[str], value: object) -> None:
    if isinstance(value, str) and value.startswith("https://") and value not in found:
        found.append(value)


def _instagram_kind(item: dict) -> str | None:
    product = str(item.get("media_product_type") or "").strip().upper()
    media = str(item.get("media_type") or "").strip().upper()
    if product == "REELS":
        return "reel"
    if product == "STORY":
        return "story"
    if media == "CAROUSEL_ALBUM":
        return "carousel_album"
    if media == "VIDEO":
        return "video"
    if media == "IMAGE":
        return "image"
    return None


def _facebook_kind(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"added_video", "added_videos"}:
        return "video"
    if text in {"added_photos", "added_photo"}:
        return "photo"
    if text == "shared_story":
        return "share"
    return text or "post"
