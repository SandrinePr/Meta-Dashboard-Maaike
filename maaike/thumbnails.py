"""Same-origin cover/media thumbnails for Maaike (Render Free safe).

Meta CDN URLs expire and often return HTTP 403 in browsers. Cards and Logs must
use local JPEG files served from ``/api/clients/{id}/posts/{id}/cover``.

Cache keys use ``{platform}_{external_id}`` so files survive post-id reimports.
On miss: try stored CDN URLs, then Graph refresh when a page token exists.
Seed pack ``maaike/seed/hamster_thumbs.tar.gz`` restores covers after Free wipes.
"""

from __future__ import annotations

import io
import logging
import os
import tarfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image

from maaike.config import project_root
from maaike.feed import parse_media_urls
from maaike.repository import load_page_secret

logger = logging.getLogger(__name__)

MAX_SIDE = 480
JPEG_QUALITY = 70
FAIL_COOLDOWN_SECONDS = 600
_DOWNLOAD_TIMEOUT = 25
_MAX_SLIDES = 8

SEED_REL = Path("maaike") / "seed" / "hamster_thumbs.tar.gz"

_session_local = threading.local()
_in_progress: set[str] = set()
_in_progress_lock = threading.Lock()
_failed_until: dict[str, float] = {}
_seed_lock = threading.Lock()
_seed_applied = False


def thumb_root() -> Path:
    override = (os.environ.get("MAAIKE_THUMB_DIR") or "").strip()
    if override:
        return Path(override)
    # Prefer persistent disk path when Render mounts one; else local data dir.
    for candidate in (
        Path("/var/data/maaike_thumbs"),
        project_root() / "data" / "maaike_thumbs",
        Path("/tmp/maaike_thumbs"),
    ):
        try:
            if candidate.parent.exists() or str(candidate).startswith("/tmp"):
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
        except OSError:
            continue
    path = project_root() / "data" / "maaike_thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def seed_thumbs_path() -> Path:
    return project_root() / SEED_REL


def cache_key(platform: str, external_id: str) -> str:
    plat = (platform or "unknown").strip().lower().replace(" ", "_")
    ext = (external_id or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in ext)[:120]
    return f"{plat}_{safe}"


def cover_path(platform: str, external_id: str) -> Path:
    return thumb_root() / f"{cache_key(platform, external_id)}.jpg"


def slide_path(platform: str, external_id: str, index: int) -> Path:
    return thumb_root() / f"{cache_key(platform, external_id)}_s{int(index)}.jpg"


def cover_api_path(client_id: int, post_id: int) -> str:
    return f"/api/clients/{int(client_id)}/posts/{int(post_id)}/cover"


def media_api_path(client_id: int, post_id: int, index: int) -> str:
    return f"/api/clients/{int(client_id)}/posts/{int(post_id)}/media-file/{int(index)}"


def ensure_seed_thumbs_extracted() -> dict[str, Any]:
    """Extract tracked cover JPEGs once per process when the thumb dir is empty."""
    global _seed_applied
    with _seed_lock:
        if _seed_applied:
            return {"extracted": False, "reason": "already_applied"}
        root = thumb_root()
        existing = list(root.glob("*.jpg"))
        if existing:
            _seed_applied = True
            return {"extracted": False, "reason": "thumbs_present", "count": len(existing)}
        seed = seed_thumbs_path()
        if not seed.is_file():
            return {
                "extracted": False,
                "reason": "seed_missing",
                "path": str(SEED_REL).replace("\\", "/"),
            }
        root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(seed, "r:gz") as archive:
            archive.extractall(root)
        _seed_applied = True
        count = len(list(root.glob("*.jpg")))
        return {
            "extracted": True,
            "reason": "hamster_thumbs_applied",
            "path": str(SEED_REL).replace("\\", "/"),
            "count": count,
        }


def _http_session() -> requests.Session:
    session = getattr(_session_local, "session", None)
    if session is None:
        session = requests.Session()
        _session_local.session = session
    return session


def _is_displayable_image_url(value: str | None) -> bool:
    if not value or not value.startswith("https://"):
        return False
    path = urlparse(value).path.lower()
    if path.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return False
    host = (urlparse(value).hostname or "").lower()
    if host in {
        "facebook.com",
        "www.facebook.com",
        "instagram.com",
        "www.instagram.com",
        "fb.com",
        "www.fb.com",
    }:
        return False
    return True


