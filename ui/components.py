"""Reusable RRO-styled Streamlit UI components."""

from __future__ import annotations

import html
import logging
import os
import re
from datetime import date, datetime
from typing import Iterable

import streamlit as st

from search.engine import (
    DEFAULT_FILTER_TYPES,
    SearchResult,
    detect_match_types,
    matches_hashtag_query as engine_matches_hashtag_query,
    normalize_search_term,
    result_membership_types,
)
from ui.icons import (
    COMMENT_ICON,
    FACEBOOK_ICON,
    HEART_STAT_ICON,
    INSTAGRAM_ICON,
    MESSAGE_STAT_ICON,
    POST_ICON,
    SAVE_STAT_ICON,
    SHARE_STAT_ICON,
    STAT_COMMENT_ICON,
    VIEW_STAT_ICON,
)
from ui.media import (
    get_comment_parent_caption,
    get_comment_parent_post_id,
    get_content_type_for_result,
    get_engagement_stats,
    get_local_image_path_for_result,
    is_result_unavailable,
    local_media_data_uri,
)
from ui import styles as styles_mod

logger = logging.getLogger(__name__)

_HASHTAG_INLINE_PATTERN = re.compile(r"#([A-Za-z0-9_]+)")
_INLINE_HIGHLIGHT_PATTERN = re.compile(r"(#[A-Za-z0-9_]+)|(@[A-Za-z0-9._]+)")


def highlight_hashtags_in_text(text: str | None) -> str:
    """Escape user content and wrap hashtags (#) and mentions (@) in spans."""
    if not text:
        return "Geen tekst"

    parts: list[str] = []
    last_end = 0
    for match in _INLINE_HIGHLIGHT_PATTERN.finditer(text):
        if match.start() > last_end:
            parts.append(html.escape(text[last_end : match.start()]))
        css_class = "hashtag" if match.group(1) else "mention"
        parts.append(f'<span class="{css_class}">{html.escape(match.group(0))}</span>')
        last_end = match.end()
    if last_end < len(text):
        parts.append(html.escape(text[last_end:]))
    return "".join(parts) if parts else html.escape(text)


_SNIPPET_THRESHOLD = 120
_SNIPPET_CONTEXT = 50


def _highlight_terms(query: str | None) -> list[str]:
    """Return lowercased search terms to highlight, longest first."""
    if not query:
        return []
    base = normalize_search_term(query).strip().lower()
    terms: set[str] = set()
    if base:
        terms.add(base)
        for token in re.split(r"\s+", base):
            token = token.strip("#@").strip()
            if len(token) >= 2:
                terms.add(token)
    return sorted(terms, key=len, reverse=True)


def _terms_regex(terms: list[str]) -> re.Pattern[str] | None:
    if not terms:
        return None
    return re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)


def _apply_term_highlight(plain_text: str, pattern: re.Pattern[str] | None) -> str:
    """Escape plain text and wrap query-term matches in a text-match span."""
    if not pattern:
        return html.escape(plain_text)
    parts: list[str] = []
    last_end = 0
    for match in pattern.finditer(plain_text):
        if match.start() > last_end:
            parts.append(html.escape(plain_text[last_end : match.start()]))
        parts.append(f'<span class="text-match">{html.escape(match.group(0))}</span>')
        last_end = match.end()
    if last_end < len(plain_text):
        parts.append(html.escape(plain_text[last_end:]))
    return "".join(parts)


def _build_highlighted_html(text: str, pattern: re.Pattern[str] | None) -> str:
    """Highlight query terms; hashtags/mentions are matched as a whole token.

    Hashtags/mentions detected first: when the term matches inside one, the whole
    token gets a subtle underline (no nested spans, no background). Remaining plain
    text uses the yellow background highlight.
    """
    parts: list[str] = []
    last_end = 0
    for match in _INLINE_HIGHLIGHT_PATTERN.finditer(text):
        if match.start() > last_end:
            parts.append(_apply_term_highlight(text[last_end : match.start()], pattern))
        token = match.group(0)
        base = "hashtag" if match.group(1) else "mention"
        matched = pattern is not None and pattern.search(token) is not None
        css_class = f"{base} {base}-match" if matched else base
        parts.append(f'<span class="{css_class}">{html.escape(token)}</span>')
        last_end = match.end()
    if last_end < len(text):
        parts.append(_apply_term_highlight(text[last_end:], pattern))
    return "".join(parts)


