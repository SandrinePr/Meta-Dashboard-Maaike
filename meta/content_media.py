"""Parse Instagram media into ordered parts. No network and no token logging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


OWN_CONTENT_FIELDS = (
    "id",
    "caption",
    "media_type",
    "media_product_type",
    "media_url",
    "thumbnail_url",
    "permalink",
    "timestamp",
    "children{id,media_type,media_url,thumbnail_url}",
)

DISCOVERY_CONTENT_FIELDS = (
    "id",
    "caption",
    "media_type",
    "media_product_type",
    "media_url",
    "thumbnail_url",
    "permalink",
    "timestamp",
    "like_count",
    "comments_count",
    "children{id,media_type,media_url,thumbnail_url}",
)


def as_content_fields(fields: tuple[str, ...]) -> str:
    return ",".join(fields)


@dataclass(frozen=True, slots=True)
class MediaPart:
    position: int
    role: str
    external_id: str | None
    media_type: str | None
    source_url: str | None
    available: bool
    unavailable_reason: str | None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _children_list(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Return child dicts and whether another page was advertised."""
    children = payload.get("children")
    if not isinstance(children, dict):
        return [], False
    data = children.get("data")
    rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    paging = children.get("paging")
    has_next = isinstance(paging, dict) and isinstance(paging.get("next"), str) and bool(paging.get("next"))
    return rows, has_next


def parts_from_media_payload(payload: dict[str, Any]) -> list[MediaPart]:
    """Split one media object into image, slide, video and thumbnail parts.

    A thumbnail is never labeled as the video. Missing URLs stay unavailable.
    """
    media_type = _text(payload.get("media_type"))
    product = (_text(payload.get("media_product_type")) or "").upper()
    kind = (media_type or "").upper()
    is_reel = product == "REELS" or kind == "VIDEO"
    is_carousel = kind == "CAROUSEL_ALBUM"
    parts: list[MediaPart] = []

    if is_carousel:
        children, _has_next = _children_list(payload)
        if not children:
            parts.append(
                MediaPart(
                    position=1,
                    role="carousel_slide",
                    external_id=_text(payload.get("id")),
                    media_type=media_type,
                    source_url=None,
                    available=False,
                    unavailable_reason="Carrousel-onderdelen ontbreken in het API-antwoord.",
                )
            )
            return parts
        for index, child in enumerate(children, start=1):
            url = _text(child.get("media_url"))
            child_type = _text(child.get("media_type"))
            if (child_type or "").upper() == "VIDEO":
                video_url = url
                thumb = _text(child.get("thumbnail_url"))
                parts.append(
                    MediaPart(
                        position=index,
                        role="video",
                        external_id=_text(child.get("id")),
                        media_type=child_type,
                        source_url=video_url,
                        available=video_url is not None,
                        unavailable_reason=None if video_url else "Video-URL ontbreekt voor deze slide.",
                    )
                )
                parts.append(
                    MediaPart(
                        position=index,
                        role="thumbnail",
                        external_id=_text(child.get("id")),
                        media_type=child_type,
                        source_url=thumb,
                        available=thumb is not None,
                        unavailable_reason=None if thumb else "Omslagfoto ontbreekt voor deze videoslide.",
                    )
                )
                continue
            parts.append(
                MediaPart(
                    position=index,
                    role="carousel_slide",
                    external_id=_text(child.get("id")),
                    media_type=child_type,
                    source_url=url,
                    available=url is not None,
                    unavailable_reason=None if url else "Afbeeldings-URL ontbreekt voor deze slide.",
                )
            )
        return parts

    if is_reel:
        video_url = _text(payload.get("media_url"))
        thumb = _text(payload.get("thumbnail_url"))
        parts.append(
            MediaPart(
                position=1,
                role="video",
                external_id=_text(payload.get("id")),
                media_type=media_type,
                source_url=video_url,
                available=video_url is not None,
                unavailable_reason=None if video_url else "Video-URL ontbreekt.",
            )
        )
        parts.append(
            MediaPart(
                position=1,
                role="thumbnail",
                external_id=_text(payload.get("id")),
                media_type=media_type,
                source_url=thumb,
                available=thumb is not None,
                unavailable_reason=None if thumb else "Omslagfoto ontbreekt.",
            )
        )
        return parts

    image_url = _text(payload.get("media_url"))
    parts.append(
        MediaPart(
            position=1,
            role="image",
            external_id=_text(payload.get("id")),
            media_type=media_type,
            source_url=image_url,
            available=image_url is not None,
            unavailable_reason=None if image_url else "Afbeeldings-URL ontbreekt.",
        )
    )
    return parts


def children_need_followup(payload: dict[str, Any]) -> bool:
    """True when a carousel still has a next page or no child list at all."""
    kind = (_text(payload.get("media_type")) or "").upper()
    if kind != "CAROUSEL_ALBUM":
        return False
    children, has_next = _children_list(payload)
    return has_next or not children