def save_compressed_jpeg(content: bytes, target: Path) -> bool:
    try:
        image = Image.open(io.BytesIO(content))
        image = image.convert("RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp.jpg")
        image.save(tmp, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        tmp.replace(target)
        return target.exists() and target.stat().st_size > 0
    except Exception:
        return False


def download_image_bytes(url: str, *, session: requests.Session | None = None) -> bytes | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.instagram.com/",
    }
    client = session or _http_session()
    try:
        response = client.get(url, timeout=_DOWNLOAD_TIMEOUT, headers=headers)
    except requests.RequestException:
        return None
    if response.status_code != 200 or not response.content:
        return None
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "image" not in content_type and not url.lower().split("?", 1)[0].endswith(
        (".jpg", ".jpeg", ".png", ".webp")
    ):
        if len(response.content) < 200:
            return None
    return response.content


def _candidate_urls_from_post(row: Any) -> list[str]:
    urls: list[str] = []
    media_urls = row["media_urls"] if "media_urls" in row.keys() else None
    for item in parse_media_urls(media_urls):
        if item["kind"] == "image" and _is_displayable_image_url(item["url"]):
            urls.append(item["url"])
    return urls


def _discovery_username(row: Any) -> str | None:
    """Username for Business Discovery refresh (competitors)."""
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    origin = ""
    if "source_origin" in keys:
        origin = str(row["source_origin"] or "")
    if origin.startswith("business_discovery:"):
        return origin.split(":", 1)[1].strip().lstrip("@") or None
    account = ""
    if "account_name" in keys:
        account = str(row["account_name"] or "").strip()
    if account.startswith("@") and "redrock" not in account.lower():
        return account.lstrip("@") or None
    return None


def _graph_version() -> str:
    return (os.environ.get("MAAIKE_META_GRAPH_VERSION") or "v21.0").strip() or "v21.0"


def _push_url(found: list[str], value: object) -> None:
    if isinstance(value, str) and _is_displayable_image_url(value) and value not in found:
        found.append(value)


def _urls_from_ig_media_payload(payload: dict) -> list[str]:
    found: list[str] = []
    media_type = str(payload.get("media_type") or "").upper()
    product = str(payload.get("media_product_type") or "").upper()
    if media_type in {"VIDEO", "REELS"} or "REEL" in product:
        _push_url(found, payload.get("thumbnail_url"))
        _push_url(found, payload.get("media_url"))
    else:
        _push_url(found, payload.get("media_url"))
        _push_url(found, payload.get("thumbnail_url"))
    children = payload.get("children")
    data = children.get("data") if isinstance(children, dict) else None
    if isinstance(data, list):
        for child in data:
            if not isinstance(child, dict):
                continue
            child_type = str(child.get("media_type") or "").upper()
            if child_type == "VIDEO":
                _push_url(found, child.get("thumbnail_url"))
            else:
                _push_url(found, child.get("media_url"))
                _push_url(found, child.get("thumbnail_url"))
    return found


def refresh_image_urls_via_discovery(
    *,
    host_ig_user_id: str,
    username: str,
    external_id: str,
    page_token: str,
    max_pages: int = 6,
) -> list[str]:
    """Find one competitor media id via Business Discovery and return fresh image URLs."""
    if not host_ig_user_id or not username or not external_id or not page_token:
        return []
    session = _http_session()
    version = _graph_version()
    clean = username.strip().lstrip("@")
    after: str | None = None
    try:
        for _ in range(max(1, max_pages)):
            media_q = f"media.limit(50)"
            if after:
                media_q += f".after({after})"
            media_q += "{id,media_type,media_product_type,media_url,thumbnail_url}"
            fields = f"business_discovery.username({clean}){{{media_q}}}"
            response = session.get(
                f"https://graph.facebook.com/{version}/{host_ig_user_id}",
                params={"fields": fields, "access_token": page_token},
                timeout=_DOWNLOAD_TIMEOUT,
            )
            if response.status_code != 200:
                return []
            payload = response.json()
            discovery = payload.get("business_discovery") if isinstance(payload, dict) else None
            if not isinstance(discovery, dict):
                return []
            block = discovery.get("media") if isinstance(discovery.get("media"), dict) else {}
            items = block.get("data") if isinstance(block, dict) else []
            if not isinstance(items, list):
                items = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("id") or "") != str(external_id):
                    continue
                return _urls_from_ig_media_payload(item)[:_MAX_SLIDES]
            paging = block.get("paging") if isinstance(block, dict) else None
            cursors = paging.get("cursors") if isinstance(paging, dict) else None
            after = cursors.get("after") if isinstance(cursors, dict) else None
            if not after:
                break
    except requests.RequestException:
        return []
    return []