def _snippet_around_match(
    text: str,
    pattern: re.Pattern[str] | None,
) -> tuple[str, bool, bool]:
    """Return (snippet, cut_start, cut_end) with ~50 chars of context per side."""
    if len(text) <= _SNIPPET_THRESHOLD or pattern is None:
        return text, False, False

    match = pattern.search(text)
    if match is None:
        return text, False, False

    start = max(0, match.start() - _SNIPPET_CONTEXT)
    end = min(len(text), match.end() + _SNIPPET_CONTEXT)

    if start > 0:
        space = text.find(" ", start, match.start())
        if space != -1:
            start = space + 1
    if end < len(text):
        space = text.rfind(" ", match.end(), end)
        if space != -1:
            end = space

    return text[start:end], start > 0, end < len(text)


def highlight_and_snippet(text: str | None, query: str = "") -> str:
    """Render caption/comment text: context snippet + term/hashtag/mention styling."""
    if not text:
        return "Geen tekst"

    terms = _highlight_terms(query)
    pattern = _terms_regex(terms)
    snippet, cut_start, cut_end = _snippet_around_match(text, pattern)
    body = _build_highlighted_html(snippet, pattern)
    prefix = "... " if cut_start else ""
    suffix = " ..." if cut_end else ""
    return f"{prefix}{body}{suffix}"


def matches_hashtag_query(result: SearchResult, query: str) -> bool:
    """Return True when the search term matches one of the post hashtags."""
    return engine_matches_hashtag_query(result, query)


def inject_styles() -> None:
    """Inject global RRO theme CSS only (no iframes — they create empty gaps).

    Reload ``ui.styles`` each run so CSS edits reach the browser without a
    full Streamlit process restart (Python otherwise keeps the first import).
    """
    import importlib

    importlib.reload(styles_mod)
    st.markdown(styles_mod.RRO_CSS, unsafe_allow_html=True)


def inject_sidebar_helpers() -> None:
    """No-op. Previously injected a components.html iframe that created a huge
    empty gap above the title after search reruns.
    """
    return None


def _format_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return value



def resolve_checkbox_filters(
    *,
    instagram: bool,
    facebook: bool,
    comments: bool,
    tags: bool,
    hashtags: bool = False,
    captions: bool = False,
) -> tuple[set[str], set[str]]:
    """Map checkbox state to platform/type sets. All off means no filter."""
    platforms: set[str] = set()
    if instagram:
        platforms.add("instagram")
    if facebook:
        platforms.add("facebook")
    if not platforms:
        platforms = {"instagram", "facebook"}

    entity_types: set[str] = set()
    if comments:
        entity_types.add("comment")
    if tags:
        entity_types.add("tag")
    if hashtags:
        entity_types.add("hashtag")
    if captions:
        entity_types.add("caption")
    if not entity_types:
        entity_types = set(DEFAULT_FILTER_TYPES)

    return platforms, entity_types


def filter_results(
    results: Iterable[SearchResult],
    platforms: set[str],
    entity_types: set[str],
    query: str,
) -> list[SearchResult]:
    """Apply platform + match-type filters client-side after search."""
    types = set(entity_types) or set(DEFAULT_FILTER_TYPES)
    filtered: list[SearchResult] = []
    for result in results:
        if result.platform not in platforms:
            continue
        if result_membership_types(result, query) & types:
            filtered.append(result)
    return filtered


def _render_deploy_version() -> None:
    """Show git commit on hosted deploys so Railway/Render version is verifiable."""
    sha = (
        os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("SOURCE_VERSION")
    )
    if not sha:
        return
    branch = (
        os.getenv("RAILWAY_GIT_BRANCH")
        or os.getenv("RENDER_GIT_BRANCH")
        or os.getenv("RAILWAY_ENVIRONMENT_NAME")
        or ""
    )
    label = sha[:7]
    if branch:
        label = f"{label} ({branch})"
    try:
        import streamlit as st_mod

        st_version = st_mod.__version__
    except Exception:
        st_version = ""
    if st_version:
        label = f"{label} · st {st_version}"
    st.markdown(
        f'<div class="rro-deploy-version">Deploy: {html.escape(label)}</div>',
        unsafe_allow_html=True,
    )


