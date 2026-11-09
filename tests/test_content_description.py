"""Content parts, descriptions and a small fetch. No live Meta or AI calls."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ai.content_describe import (
    COVERAGE_NONE,
    availability_note,
    content_fingerprint,
    describe_post,
    parse_content_response,
)
from db.comparison_repository import (
    ROLE_COMPETITOR,
    ROLE_OWN,
    upsert_comparison_account,
    upsert_comparison_post,
)
from db.content_repository import get_description, list_media_parts, save_description
from db.database import get_connection, initialize_database
from db.repository import upsert_comment
from meta.client import MetaRequestError
from meta.content_media import children_need_followup, parts_from_media_payload
from sync.content_sample import run_content_sample


def _setup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "content.db"))
    monkeypatch.setattr("db.database.ensure_seed_database", lambda *args, **kwargs: False)
    monkeypatch.setattr("ai.config.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    initialize_database(tmp_path / "content.db")


def _valid_payload(**overrides) -> dict:
    payload = {
        "visual_description": "Een lichte kamer met een stoel.",
        "visible_text": "Welkom",
        "spoken_content": None,
        "topic": "interieur",
        "content_kind": "foto",
        "opening": "Een stoel in beeld.",
        "call_to_viewer": "Geen oproep zichtbaar.",
        "caption_only": "De caption noemt een showroom.",
        "seen_only": "Een stoel in een lichte kamer.",
        "unclear": "De achtergrond is wazig.",
        "slides": [
            {
                "slide": 1,
                "seen": "Een stoel.",
                "visible_text": "Welkom",
                "unclear": "",
            }
        ],
        "evidence": [{"slide": 1, "timestamp": None, "note": "stoel links"}],
        "missing_parts": [],
        "video_analyzed": False,
    }
    payload.update(overrides)
    return payload


def test_carousel_keeps_order_and_marks_missing_slide() -> None:
    parts = parts_from_media_payload(
        {
            "id": "album",
            "media_type": "CAROUSEL_ALBUM",
            "children": {
                "data": [
                    {"id": "a", "media_type": "IMAGE", "media_url": "https://cdn.example/a.jpg"},
                    {"id": "b", "media_type": "IMAGE"},
                    {"id": "c", "media_type": "IMAGE", "media_url": "https://cdn.example/c.jpg"},
                ]
            },
        }
    )
    assert [part.position for part in parts] == [1, 2, 3]
    assert parts[1].available is False
    assert "Afbeeldings-URL ontbreekt" in (parts[1].unavailable_reason or "")
    note = availability_note(
        [
            {"role": "carousel_slide", "available": part.available}
            for part in parts
        ]
    )
    assert note == "2 van 3 slides beschikbaar"


def test_reel_keeps_video_and_thumbnail_apart() -> None:
    parts = parts_from_media_payload(
        {
            "id": "reel",
            "media_type": "VIDEO",
            "media_product_type": "REELS",
            "media_url": "https://cdn.example/video.mp4",
            "thumbnail_url": "https://cdn.example/cover.jpg",
        }
    )
    assert [part.role for part in parts] == ["video", "thumbnail"]
    assert parts[0].source_url != parts[1].source_url
    note = availability_note(
        [{"role": part.role, "available": True} for part in parts]
    )
    assert "nog niet als video bekeken" in note


def test_missing_video_is_not_described_as_video() -> None:
    parts = parts_from_media_payload(
        {
            "id": "reel",
            "media_type": "VIDEO",
            "media_product_type": "REELS",
            "thumbnail_url": "https://cdn.example/cover.jpg",
        }
    )
    note = availability_note(
        [{"role": part.role, "available": part.available} for part in parts]
    )
    assert note == "video ontbreekt; alleen omslagfoto beschikbaar"


def test_children_follow_only_when_next_page_exists() -> None:
    assert children_need_followup(
        {"media_type": "CAROUSEL_ALBUM", "children": {"data": [{"id": "1"}], "paging": {"cursors": {"after": "abc"}}}}
    ) is False
    assert children_need_followup(
        {
            "media_type": "CAROUSEL_ALBUM",
            "children": {"data": [{"id": "1"}], "paging": {"next": "https://graph.example/next"}},
        }
    ) is True


def test_invalid_description_and_video_claim_are_rejected() -> None:
    assert parse_content_response("geen json", video_was_sent=False) is None
    assert parse_content_response(json.dumps({"summary": "x"}), video_was_sent=False) is None
    claimed = _valid_payload(video_analyzed=True)
    assert parse_content_response(json.dumps(claimed), video_was_sent=False) is None
    spoken = _valid_payload(spoken_content="gesproken tekst")
    assert parse_content_response(json.dumps(spoken), video_was_sent=False) is None
    parsed = parse_content_response(
        json.dumps(_valid_payload()),
        video_was_sent=False,
        expected_slides=[1],
    )
    assert parsed is not None
    assert parsed["video_analyzed"] is False
    assert parsed["visible_text"] == "Welkom"
    assert parsed["caption_only"] == "De caption noemt een showroom."
    fenced = "```json\n" + json.dumps(_valid_payload()) + "\n```"
    assert parse_content_response(fenced, video_was_sent=False, expected_slides=[1]) is not None
    one_slide = _valid_payload()
    assert parse_content_response(json.dumps(one_slide), video_was_sent=False, expected_slides=[1, 2]) is None


def test_reply_with_same_external_id_is_stored_once(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        account_id = upsert_comparison_account(
            conn,
            external_id="own",
            username="theartofliving.online",
            name="own",
            comparison_role=ROLE_OWN,
        )
        post = upsert_comparison_post(
            conn,
            account_id=account_id,
            external_id="post-1",
            text="caption",
            permalink=None,
            media_type="IMAGE",
            media_product_type=None,
            published_at="2026-10-14T08:00:00+00:00",
            raw_json=None,
        )
        parent = upsert_comment(
            conn,
            platform="instagram",
            external_id="comment-1",
            post_id=post.row_id,
            text="vraag",
            author_name="gast",
            author_id=None,
            published_at="2026-10-14T09:00:00+00:00",
            raw_json=None,
        )
        first = upsert_comment(
            conn,
            platform="instagram",
            external_id="reply-1",
            post_id=post.row_id,
            text="antwoord",
            author_name="eigenaar",
            author_id=None,
            published_at="2026-10-14T09:05:00+00:00",
            raw_json=None,
            parent_comment_id=parent.row_id,
        )
        second = upsert_comment(
            conn,
            platform="instagram",
            external_id="reply-1",
            post_id=post.row_id,
            text="antwoord bijgewerkt",
            author_name="eigenaar",
            author_id=None,
            published_at="2026-10-14T09:06:00+00:00",
            raw_json=None,
            parent_comment_id=parent.row_id,
        )
        count = conn.execute("SELECT COUNT(*) FROM comments WHERE external_id = 'reply-1'").fetchone()[0]
        parent_id = conn.execute(
            "SELECT parent_comment_id FROM comments WHERE external_id = 'reply-1'"
        ).fetchone()[0]
        conn.commit()
    assert first.created is True
    assert second.created is False
    assert count == 1
    assert parent_id == parent.row_id


def test_without_ai_key_nothing_is_invented(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("AI mag niet worden aangeroepen")

    monkeypatch.setattr("ai.content_describe.requests.post", fail_if_called)
    monkeypatch.setattr("ai.content_describe.is_configured", lambda: False)
    with get_connection() as conn:
        account_id = upsert_comparison_account(
            conn,
            external_id="own",
            username="theartofliving.online",
            name="own",
            comparison_role=ROLE_OWN,
        )
        post = upsert_comparison_post(
            conn,
            account_id=account_id,
            external_id="post-2",
            text="caption als gegeven",
            permalink=None,
            media_type="IMAGE",
            media_product_type=None,
            published_at="2026-10-14T08:00:00+00:00",
            raw_json=None,
        )
        conn.commit()
        post_id = post.row_id
    result = describe_post(post_id)
    assert result.called_model is False
    assert result.coverage == COVERAGE_NONE
    with get_connection() as conn:
        stored = get_description(conn, post_id)
    assert stored is not None
    assert stored.description is None


def test_invalid_model_answer_is_not_stored_as_description(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("ai.content_describe.is_configured", lambda: True)

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "dit is geen json"}}]}

    monkeypatch.setattr("ai.content_describe.requests.post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        "ai.content_describe.load_ai_config",
        lambda: type("Cfg", (), {"base_url": "https://ai.example/v1", "api_key": "secret", "model": "test-model"})(),
    )
    with get_connection() as conn:
        account_id = upsert_comparison_account(
            conn,
            external_id="own",
            username="theartofliving.online",
            name="own",
            comparison_role=ROLE_OWN,
        )
        post = upsert_comparison_post(
            conn,
            account_id=account_id,
            external_id="post-3",
            text="caption",
            permalink=None,
            media_type="IMAGE",
            media_product_type=None,
            published_at="2026-10-14T08:00:00+00:00",
            raw_json=None,
        )
        image = tmp_path / "tiny.jpg"
        image.write_bytes(b"\xff\xd8\xff\xd9")
        parts = parts_from_media_payload(
            {"id": "post-3", "media_type": "IMAGE", "media_url": "https://cdn.example/a.jpg"}
        )
        from db.content_repository import mark_local_file, replace_media_parts

        replace_media_parts(conn, post.row_id, parts)
        item_id = list_media_parts(conn, post.row_id)[0]["id"]
        mark_local_file(conn, int(item_id), str(image))
        conn.commit()
        post_id = post.row_id
    result = describe_post(post_id)
    assert result.called_model is True
    assert result.coverage == COVERAGE_NONE
    with get_connection() as conn:
        stored = get_description(conn, post_id)
    assert stored is not None
    assert stored.description is None
    assert "Ongeldig" in (stored.coverage_note or "")


def test_image_request_uses_gemini_shape_without_metrics(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("ai.content_describe.is_configured", lambda: True)
    captured: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": json.dumps(_valid_payload())}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
            }

    def post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        captured["authorization"] = (headers or {}).get("Authorization")
        return Response()

    monkeypatch.setattr("ai.content_describe.requests.post", post)
    monkeypatch.setattr(
        "ai.content_describe.load_ai_config",
        lambda: type(
            "Cfg",
            (),
            {
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "api_key": "secret-value",
                "model": "gemini-3.5-flash-lite",
            },
        )(),
    )
    with get_connection() as conn:
        account_id = upsert_comparison_account(
            conn,
            external_id="own",
            username="theartofliving.online",
            name="own",
            comparison_role=ROLE_OWN,
        )
        post_row = upsert_comparison_post(
            conn,
            account_id=account_id,
            external_id="post-vision",
            text="caption met 12 likes",
            permalink=None,
            media_type="IMAGE",
            media_product_type=None,
            published_at="2026-10-14T08:00:00+00:00",
            raw_json=None,
        )
        image = tmp_path / "room.jpg"
        image.write_bytes(b"\xff\xd8\xff\xd9")
        parts = parts_from_media_payload(
            {"id": "post-vision", "media_type": "IMAGE", "media_url": "https://cdn.example/room.jpg"}
        )
        from db.content_repository import mark_local_file, replace_media_parts

        replace_media_parts(conn, post_row.row_id, parts)
        mark_local_file(conn, int(list_media_parts(conn, post_row.row_id)[0]["id"]), str(image))
        conn.commit()
        post_id = post_row.row_id

    result = describe_post(post_id)
    body = captured["body"]
    encoded = json.dumps(body)
    assert captured["url"].endswith("/chat/completions")
    assert "temperature" not in body
    assert body["model"] == "gemini-3.5-flash-lite"
    assert body["response_format"]["type"] == "json_schema"
    assert "like_count" not in encoded
    assert "data:image/jpeg;base64," in encoded
    assert "secret-value" not in encoded
    assert result.called_model is True
    assert result.coverage == "Volledig geanalyseerd"
    with get_connection() as conn:
        stored = get_description(conn, post_id)
    assert stored is not None
    assert stored.description["api_usage"]["prompt_tokens"] == 120
    assert stored.description["api_usage"]["completion_tokens"] == 40
    assert stored.description["slides"][0]["slide"] == 1
    monkeypatch.setattr(
        "ai.content_describe.requests.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("tweede aanvraag")),
    )
    again = describe_post(post_id)
    assert again.called_model is False


def test_unchanged_post_is_not_sent_again(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    calls = {"count": 0}

    def fail_if_called(*args, **kwargs):
        calls["count"] += 1
        raise AssertionError("ongewijzigde post")

    monkeypatch.setattr("ai.content_describe.requests.post", fail_if_called)
    monkeypatch.setattr("ai.content_describe.is_configured", lambda: True)
    with get_connection() as conn:
        account_id = upsert_comparison_account(
            conn,
            external_id="own",
            username="theartofliving.online",
            name="own",
            comparison_role=ROLE_OWN,
        )
        post = upsert_comparison_post(
            conn,
            account_id=account_id,
            external_id="post-4",
            text="zelfde caption",
            permalink=None,
            media_type="IMAGE",
            media_product_type=None,
            published_at="2026-10-14T08:00:00+00:00",
            raw_json=None,
        )
        parts = parts_from_media_payload(
            {"id": "post-4", "media_type": "IMAGE", "media_url": "https://cdn.example/a.jpg"}
        )
        from db.content_repository import replace_media_parts

        replace_media_parts(conn, post.row_id, parts)
        rows = list_media_parts(conn, post.row_id)
        fingerprint = content_fingerprint(
            "zelfde caption",
            [
                {
                    "position": row["position"],
                    "role": row["role"],
                    "external_id": row["external_id"],
                    "available": bool(row["available"]),
                    "source_url": row["source_url"],
                }
                for row in rows
            ],
        )
        save_description(
            conn,
            post_id=post.row_id,
            fingerprint=fingerprint,
            coverage="Volledig geanalyseerd",
            coverage_note="1 van 1 slides verwerkt",
            description=_valid_payload(),
            files_processed=["post_4_image_1.img"],
            model="test-model",
            prompt_version="content-describe-v1",
            analyzed_at="2026-10-20T10:00:00+00:00",
        )
        conn.commit()
        post_id = post.row_id
    result = describe_post(post_id)
    assert result.called_model is False
    assert result.stored is False
    assert calls["count"] == 0


def test_sample_stores_parts_and_stops_on_rate_limit(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    with get_connection() as conn:
        own = upsert_comparison_account(
            conn,
            external_id="17841400191455972",
            username="theartofliving.online",
            name="own",
            comparison_role=ROLE_OWN,
        )
        image = upsert_comparison_post(
            conn,
            account_id=own,
            external_id="image-1",
            text=None,
            permalink=None,
            media_type="IMAGE",
            media_product_type=None,
            published_at="2026-10-16T08:00:00+00:00",
            raw_json=None,
        )
        upsert_comparison_post(
            conn,
            account_id=own,
            external_id="album-1",
            text=None,
            permalink=None,
            media_type="CAROUSEL_ALBUM",
            media_product_type=None,
            published_at="2026-10-15T08:00:00+00:00",
            raw_json=None,
        )
        upsert_comment(
            conn,
            platform="instagram",
            external_id="comment-9",
            post_id=image.row_id,
            text="vraag",
            author_name=None,
            author_id=None,
            published_at="2026-10-16T09:00:00+00:00",
            raw_json=None,
        )
        upsert_comparison_account(
            conn,
            external_id="comp",
            username="hoog.design",
            name="Hoog",
            comparison_role=ROLE_COMPETITOR,
        )
        conn.commit()

    class Client:
        def __init__(self) -> None:
            self.children_called = False
            self.discovery_called = False

        def get_instagram_media_content(self, media_id: str) -> dict:
            if media_id == "image-1":
                return {
                    "id": media_id,
                    "caption": "caption van de post",
                    "media_type": "IMAGE",
                    "media_url": "https://cdn.example/hidden.jpg",
                }
            if media_id == "album-1":
                return {
                    "id": media_id,
                    "caption": "carrousel",
                    "media_type": "CAROUSEL_ALBUM",
                    "children": {
                        "data": [{"id": "s1", "media_type": "IMAGE", "media_url": "https://cdn.example/1.jpg"}],
                        "paging": {"next": "https://graph.example/next"},
                    },
                }
            raise AssertionError(media_id)

        def get_instagram_media_children(self, media_id: str) -> list[dict]:
            self.children_called = True
            return [
                {"id": "s1", "media_type": "IMAGE", "media_url": "https://cdn.example/1.jpg"},
                {"id": "s2", "media_type": "IMAGE", "media_url": "https://cdn.example/2.jpg"},
            ]

        def get_instagram_comment_replies(self, comment_id: str, *, limit: int | None = 50) -> list[dict]:
            return [
                {
                    "id": "reply-9",
                    "text": "antwoord",
                    "timestamp": "2026-10-16T10:00:00+0000",
                    "username": "theartofliving.online",
                }
            ]

        def get_json(self, endpoint: str, *, params=None, use_page_token: bool = True) -> dict:
            self.discovery_called = True
            return {
                "business_discovery": {
                    "media": {
                        "data": [
                            {
                                "id": "unknown-competitor-post",
                                "caption": "competitor caption",
                                "media_type": "IMAGE",
                                "media_url": "https://cdn.example/secret.jpg",
                            }
                        ]
                    }
                }
            }

    client = Client()
    with get_connection() as conn:
        report = run_content_sample(conn, client, host_id="17841400191455972")
        conn.commit()
        image_parts = list_media_parts(
            conn,
            conn.execute("SELECT id FROM posts WHERE external_id = 'image-1'").fetchone()[0],
        )
        slide_count = conn.execute(
            """
            SELECT COUNT(*) FROM post_media_items
            WHERE post_id = (SELECT id FROM posts WHERE external_id = 'album-1')
            """
        ).fetchone()[0]
        replies = conn.execute("SELECT COUNT(*) FROM comments WHERE external_id = 'reply-9'").fetchone()[0]
    assert client.children_called is True
    assert client.discovery_called is True
    assert image_parts[0]["available"] == 1
    assert slide_count == 2
    assert replies == 1
    dumped = json.dumps(report)
    assert "https://" not in dumped
    assert "caption van de post" not in dumped
    assert report["competitor"]["posts"][0]["caption_present"] is True

    class Limited:
        def get_instagram_media_content(self, media_id: str) -> dict:
            raise MetaRequestError("limiet", error_code=4, is_rate_limited=True)

        def get_json(self, *args, **kwargs):
            raise AssertionError("geen extra aanvraag")

    with get_connection() as conn:
        stopped = run_content_sample(conn, Limited(), host_id="17841400191455972")
    assert stopped["stopped"]
    assert stopped["competitor"] is None
    assert stopped["own"][0]["rate_limited"] is True


def test_partial_coverage_note_counts_processed_slides() -> None:
    from ai.content_describe import _coverage_after_call

    coverage, note = _coverage_after_call(images_sent=3, images_expected=5, caption_only=False)
    assert coverage == "Gedeeltelijk geanalyseerd"
    assert note == "3 van 5 slides verwerkt"