def refresh_image_urls_via_graph(
    *,
    platform: str,
    external_id: str,
    page_token: str,
    host_ig_user_id: str | None = None,
    discovery_username: str | None = None,
) -> list[str]:
    """Return fresh image URLs for cover + carousel slides via Graph."""
    if not external_id or not page_token:
        return []
    plat = (platform or "").strip().lower()
    session = _http_session()
    version = _graph_version()
    found: list[str] = []

    try:
        if plat == "instagram":
            fields = (
                "id,media_type,media_product_type,media_url,thumbnail_url,"
                "children{media_type,media_url,thumbnail_url}"
            )
            response = session.get(
                f"https://graph.facebook.com/{version}/{external_id}",
                params={"fields": fields, "access_token": page_token},
                timeout=_DOWNLOAD_TIMEOUT,
            )
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict) and not payload.get("error"):
                    found = _urls_from_ig_media_payload(payload)
            if not found and host_ig_user_id and discovery_username:
                found = refresh_image_urls_via_discovery(
                    host_ig_user_id=host_ig_user_id,
                    username=discovery_username,
                    external_id=external_id,
                    page_token=page_token,
                )
        elif plat == "facebook":
            fields = "id,full_picture,attachments{media,subattachments{media}}"
            response = session.get(
                f"https://graph.facebook.com/{version}/{external_id}",
                params={"fields": fields, "access_token": page_token},
                timeout=_DOWNLOAD_TIMEOUT,
            )
            if response.status_code != 200:
                return []
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("error"):
                return []
            _push_url(found, payload.get("full_picture"))
            attachments = payload.get("attachments")
            data = attachments.get("data") if isinstance(attachments, dict) else None
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    media = item.get("media")
                    if isinstance(media, dict):
                        image = media.get("image")
                        if isinstance(image, dict):
                            _push_url(found, image.get("src"))
                    sub = item.get("subattachments")
                    nested = sub.get("data") if isinstance(sub, dict) else None
                    if isinstance(nested, list):
                        for child in nested:
                            if not isinstance(child, dict):
                                continue
                            media = child.get("media")
                            if isinstance(media, dict):
                                image = media.get("image")
                                if isinstance(image, dict):
                                    _push_url(found, image.get("src"))
        else:
            return []
    except requests.RequestException:
        return []
    return found[:_MAX_SLIDES]


def _persist_refreshed_media_urls(conn, post_id: int, urls: list[str]) -> None:
    if not urls:
        return
    # Keep first image URLs only; never store video bytes paths here.
    lines = [u for u in urls if _is_displayable_image_url(u)][:_MAX_SLIDES]
    if not lines:
        return
    conn.execute(
        "UPDATE posts SET media_urls = ? WHERE id = ?",
        ("\n".join(lines), int(post_id)),
    )


def _load_post_row(conn, client_id: int, post_id: int) -> Any | None:
    return conn.execute(
        """
        SELECT id, client_id, platform, external_id, content_kind, media_urls,
               account_name, source_origin
        FROM posts
        WHERE id = ? AND client_id = ?
        """,
        (int(post_id), int(client_id)),
    ).fetchone()


def write_cover_from_bytes(platform: str, external_id: str, content: bytes) -> Path | None:
    """Store a cover JPEG for an external Meta id (used by seed builder)."""
    if not external_id or not content:
        return None
    target = cover_path(platform, external_id)
    if target.is_file() and target.stat().st_size > 0:
        return target
    if save_compressed_jpeg(content, target):
        return target
    return None


