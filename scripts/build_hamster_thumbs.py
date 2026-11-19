"""Build maaike/seed/hamster_thumbs.tar.gz from Graph + stored media URLs.

Uses the local Maaike DB page token. Walks Instagram media + Facebook posts so
covers exist even when the local post table is a subset of live. Only JPEG
covers (and optional carousel slides). Idempotent: existing files are kept.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MAAIKE_DATABASE_PATH", str(ROOT / "data" / "maaike_redrock.db"))


def _cache_from_urls(platform: str, external_id: str, urls: list[str], session) -> bool:
    from maaike.thumbnails import download_image_bytes, write_cover_from_bytes

    for url in urls:
        content = download_image_bytes(url, session=session)
        if content and write_cover_from_bytes(platform, external_id, content):
            return True
    return False


def _graph_walk(conn: sqlite3.Connection, client_id: int) -> tuple[int, int]:
    """Download covers for every IG/FB object currently visible via Graph."""
    from maaike.repository import load_page_secret
    from maaike.thumbnails import (
        _graph_version,
        _http_session,
        _urls_from_ig_media_payload,
        refresh_image_urls_via_graph,
    )

    secret = load_page_secret(conn, client_id)
    if secret is None:
        print("no page token — skip Graph walk")
        return 0, 0
    page_id, ig_user_id, page_token = secret
    session = _http_session()
    version = _graph_version()
    ok = 0
    fail = 0

    def cache_one(platform: str, external_id: str, discovery_username: str | None = None) -> bool:
        urls = refresh_image_urls_via_graph(
            platform=platform,
            external_id=external_id,
            page_token=page_token,
            host_ig_user_id=ig_user_id,
            discovery_username=discovery_username,
        )
        return _cache_from_urls(platform, external_id, urls, session)

    # Instagram media (own account)
    url = f"https://graph.facebook.com/{version}/{ig_user_id}/media"
    params = {
        "fields": "id,media_type,media_product_type,media_url,thumbnail_url",
        "limit": "50",
        "access_token": page_token,
    }
    while url:
        response = session.get(url, params=params, timeout=30)
        params = None
        if response.status_code != 200:
            print("ig media page failed", response.status_code, response.text[:160])
            break
        payload = response.json()
        for item in payload.get("data") or []:
            ext = str(item.get("id") or "")
            if not ext:
                continue
            if cache_one("instagram", ext):
                ok += 1
            else:
                fail += 1
        paging = payload.get("paging") if isinstance(payload.get("paging"), dict) else {}
        next_url = paging.get("next")
        url = next_url if isinstance(next_url, str) else None
        if ok + fail and (ok + fail) % 50 == 0:
            print(f"  ig progress ok={ok} fail={fail}")

    # Facebook published posts
    url = f"https://graph.facebook.com/{version}/{page_id}/published_posts"
    params = {
        "fields": "id,full_picture",
        "limit": "50",
        "access_token": page_token,
    }
    while url:
        response = session.get(url, params=params, timeout=30)
        params = None
        if response.status_code != 200:
            print("fb posts page failed", response.status_code, response.text[:160])
            break
        payload = response.json()
        for item in payload.get("data") or []:
            ext = str(item.get("id") or "")
            if not ext:
                continue
            if cache_one("facebook", ext):
                ok += 1
            else:
                fail += 1
        paging = payload.get("paging") if isinstance(payload.get("paging"), dict) else {}
        next_url = paging.get("next")
        url = next_url if isinstance(next_url, str) else None
        if ok + fail and (ok + fail) % 50 == 0:
            print(f"  meta progress ok={ok} fail={fail}")

    # Competitor accounts via Business Discovery (from seed + local posts)
    usernames: set[str] = set()
    for row in conn.execute(
        """
        SELECT DISTINCT source_origin, account_name FROM posts
        WHERE client_id = ? AND platform = 'instagram'
        """,
        (client_id,),
    ):
        origin = str(row["source_origin"] or "")
        if origin.startswith("business_discovery:"):
            usernames.add(origin.split(":", 1)[1].strip().lstrip("@"))
        account = str(row["account_name"] or "").strip()
        if account.startswith("@") and "redrock" not in account.lower():
            usernames.add(account.lstrip("@"))
    seed_path = ROOT / "maaike" / "seed" / "hamster_redrock.json.gz"
    if seed_path.is_file():
        import gzip
        import json

        package = json.loads(gzip.decompress(seed_path.read_bytes()).decode("utf-8"))
        for post in package.get("posts") or []:
            origin = str(post.get("source_origin") or "")
            if origin.startswith("business_discovery:"):
                usernames.add(origin.split(":", 1)[1].strip().lstrip("@"))
            account = str(post.get("account_name") or "").strip()
            if account.startswith("@") and "redrock" not in account.lower():
                usernames.add(account.lstrip("@"))

    usernames = {u for u in usernames if u}
    print(f"discovery usernames: {sorted(usernames)}")
    for username in sorted(usernames):
        after = None
        pages = 0
        while pages < 8:
            pages += 1
            media_q = "media.limit(50)"
            if after:
                media_q += f".after({after})"
            media_q += "{id,media_type,media_product_type,media_url,thumbnail_url}"
            fields = f"business_discovery.username({username}){{{media_q}}}"
            response = session.get(
                f"https://graph.facebook.com/{version}/{ig_user_id}",
                params={"fields": fields, "access_token": page_token},
                timeout=40,
            )
            if response.status_code != 200:
                print(f"  discovery {username} failed", response.status_code)
                break
            payload = response.json()
            discovery = payload.get("business_discovery") if isinstance(payload, dict) else None
            if not isinstance(discovery, dict):
                print(f"  discovery {username} missing payload")
                break
            block = discovery.get("media") if isinstance(discovery.get("media"), dict) else {}
            items = block.get("data") if isinstance(block, dict) else []
            if not isinstance(items, list):
                items = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                ext = str(item.get("id") or "")
                if not ext:
                    continue
                urls = _urls_from_ig_media_payload(item)
                if _cache_from_urls("instagram", ext, urls, session):
                    ok += 1
                else:
                    fail += 1
            paging = block.get("paging") if isinstance(block, dict) else None
            cursors = paging.get("cursors") if isinstance(paging, dict) else None
            after = cursors.get("after") if isinstance(cursors, dict) else None
            print(f"  discovery @{username} page {pages} items={len(items)} ok={ok} fail={fail}")
            if not after:
                break

    return ok, fail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="0 = all local posts with media")
    parser.add_argument("--slides", action="store_true", help="Also cache carousel slides from local posts")
    parser.add_argument("--skip-graph-walk", action="store_true")
    args = parser.parse_args()

    from maaike.thumbnails import (
        SEED_REL,
        ensure_cover_file,
        ensure_slide_file,
        seed_thumbs_path,
        thumb_root,
    )

    db_path = Path(os.environ["MAAIKE_DATABASE_PATH"])
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if not args.skip_graph_walk:
        print("Graph walk (all visible IG/FB media)…")
        g_ok, g_fail = _graph_walk(conn, args.client_id)
        print(f"graph walk ok={g_ok} fail={g_fail}")

    rows = conn.execute(
        """
        SELECT id, platform, external_id, content_kind, media_urls
        FROM posts
        WHERE client_id = ?
          AND media_urls IS NOT NULL
          AND TRIM(media_urls) != ''
          AND platform IN ('instagram', 'facebook')
        ORDER BY published_at DESC
        """,
        (args.client_id,),
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f"local posts with media: {len(rows)} → {thumb_root()}")

    ok = 0
    fail = 0

    def work(row: sqlite3.Row) -> tuple[int, bool]:
        local = sqlite3.connect(db_path)
        local.row_factory = sqlite3.Row
        try:
            path = ensure_cover_file(local, args.client_id, int(row["id"]))
            if path is None:
                return int(row["id"]), False
            if args.slides and (row["content_kind"] or "").lower() in {
                "carousel_album",
                "carrousel",
                "carousel",
            }:
                for index in range(1, 8):
                    ensure_slide_file(local, args.client_id, int(row["id"]), index)
            local.commit()
            return int(row["id"]), True
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(work, row) for row in rows]
        for fut in as_completed(futures):
            _pid, success = fut.result()
            if success:
                ok += 1
            else:
                fail += 1
            if (ok + fail) % 25 == 0:
                print(f"  local progress {ok + fail}/{len(rows)} ok={ok} fail={fail}")

    print(f"local ensure ok={ok} fail={fail}")

    seed = seed_thumbs_path()
    seed.parent.mkdir(parents=True, exist_ok=True)
    root = thumb_root()
    files = sorted(root.glob("*.jpg"))
    if not files:
        print("no thumbnails to pack")
        return 1
    with tarfile.open(seed, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=path.name)
    print(f"wrote {seed.relative_to(ROOT)} files={len(files)} bytes={seed.stat().st_size}")
    print(f"tracked as {SEED_REL.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