def render_performance_sidebar_button(is_active: bool) -> None:
    """Open the monthly performance view from the sidebar."""
    if st.button(
        "Performance per month",
        type="tertiary" if is_active else "primary",
        use_container_width=True,
        key="nav_performance",
    ):
        st.session_state.dashboard_page = "performance"
        st.rerun()


def render_filter_page_sidebar_button(is_active: bool) -> None:
    """Return to the main search/filter page from the sidebar."""
    if st.button(
        "Filter posts",
        type="tertiary" if is_active else "primary",
        use_container_width=True,
        key="nav_filter_page",
    ):
        st.session_state.dashboard_page = "search"
        st.rerun()


def render_comparison_sidebar_button(is_active: bool) -> None:
    """Open the social competitor comparison page from the sidebar."""
    if st.button(
        "Social vergelijking",
        type="tertiary" if is_active else "primary",
        icon=":material/compare:",
        use_container_width=True,
        key="nav_comparison",
    ):
        st.session_state.dashboard_page = "comparison"
        st.rerun()


def render_weekly_report_sidebar_button(is_active: bool) -> None:
    """Open the weekly results page from the sidebar."""
    if st.button(
        "Weekrapport",
        type="tertiary" if is_active else "primary",
        icon=":material/calendar_month:",
        use_container_width=True,
        key="nav_weekly",
    ):
        st.session_state.dashboard_page = "weekly"
        st.rerun()


def render_image_test_sidebar_button(is_active: bool) -> None:
    """Open the local image comparison page from the sidebar."""
    if st.button(
        "Beeldtest",
        type="tertiary" if is_active else "primary",
        icon=":material/image:",
        use_container_width=True,
        key="nav_image_test",
    ):
        st.session_state.dashboard_page = "image_test"
        st.rerun()


def render_ai_settings_sidebar_button(is_active: bool) -> None:
    """Open the AI connection and prompt page from the sidebar."""
    if st.button(
        "AI-koppeling",
        type="tertiary" if is_active else "primary",
        icon=":material/tune:",
        use_container_width=True,
        key="nav_ai",
    ):
        st.session_state.dashboard_page = "ai"
        st.rerun()


def render_sidebar_stats(totals: dict) -> None:
    """Render sidebar sync statistics with icons."""
    st.markdown('<div class="rro-sidebar-title">Synchronisatie</div>', unsafe_allow_html=True)

    stats = [
        (INSTAGRAM_ICON, "Instagram posts", totals.get("instagram_posts", 0)),
        (STAT_COMMENT_ICON, "Instagram comments", totals.get("instagram_comments", 0)),
        (FACEBOOK_ICON, "Facebook posts", totals.get("facebook_posts", 0)),
        (STAT_COMMENT_ICON, "Facebook comments", totals.get("facebook_comments", 0)),
    ]
    rows = []
    for icon, label, value in stats:
        rows.append(
            '<div class="rro-stat-row">'
            f'<span class="rro-stat-icon">{icon}</span>'
            f'<span class="rro-stat-label">{html.escape(label)}</span>'
            f'<span class="rro-stat-value">{html.escape(str(value))}</span>'
            "</div>"
        )
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.markdown(
        '<div class="rro-sync-metrics-note">'
        "<strong>n.b.</strong> = nog niet opgehaald uit Meta "
        "(niet hetzelfde als 0). "
        "Data betreft alleen de afgelopen 1,5 jaar."
        "</div>",
        unsafe_allow_html=True,
    )
    _render_deploy_version()