def ensure_cover_file(conn, client_id: int, post_id: int) -> Path | None:
    """Return a local cover JPEG, downloading once on miss when possible."""
    ensure_seed_thumbs_extracted()
    row = _load_post_row(conn, client_id, post_id)
    if row is None:
        return None
    platform = str(row["platform"] or "")
    external_id = str(row["external_id"] or "")
    if not external_id:
        return None
    key = cache_key(platform, external_id)
    target = cover_path(platform, external_id)
    if target.is_file() and target.stat().st_size > 0:
        return target

    now = time.monotonic()
    if _failed_until.get(key, 0.0) > now:
        return None

    with _in_progress_lock:
        if key in _in_progress:
            return None
        _in_progress.add(key)
    try:
        if target.is_file() and target.stat().st_size > 0:
            return target

        session = _http_session()
        content: bytes | None = None
        for url in _candidate_urls_from_post(row):
            content = download_image_bytes(url, session=session)
            if content:
                break

        refreshed: list[str] = []
        if not content:
            secret = load_page_secret(conn, client_id)
            if secret is not None:
                _page_id, ig_id, page_token = secret
                refreshed = refresh_image_urls_via_graph(
                    platform=platform,
                    external_id=external_id,
                    page_token=page_token,
                    host_ig_user_id=ig_id,
                    discovery_username=_discovery_username(row),
                )
                for url in refreshed:
                    content = download_image_bytes(url, session=session)
                    if content:
                        break
                if refreshed:
                    try:
                        _persist_refreshed_media_urls(conn, int(row["id"]), refreshed)
                    except Exception:
                        logger.exception("Could not persist refreshed media URLs for post %s", post_id)

        if content and save_compressed_jpeg(content, target):
            # Also store first slide alias for carousel index 0.
            slide0 = slide_path(platform, external_id, 0)
            if not slide0.exists():
                try:
                    slide0.write_bytes(target.read_bytes())
                except OSError:
                    pass
            if refreshed:
                _cache_extra_slides(platform, external_id, refreshed[1:], session)
            _failed_until.pop(key, None)
            return target

        _failed_until[key] = now + FAIL_COOLDOWN_SECONDS
        return None
    except Exception:
        logger.exception("Cover cache failed for post %s", post_id)
        _failed_until[key] = time.monotonic() + FAIL_COOLDOWN_SECONDS
        return None
    finally:
        with _in_progress_lock:
            _in_progress.discard(key)


def _cache_extra_slides(
    platform: str,
    external_id: str,
    urls: list[str],
    session: requests.Session,
) -> None:
    for index, url in enumerate(urls, start=1):
        if index >= _MAX_SLIDES:
            break
        target = slide_path(platform, external_id, index)
        if target.is_file() and target.stat().st_size > 0:
            continue
        content = download_image_bytes(url, session=session)
        if content:
            save_compressed_jpeg(content, target)


def ensure_slide_file(conn, client_id: int, post_id: int, index: int) -> Path | None:
    """Return JPEG for carousel slide index (0-based). Falls back to cover for 0."""
    ensure_seed_thumbs_extracted()
    row = _load_post_row(conn, client_id, post_id)
    if row is None:
        return None
    platform = str(row["platform"] or "")
    external_id = str(row["external_id"] or "")
    if not external_id:
        return None
    idx = max(0, int(index))
    if idx == 0:
        cover = ensure_cover_file(conn, client_id, post_id)
        if cover is not None:
            return cover
    target = slide_path(platform, external_id, idx)
    if target.is_file() and target.stat().st_size > 0:
        return target

    # Try stored CDN line for this index.
    candidates = _candidate_urls_from_post(row)
    session = _http_session()
    if idx < len(candidates):
        content = download_image_bytes(candidates[idx], session=session)
        if content and save_compressed_jpeg(content, target):
            return target

    secret = load_page_secret(conn, client_id)
    if secret is None:
        return ensure_cover_file(conn, client_id, post_id) if idx == 0 else None
    _page_id, ig_id, page_token = secret
    refreshed = refresh_image_urls_via_graph(
        platform=platform,
        external_id=external_id,
        page_token=page_token,
        host_ig_user_id=ig_id,
        discovery_username=_discovery_username(row),
    )
    if refreshed:
        try:
            _persist_refreshed_media_urls(conn, int(row["id"]), refreshed)
        except Exception:
            pass
        if idx < len(refreshed):
            content = download_image_bytes(refreshed[idx], session=session)
            if content and save_compressed_jpeg(content, target):
                if idx == 0:
                    cover = cover_path(platform, external_id)
                    if not cover.exists():
                        try:
                            cover.write_bytes(target.read_bytes())
                        except OSError:
                            pass
                return target
        _cache_extra_slides(platform, external_id, refreshed[1:], session)
        if target.is_file() and target.stat().st_size > 0:
            return target
    return ensure_cover_file(conn, client_id, post_id) if idx == 0 else None


def rewrite_feed_media(
    media: list[dict[str, str]],
    *,
    client_id: int,
    post_id: int,
    has_cover_candidate: bool,
) -> list[dict[str, str]]:
    """Point image media at same-origin proxy paths; leave videos as-is (or drop)."""
    out: list[dict[str, str]] = []
    image_index = 0
    for item in media:
        if item.get("kind") == "image":
            out.append(
                {
                    "url": media_api_path(client_id, post_id, image_index),
                    "kind": "image",
                }
            )
            image_index += 1
        elif item.get("kind") == "video":
            # Reel preview uses cover; do not expose broken CDN video in the browser.
            continue
    if not out and has_cover_candidate:
        out.append({"url": media_api_path(client_id, post_id, 0), "kind": "image"})
    return out
