"""Same-origin thumbnail proxy helpers for Maaike feed cards."""

from __future__ import annotations

from pathlib import Path

from maaike.feed import feed_card, parse_media_urls
from maaike.repository import StoredPost
from maaike.thumbnails import (
    cache_key,
    cover_api_path,
    media_api_path,
    rewrite_feed_media,
    save_compressed_jpeg,
)


def test_parse_media_skips_permalink_hosts() -> None:
    raw = "https://www.instagram.com/p/abc/\nhttps://scontent.cdninstagram.com/v/t51/x.jpg"
    items = parse_media_urls(raw)
    assert len(items) == 1
    assert items[0]["kind"] == "image"


def test_parse_media_accepts_json_array() -> None:
    raw = '["https://scontent.cdninstagram.com/v/t51/a.jpg", "https://scontent.cdninstagram.com/v/t51/b.mp4"]'
    items = parse_media_urls(raw)
    assert [item["kind"] for item in items] == ["image", "video"]


def test_rewrite_feed_media_uses_proxy_paths() -> None:
    media = [
        {"url": "https://scontent.cdninstagram.com/v/t51/a.jpg", "kind": "image"},
        {"url": "https://scontent.cdninstagram.com/v/t51/b.mp4", "kind": "video"},
        {"url": "https://scontent.cdninstagram.com/v/t51/c.jpg", "kind": "image"},
    ]
    out = rewrite_feed_media(media, client_id=1, post_id=42, has_cover_candidate=True)
    assert out == [
        {"url": media_api_path(1, 42, 0), "kind": "image"},
        {"url": media_api_path(1, 42, 1), "kind": "image"},
    ]


def test_feed_card_cover_is_same_origin_when_client_set() -> None:
    post = StoredPost(
        post_id=9,
        platform="instagram",
        published_at="2026-11-05T18:03:17+0000",
        content_kind="carousel_album",
        permalink="https://www.instagram.com/p/x/",
        views=1,
        likes=2,
        comments=0,
        shares=None,
        saves=None,
        clicks=None,
        last_synced_at=None,
        format_id=None,
        format_name=None,
        pillar_id=None,
        pillar_name=None,
        hook="",
        external_id="17922651387449703",
        account_name="redrock.agency",
        caption="hello",
        media_urls="https://scontent.cdninstagram.com/v/t51/a.jpg",
    )
    card = feed_card(post, client_id=1)
    assert card["cover_url"] == cover_api_path(1, 9)
    assert card["media"][0]["url"].startswith("/api/clients/1/posts/9/media-file/")


def test_save_compressed_jpeg_and_cache_key(tmp_path: Path) -> None:
    from PIL import Image

    src = tmp_path / "src.png"
    Image.new("RGB", (32, 32), color=(20, 80, 160)).save(src, format="PNG")
    target = tmp_path / "cover.jpg"
    assert save_compressed_jpeg(src.read_bytes(), target)
    assert target.stat().st_size > 0
    assert cache_key("instagram", "17922651387449703") == "instagram_17922651387449703"