def render_sync_result(stats) -> None:
    """Render last sync run counters and errors in the sidebar."""
    if stats is None:
        return

    st.markdown('<div class="rro-sidebar-title">Laatste sync</div>', unsafe_allow_html=True)
    lines = [
        f"Instagram posts toegevoegd: {stats.instagram_posts_added}",
        f"Instagram posts bijgewerkt: {stats.instagram_posts_updated}",
        f"Instagram comments toegevoegd: {stats.instagram_comments_added}",
        f"Instagram comments bijgewerkt: {stats.instagram_comments_updated}",
        f"Facebook posts toegevoegd: {stats.facebook_posts_added}",
        f"Facebook posts bijgewerkt: {stats.facebook_posts_updated}",
        f"Facebook comments toegevoegd: {stats.facebook_comments_added}",
        f"Facebook comments bijgewerkt: {stats.facebook_comments_updated}",
    ]
    insights_ok = getattr(stats, "insights_ok", None)
    insights_failed = getattr(stats, "insights_failed", None)
    if insights_ok is not None:
        lines.append(f"Insights bijgewerkt: {insights_ok}")
    if insights_failed:
        lines.append(f"Insights mislukt: {insights_failed}")
    unavailable = getattr(stats, "posts_marked_unavailable", None)
    if unavailable:
        lines.append(f"Posts niet meer beschikbaar: {unavailable}")
    for line in lines:
        st.caption(line)

    if stats.errors:
        st.warning("Sync voltooid met waarschuwingen.")
        for error in stats.errors:
            st.error(error)
    else:
        st.success("Synchronisatie voltooid.")


MIN_QUERY_LENGTH = 3


