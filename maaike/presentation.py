"""Display values for the Red Rock post overview. Missing numbers stay unavailable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from maaike.repository import UNSET_LABEL, StoredPost

NOT_AVAILABLE = "not available"
RATING_PENDING = "not rated yet"
AMSTERDAM = ZoneInfo("Europe/Amsterdam")

# Internal cell keys stay stable for Excel import/export round-trips; UI uses COLUMN_LABELS.
OVERVIEW_COLUMNS = (
    "Maand",
    "Publicatiedatum",
    "Platform",
    "Account",
    "Meta-post-ID",
    "Contentsoort",
    "Media",
    "Contentformat",
    "Post-URL",
    "Contentpijler",
    "Hook",
    "Tekst",
    "Weergaven",
    "Bereik",
    "Likes",
    "Comments",
    "Shares",
    "Saves",
    "Clicks",
    "Beoordeling",
    "Insight",
    "Actie",
)

COLUMN_LABELS = {
    "Maand": "Month",
    "Publicatiedatum": "Publication date",
    "Platform": "Platform",
    "Account": "Account",
    "Meta-post-ID": "Meta post ID",
    "Contentsoort": "Content type",
    "Media": "Media",
    "Contentformat": "Content format",
    "Post-URL": "Post URL",
    "Contentpijler": "Content pillar",
    "Hook": "Hook",
    "Tekst": "Text",
    "Weergaven": "Views",
    "Bereik": "Reach",
    "Likes": "Likes",
    "Comments": "Comments",
    "Shares": "Shares",
    "Saves": "Saves",
    "Clicks": "Clicks",
    "Beoordeling": "Rating",
    "Insight": "Insight",
    "Actie": "Action",
}

EDITABLE_COLUMNS = frozenset({"Contentformat", "Contentpijler", "Hook"})

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_PLATFORM_LABELS = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "linkedin_zakelijk": "LinkedIn - Zakelijk",
}

_KIND_LABELS = {
    "reel": "Reel",
    "reels": "Reel",
    "carousel": "Carousel",
    "carousel_album": "Carousel",
    "image": "Image",
    "video": "Video",
    "post": "Post",
    "photo": "Photo",
    "album": "Album",
    "video_inline": "Video",
    "share": "Share",
}


@dataclass(frozen=True, slots=True)
class EditorialChange:
    post_id: int
    format_id: int | None
    pillar_id: int | None
    hook: str


def format_metric(value: int | None, *, previous: bool = False) -> str:
    """Show a stored integer, including 0. Missing stays unavailable."""
    if value is None:
        return NOT_AVAILABLE
    text = str(value)
    if previous:
        return f"{text} (previously measured)"
    return text


def format_sync_moment(value: str | None) -> str:
    """Format the latest stored sync time in Europe/Amsterdam. Naive values are UTC."""
    parsed = _parse_timestamp(value)
    if parsed is None:
        return NOT_AVAILABLE
    return parsed.astimezone(AMSTERDAM).strftime("%d-%m-%Y %H:%M")


def overview_record(post: StoredPost) -> dict[str, str]:
    month, published = _published_labels(post.published_at)
    rating = post.rating_text or RATING_PENDING
    if post.rating_text and post.rating_source_label:
        rating = f"{post.rating_text} ({post.rating_source_label})"
    return {
        "Maand": month,
        "Publicatiedatum": published,
        "Platform": post.platform_label or _platform_label(post.platform),
        "Account": post.account_name or NOT_AVAILABLE,
        "Meta-post-ID": _identity_label(post.external_id),
        "Contentsoort": post.content_soort_raw or _kind_label(post.content_kind),
        "Media": post.media_urls or NOT_AVAILABLE,
        "Contentformat": _format_label(post),
        "Post-URL": post.permalink or ("" if (post.external_id or "").startswith("excelrow:") else NOT_AVAILABLE),
        "Contentpijler": post.pillar_name or UNSET_LABEL,
        "Hook": post.hook,
        "Tekst": post.caption or NOT_AVAILABLE,
        "Weergaven": _metric_cell(post, "views", post.views),
        "Bereik": _metric_cell(post, "reach", post.reach),
        "Likes": _metric_cell(post, "likes", post.likes),
        "Comments": _metric_cell(post, "comments", post.comments),
        "Shares": _metric_cell(post, "shares", post.shares),
        "Saves": _metric_cell(post, "saves", post.saves),
        "Clicks": _metric_cell(post, "clicks", post.clicks),
        "Beoordeling": rating,
        "Insight": post.insight_text or "",
        "Actie": post.action_text or "",
    }


def _metric_cell(post: StoredPost, name: str, value: int | None) -> str:
    return format_metric(value, previous=name in post.previous_metrics)


def overview_table(posts: list[StoredPost]) -> tuple[list[int], list[dict[str, str]]]:
    ids = [post.post_id for post in posts]
    return ids, [overview_record(post) for post in posts]


def editorial_changes(
    post_ids: list[int],
    original_rows: list[dict],
    edited_rows: list[dict],
    *,
    format_ids: dict[str, int],
    pillar_ids: dict[str, int],
) -> list[EditorialChange]:
    """Return format, pillar and hook edits. Other columns are ignored."""
    if len(edited_rows) != len(post_ids) or len(original_rows) != len(post_ids):
        raise ValueError(
            "The post overview changed. Refresh the page and try again."
        )
    changes: list[EditorialChange] = []
    for post_id, original, edited in zip(post_ids, original_rows, edited_rows):
        new_format = _cell_text(edited.get("Contentformat"))
        new_pillar = _cell_text(edited.get("Contentpijler"))
        new_hook = _cell_text(edited.get("Hook"))
        old_format = _cell_text(original.get("Contentformat")) or UNSET_LABEL
        old_pillar = _cell_text(original.get("Contentpijler")) or UNSET_LABEL
        old_hook = _cell_text(original.get("Hook"))
        if (new_format, new_pillar, new_hook) == (old_format, old_pillar, old_hook):
            continue
        changes.append(
            EditorialChange(
                post_id=post_id,
                format_id=_legend_id(new_format, format_ids, label_name="contentformat"),
                pillar_id=_legend_id(new_pillar, pillar_ids, label_name="contentpijler"),
                hook=new_hook,
            )
        )
    return changes


def _legend_id(label: str, mapping: dict[str, int], *, label_name: str) -> int | None:
    if not label or label == UNSET_LABEL:
        return None
    if label not in mapping:
        raise ValueError(f"Unknown choice for {label_name}: {label}")
    return mapping[label]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()


def _published_labels(value: str | None) -> tuple[str, str]:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return NOT_AVAILABLE, NOT_AVAILABLE
    local = parsed.astimezone(AMSTERDAM)
    month = f"{MONTH_NAMES[local.month - 1]} {local.year}"
    return month, local.strftime("%d-%m-%Y")


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _platform_label(value: str | None) -> str:
    if not value or not value.strip():
        return NOT_AVAILABLE
    return _PLATFORM_LABELS.get(value.strip().lower(), value.strip())


def _identity_label(external_id: str | None) -> str:
    if not external_id:
        return NOT_AVAILABLE
    text = str(external_id)
    if text.startswith("excelrow:"):
        return f"internal Excel ID ({text})"
    return text


def _format_label(post: StoredPost) -> str:
    raw = (post.format_code_raw or "").strip()
    if raw.lower() in {"nvt.", "nvt", "n.v.t.", "n.v.t"}:
        return raw
    return post.format_name or raw or UNSET_LABEL


def _kind_label(value: str | None) -> str:
    if not value or not value.strip():
        return NOT_AVAILABLE
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return _KIND_LABELS.get(key, value.strip())