def render_search_form() -> tuple[str, set[str], set[str], tuple[date, ...]]:
    """Render live search controls (no mandatory submit; searches while typing)."""
    if "date_range_filter" not in st.session_state:
        st.session_state["date_range_filter"] = ()
    st.session_state.pop("date_filter", None)
    st.session_state.pop("selected_date", None)

    st.markdown('<div class="rro-search-form-header"><h3>Zoeken</h3></div>', unsafe_allow_html=True)

    query = st.text_input(
        "Zoekterm",
        placeholder="Typ minstens 3 tekens...",
        label_visibility="collapsed",
        key="search_query",
    )

    with st.container():
        st.markdown(
            '<div class="rro-filter-block-anchor" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        filter_cols = st.columns(3, gap="small")
        with filter_cols[0]:
            platform_labels = st.multiselect(
                "Platforms",
                ["Instagram", "Facebook"],
                default=["Instagram", "Facebook"],
            )
        with filter_cols[1]:
            type_labels = st.multiselect(
                "Type",
                ["Comments", "Tags", "Hashtags", "Captions"],
                default=["Comments", "Tags", "Hashtags", "Captions"],
            )
        with filter_cols[2]:
            date_range = st.date_input(
                "Datums",
                format="YYYY/MM/DD",
                key="date_range_filter",
            )
        st.button("Zoeken")
        st.markdown(
            '<div class="rro-search-button-anchor" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )

    platforms, entity_types = resolve_checkbox_filters(
        instagram="Instagram" in platform_labels,
        facebook="Facebook" in platform_labels,
        comments="Comments" in type_labels,
        tags="Tags" in type_labels,
        hashtags="Hashtags" in type_labels,
        captions="Captions" in type_labels,
    )
    return query, platforms, entity_types, date_range


def _platform_badge(platform: str) -> str:
    if platform == "instagram":
        return f'<span class="badge badge-instagram badge-platform">{INSTAGRAM_ICON}<span>Instagram</span></span>'
    return f'<span class="badge badge-facebook badge-platform">{FACEBOOK_ICON}<span>Facebook</span></span>'


def _content_type_badge(label: str) -> str:
    icon = COMMENT_ICON if label == "Comment" else POST_ICON
    return f'<span class="badge badge-content badge-type">{icon}<span>{label}</span></span>'


def _unavailable_badge() -> str:
    return (
        '<span class="badge badge-unavailable badge-match">'
        "Niet meer beschikbaar"
        "</span>"
    )


_MATCH_BADGE_ORDER = (
    ("caption", "Caption", "badge-caption"),
    ("hashtag", "Hashtag", "badge-hashtag"),
    ("tag", "Tag", "badge-tag"),
)


def _match_badges(result: SearchResult, query: str) -> str:
    """Render Caption/Hashtag/Tag badges explaining why a result matched."""
    if not query or not query.strip():
        return ""
    matches = detect_match_types(result, query)
    badges = [
        f'<span class="badge {css} badge-match">{label}</span>'
        for key, label, css in _MATCH_BADGE_ORDER
        if key in matches
    ]
    return "".join(badges)


_STAT_DISPLAY_ORDER = (
    ("views", VIEW_STAT_ICON, "Weergaven"),
    ("likes", HEART_STAT_ICON, "Likes"),
    ("comments", MESSAGE_STAT_ICON, "Reacties"),
    ("saves", SAVE_STAT_ICON, "Opgeslagen"),
    ("shares", SHARE_STAT_ICON, "Gedeeld"),
)

# Shown when a metric is expected but not yet present in the local DB.
_STAT_NOT_SYNCED = (
    '<span class="rro-stat-value-inline rro-stat-missing" '
    'title="n.b. = nog niet opgehaald uit Meta (niet hetzelfde als 0)">'
    "n.b.</span>"
)


def _stat_items_html(
    stats: dict[str, int],
    *,
    show_missing: bool = False,
    exclude_keys: frozenset[str] | None = None,
) -> list[str]:
    """Build labeled stat spans. With show_missing, always show the 5 core metrics."""
    excluded = exclude_keys or frozenset()
    items: list[str] = []
    for key, icon, label in _STAT_DISPLAY_ORDER:
        if key in excluded:
            continue
        if key not in stats:
            if not show_missing:
                continue
            value_html = _STAT_NOT_SYNCED
        else:
            value_html = (
                f'<span class="rro-stat-value-inline">{html.escape(str(stats[key]))}</span>'
            )
        items.append(
            '<span class="rro-stat">'
            f"{icon}"
            f'<span class="rro-stat-label-inline">{html.escape(label)}</span>'
            f"{value_html}"
            "</span>"
        )
    return items


def _stats_html(result: SearchResult, highlight_metric: str | None = None) -> str:
    """Render engagement stats for a result card."""
    stats = get_engagement_stats(result)
    if result.entity_type != "post":
        items = _stat_items_html(stats, show_missing=False)
        if not items:
            return ""
        return f'<div class="rro-card-stats">{"".join(items)}</div>'

    # Facebook: never show Opgeslagen (not in Meta API).
    # Missing expected metrics show as "n.b." (= nog niet opgehaald, niet 0).
    if result.platform == "facebook":
        exclude = frozenset({"saves"})
        force_missing = frozenset({"views", "shares"})
    else:
        exclude = frozenset()
        force_missing = frozenset({"views", "saves", "shares"})

    items: list[str] = []
    for key, icon, label in _STAT_DISPLAY_ORDER:
        if key in exclude:
            continue
        if key in stats:
            value_html = (
                f'<span class="rro-stat-value-inline'
                f'{" rro-stat-value-inline--highlight" if key == highlight_metric else ""}">'
                f"{html.escape(str(stats[key]))}</span>"
            )
        elif key in force_missing:
            value_html = _STAT_NOT_SYNCED
        else:
            continue
        items.append(
            '<span class="rro-stat">'
            f"{icon}"
            f'<span class="rro-stat-label-inline">{html.escape(label)}</span>'
            f"{value_html}"
            "</span>"
        )
    if not items:
        return ""
    return f'<div class="rro-card-stats">{"".join(items)}</div>'


def render_result_card(
    result: SearchResult,
    query: str = "",
    *,
    full_text: bool = False,
    rank_banner_html: str | None = None,
    highlight_metric: str | None = None,
) -> None:
    """Render one search result card in RRO style.

    Thumbnails are shown via ``st.image`` from local files so Streamlit does not
    strip/break large data-URI ``<img>`` tags inside markdown.
    """
    if full_text:
        highlighted_text = highlight_hashtags_in_text(result.text)
        text_class = "rro-card-text rro-card-text--full"
    else:
        highlighted_text = highlight_and_snippet(result.text, query)
        text_class = "rro-card-text"
    safe_date = html.escape(_format_date(result.published_at))
    unavailable = is_result_unavailable(result)

    if result.entity_type == "post":
        thumb_post_id: int | None = int(result.entity_id)
    else:
        thumb_post_id = get_comment_parent_post_id(int(result.entity_id))
    image_path = get_local_image_path_for_result(result)
    thumb_uri = local_media_data_uri(thumb_post_id) if thumb_post_id else None
    logger.debug(
        "Result image entity=%s/%s path=%s uri=%s",
        result.entity_type,
        result.entity_id,
        image_path,
        bool(thumb_uri),
    )

    if unavailable:
        action_html = (
            '<div class="rro-btn-disabled" '
            'title="Deze post is verwijderd of niet meer bereikbaar op het platform">'
            "Niet meer beschikbaar"
            "</div>"
        )
    elif result.permalink:
        safe_link = html.escape(result.permalink, quote=True)
        action_html = (
            f'<a class="rro-btn-link" href="{safe_link}" target="_blank" '
            f'rel="noopener noreferrer">Bekijk origineel</a>'
        )
    else:
        action_html = '<div class="rro-btn-disabled">Geen link</div>'

    content_type_label = get_content_type_for_result(result)
    badges_html = (
        f"{_platform_badge(result.platform)}"
        f"{_content_type_badge(content_type_label)}"
        f"{_unavailable_badge() if unavailable else ''}"
        f"{_match_badges(result, query)}"
    )
    stats_html = _stats_html(result, highlight_metric=highlight_metric)
    unavailable_html = ""
    if unavailable:
        unavailable_html = (
            '<div class="rro-unavailable-notice">'
            "Deze post is verwijderd of niet meer bereikbaar op het platform."
            "</div>"
        )
    body_html = (
        f'<div class="rro-card-badges">{badges_html}</div>'
        f'<div class="rro-card-date">{safe_date}</div>'
        f"{unavailable_html}"
        f'<div class="{text_class}">{highlighted_text}</div>'
    )

    with st.container(border=True):
        if rank_banner_html:
            st.markdown(rank_banner_html, unsafe_allow_html=True)
        st.markdown(
            '<div class="rro-result-card-marker" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        thumb_col, body_col, action_col = st.columns([1.45, 4.0, 1.25], gap="small")
        with thumb_col:
            if thumb_uri:
                # Embed JPEG bytes in the page. Do not use st.image: Render cannot
                # load Streamlit's /_stcore/media URLs or Instagram CDN links.
                st.html(
                    '<img class="rro-thumb" alt="" '
                    f'src="{thumb_uri}" '
                    'style="width:100%;aspect-ratio:1/1;object-fit:cover;'
                    "border-radius:8px;border:1px solid rgba(242,240,236,0.12);"
                    'display:block;background:#4B5560;" />',
                    width="stretch",
                )
            else:
                st.markdown(
                    '<div class="rro-thumb-placeholder">Geen thumbnail</div>',
                    unsafe_allow_html=True,
                )
        with body_col:
            st.markdown(body_html, unsafe_allow_html=True)
        with action_col:
            st.markdown(action_html, unsafe_allow_html=True)
        # Stats full-width under the row so they are not clipped in a narrow column.
        if stats_html:
            st.markdown(
                (
                    '<div class="rro-card-stats-wrap">'
                    f"{stats_html}"
                    '<div class="rro-card-stats-spacer" aria-hidden="true"></div>'
                    "</div>"
                ),
                unsafe_allow_html=True,
            )


def _comment_row_html(comment: SearchResult, query: str) -> str:
    """Render a single comment row used inside a grouped post card."""
    safe_date = html.escape(_format_date(comment.published_at))
    highlighted = highlight_and_snippet(comment.text, query)
    match_html = _match_badges(comment, query)
    comment_badge = '<span class="badge badge-comment badge-match">Comment</span>'
    return (
        '<div class="rro-comment-item">'
        f'<div class="rro-comment-item-head">{comment_badge}{match_html}'
        f'<span class="rro-comment-date">{safe_date}</span></div>'
        f'<div class="rro-comment-text">{highlighted}</div>'
        "</div>"
    )


def render_comment_group(comments: list[SearchResult], query: str) -> None:
    """Render comments nested under their parent post card."""
    if not comments:
        return
    rows = "".join(_comment_row_html(comment, query) for comment in comments)
    group_html = (
        '<div class="rro-comment-group">'
        f'<div class="rro-comment-group-title">Reacties ({len(comments)})</div>'
        f"{rows}"
        "</div>"
    )
    st.markdown(group_html, unsafe_allow_html=True)


def render_comment_card(comment: SearchResult, query: str = "") -> None:
    """Render a standalone comment as a distinct, smaller card."""
    platform_label = "Instagram" if comment.platform == "instagram" else "Facebook"
    safe_date = html.escape(_format_date(comment.published_at))
    highlighted = highlight_and_snippet(comment.text, query)
    match_html = _match_badges(comment, query)

    parent_caption = get_comment_parent_caption(comment.entity_id)
    parent_html = ""
    if parent_caption.strip():
        preview = parent_caption.strip()
        if len(preview) > 140:
            preview = preview[:140].rstrip() + "..."
        parent_html = (
            f'<div class="rro-comment-parent">Op post: {html.escape(preview)}</div>'
        )

    if comment.permalink:
        safe_link = html.escape(comment.permalink, quote=True)
        action_html = (
            f'<a class="rro-comment-link" href="{safe_link}" target="_blank" '
            f'rel="noopener noreferrer">Bekijk post</a>'
        )
    else:
        action_html = ""

    comment_badge = '<span class="badge badge-comment badge-match">Comment</span>'
    stats_html = _stats_html(comment)
    card_html = (
        '<div class="rro-comment-card">'
        f'<div class="rro-comment-label">{COMMENT_ICON}'
        f"<span>Reactie op {platform_label}-post</span></div>"
        f'<div class="rro-comment-badges">{comment_badge}{match_html}'
        f'<span class="rro-comment-date">{safe_date}</span></div>'
        f'<div class="rro-comment-text">{highlighted}</div>'
        f"{stats_html}"
        f"{parent_html}"
        f"{action_html}"
        "</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)


def render_results_section(
    results: list[SearchResult],
    *,
    query: str = "",
    content_count: int | None = None,
    comment_count: int | None = None,
    title: str | None = None,
) -> None:
    """Render results inside the main dashboard card (grows with content)."""
    _ = content_count, comment_count  # kept for backward compatibility; no longer shown
    # Do NOT wrap widgets in split open/close HTML divs — Streamlit renders each
    # markdown as its own node; that pattern cannot create a real parent wrapper.
    st.markdown(
        '<div class="rro-results-section" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    render_results_header(results, title=title)
    if not results:
        st.info("Geen resultaten gevonden in de lokale database.")
    else:
        render_results(results, query=query)


def render_results(results: list[SearchResult], query: str | None = None) -> None:
    """Render results, grouping comments under their parent post when present."""
    query = query or ""
    post_by_id = {
        result.entity_id: result
        for result in results
        if result.entity_type == "post"
    }

    grouped: dict[int, list[SearchResult]] = {}
    orphans: set[int] = set()
    for result in results:
        if result.entity_type != "comment":
            continue
        parent_id = get_comment_parent_post_id(result.entity_id)
        if parent_id is not None and parent_id in post_by_id:
            grouped.setdefault(parent_id, []).append(result)
        else:
            orphans.add(result.entity_id)

    for result in results:
        if result.entity_type == "post":
            render_result_card(result, query)
            render_comment_group(grouped.get(result.entity_id, []), query)
        elif result.entity_id in orphans:
            render_comment_card(result, query)


def _aggregate_engagement(results: list[SearchResult]) -> dict[str, int]:
    """Sum available engagement stats across the visible results."""
    totals: dict[str, int] = {}
    for result in results:
        for key, value in get_engagement_stats(result).items():
            totals[key] = totals.get(key, 0) + int(value)
    return totals


def _totals_html(results: list[SearchResult]) -> str:
    """Render engagement totals for the results section."""
    totals = _aggregate_engagement(results)
    # Opgeslagen is Instagram-only; hide from totals when no IG posts contribute.
    post_platforms = {r.platform for r in results if r.entity_type == "post"}
    exclude = frozenset({"saves"}) if "instagram" not in post_platforms else None
    items = _stat_items_html(totals, show_missing=False, exclude_keys=exclude)
    if not items:
        return ""
    joined = ' <span class="rro-totals-sep">&middot;</span> '.join(items)
    note = ""
    if "views" not in totals:
        note = (
            '<div class="rro-results-views-note">'
            "<strong>n.b.</strong> = nog niet opgehaald uit Meta (niet hetzelfde als 0)."
            "</div>"
        )
    return f'<div class="rro-results-totals">Totaal engagement: {joined}</div>{note}'


def render_results_header(
    results: list[SearchResult] | None = None,
    *,
    title: str | None = None,
) -> None:
    """Render results header with count and engagement totals."""
    total = len(results or [])
    totals_html = _totals_html(results or [])
    heading = title or f"Resultaten ({total})"
    st.markdown(
        '<div class="rro-results-header">'
        f"<h2>{html.escape(heading)}</h2>"
        "</div>"
        f"{totals_html}",
        unsafe_allow_html=True,
    )
