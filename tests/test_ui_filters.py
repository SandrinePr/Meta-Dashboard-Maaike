"""Tests for UI checkbox filter logic and hashtag rendering."""

from datetime import date
from pathlib import Path

from db.database import get_connection
from db.repository import rebuild_search_index, sync_post_hashtags, upsert_account, upsert_post
from search.engine import SearchResult, search
from ui.components import (
    filter_results,
    highlight_and_snippet,
    highlight_hashtags_in_text,
    matches_hashtag_query,
    resolve_checkbox_filters,
)


def _result(
    platform: str,
    entity_type: str,
    *,
    text: str = "x",
    hashtags: list[str] | None = None,
) -> SearchResult:
    return SearchResult(
        platform=platform,
        entity_type=entity_type,
        entity_id=1,
        published_at="2026-07-01T00:00:00+00:00",
        text=text,
        hashtags=hashtags or [],
        permalink=None,
        thumbnail_url=None,
    )


def test_resolve_checkbox_filters_defaults_to_all_when_none_selected() -> None:
    platforms, types = resolve_checkbox_filters(
        instagram=False,
        facebook=False,
        comments=False,
        tags=False,
        hashtags=False,
        captions=False,
    )
    assert platforms == {"instagram", "facebook"}
    assert types == {"comment", "tag", "hashtag", "caption"}


def test_resolve_checkbox_filters_has_no_posts_option() -> None:
    platforms, types = resolve_checkbox_filters(
        instagram=True,
        facebook=True,
        comments=True,
        tags=False,
        hashtags=False,
        captions=False,
    )
    assert "post" not in types
    assert types == {"comment"}


def test_filter_results_applies_platform_and_type() -> None:
    results = [
        _result("instagram", "post"),
        _result("facebook", "comment"),
    ]
    filtered = filter_results(results, {"instagram"}, {"post"}, "x")
    assert len(filtered) == 1
    assert filtered[0].platform == "instagram"


def test_filter_results_hashtags_only_matches_hashtag_posts() -> None:
    results = [
        _result("instagram", "post", text="Yava #crazy", hashtags=["crazy"]),
        _result("instagram", "post", text="hello world", hashtags=["other"]),
        _result("instagram", "comment", text="crazy comment"),
    ]
    filtered = filter_results(results, {"instagram"}, {"hashtag"}, "crazy")
    assert len(filtered) == 1
    assert filtered[0].text == "Yava #crazy"


def test_filter_results_posts_off_hashtags_on_still_shows_hashtag_posts() -> None:
    results = [
        _result("instagram", "post", text="Yava #crazy", hashtags=["crazy"]),
        _result("instagram", "post", text="plain post", hashtags=[]),
    ]
    filtered = filter_results(results, {"instagram"}, {"hashtag"}, "#crazy")
    assert len(filtered) == 1
    assert filtered[0].hashtags == ["crazy"]


def test_filter_results_tags_only_matches_mention_posts() -> None:
    results = [
        _result("instagram", "post", text="Nova & Pip @sandrine.prum", hashtags=[]),
        _result("instagram", "post", text="no mention here", hashtags=[]),
    ]
    filtered = filter_results(results, {"instagram"}, {"tag"}, "@sandrine.prum")
    assert len(filtered) == 1
    assert filtered[0].text == "Nova & Pip @sandrine.prum"


def test_filter_results_captions_only_matches_plain_text() -> None:
    results = [
        _result("instagram", "post", text="lovely sunset walk", hashtags=[]),
        _result("instagram", "post", text="only #sunset tag", hashtags=["sunset"]),
    ]
    filtered = filter_results(results, {"instagram"}, {"caption"}, "sunset")
    assert len(filtered) == 1
    assert filtered[0].text == "lovely sunset walk"


def test_filter_results_comments_still_work_with_hashtags() -> None:
    results = [
        _result("facebook", "comment", text="brand mention"),
        _result("instagram", "post", text="Yava #brand", hashtags=["brand"]),
    ]
    filtered = filter_results(
        results, {"instagram", "facebook"}, {"comment", "hashtag"}, "brand"
    )
    assert len(filtered) == 2


def test_matches_hashtag_query_normalizes_hash_prefix() -> None:
    result = _result("instagram", "post", hashtags=["culimaat"])
    assert matches_hashtag_query(result, "#culimaat")
    assert matches_hashtag_query(result, "culimaat")


def test_highlight_hashtags_in_text_escapes_and_wraps() -> None:
    rendered = highlight_hashtags_in_text('Yava <script>#crazy</script> & #fun')
    assert "<script>" not in rendered
    assert 'Yava &lt;script&gt;<span class="hashtag">#crazy</span>&lt;/script&gt; &amp; <span class="hashtag">#fun</span>' == rendered


def test_highlight_wraps_mentions() -> None:
    rendered = highlight_hashtags_in_text("Nova & Pip @sandrine.prum #cute")
    assert '<span class="mention">@sandrine.prum</span>' in rendered
    assert '<span class="hashtag">#cute</span>' in rendered


def test_highlight_and_snippet_wraps_query_term() -> None:
    rendered = highlight_and_snippet("we spraken over CULIMAAT vandaag", "CULIMAAT")
    assert '<span class="text-match">CULIMAAT</span>' in rendered


def test_highlight_and_snippet_is_case_insensitive() -> None:
    rendered = highlight_and_snippet("Over culimaat gesproken", "CULIMAAT")
    assert '<span class="text-match">culimaat</span>' in rendered


def test_highlight_hashtag_match_wraps_whole_token_no_nested_span() -> None:
    rendered = highlight_and_snippet("kijk #CULIMAAT nu", "culimaat")
    assert '<span class="hashtag hashtag-match">#CULIMAAT</span>' in rendered
    assert "text-match" not in rendered


def test_highlight_mention_match_wraps_whole_token_no_nested_span() -> None:
    rendered = highlight_and_snippet("cc @sandrine.prum", "sandrine")
    assert '<span class="mention mention-match">@sandrine.prum</span>' in rendered
    assert "text-match" not in rendered


def test_non_matching_hashtag_has_no_match_class() -> None:
    rendered = highlight_and_snippet("iets #anders hier CULIMAAT", "CULIMAAT")
    assert '<span class="hashtag">#anders</span>' in rendered
    assert '<span class="text-match">CULIMAAT</span>' in rendered


def test_plain_word_still_uses_yellow_background_highlight() -> None:
    rendered = highlight_and_snippet("Big boy Yasuo here", "yasuo")
    assert '<span class="text-match">Yasuo</span>' in rendered


def test_snippet_truncates_long_text_with_ellipsis() -> None:
    text = ("x" * 80) + " gisteren besproken over CULIMAAT en volgende week " + ("y" * 80)
    rendered = highlight_and_snippet(text, "CULIMAAT")
    assert rendered.startswith("... ")
    assert rendered.endswith(" ...")
    assert '<span class="text-match">CULIMAAT</span>' in rendered
    assert "xxxxxxxx" not in rendered.split("CULIMAAT")[0][-20:]


def test_snippet_keeps_short_text_intact() -> None:
    rendered = highlight_and_snippet("korte tekst met CULIMAAT erin", "CULIMAAT")
    assert not rendered.startswith("...")
    assert not rendered.endswith("...")


def test_highlight_and_snippet_escapes_html() -> None:
    rendered = highlight_and_snippet("<script>alert(1)</script> CULIMAAT", "CULIMAAT")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_detect_match_types_combines_caption_hashtag_tag() -> None:
    from search.engine import detect_match_types

    result = _result(
        "instagram",
        "post",
        text="cute Nova @sandrine.prum #cute",
        hashtags=["cute"],
    )
    assert detect_match_types(result, "cute") == {"caption", "hashtag"}
    assert detect_match_types(result, "@sandrine.prum") == {"tag"}
    assert detect_match_types(result, "sandrine.prum") == {"tag"}


def test_detect_match_types_comment_flag() -> None:
    from search.engine import detect_match_types

    result = _result("facebook", "comment", text="great post")
    assert "comment" in detect_match_types(result, "great")


def test_comment_never_gets_caption_badge() -> None:
    from search.engine import detect_match_types

    result = _result("instagram", "comment", text="great sunset here")
    assert detect_match_types(result, "sunset") == {"comment"}


def test_comment_hashtag_uses_own_text_not_inherited_hashtags() -> None:
    from search.engine import detect_match_types

    # hashtags list is inherited from parent post, but comment text has no '#cute'
    result = _result("instagram", "comment", text="so nice", hashtags=["cute"])
    assert detect_match_types(result, "cute") == {"comment"}

    # comment text with its own hashtag should produce a hashtag match
    with_tag = _result("instagram", "comment", text="love this #cute", hashtags=[])
    assert detect_match_types(with_tag, "cute") == {"comment", "hashtag"}


def test_comment_mention_produces_tag_badge() -> None:
    from search.engine import detect_match_types

    result = _result("instagram", "comment", text="cc @sandrine.prum", hashtags=[])
    assert detect_match_types(result, "@sandrine.prum") == {"comment", "tag"}


def _seed_search_posts(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    # Schema only — do not call initialize_database (that copies the full seed DB
    # and makes "match" queries hit unrelated Art-of-Living rows).
    from db.migrate import apply_comparison_schema

    schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    with get_connection(db_path) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        apply_comparison_schema(conn)
        conn.commit()

    with get_connection() as conn:
        account_id = upsert_account(conn, platform="instagram", external_id="ig-1")
        for external_id, text, published_at in (
            ("post-1", "match on first day", "2026-07-01T10:00:00+00:00"),
            ("post-2", "match on second day", "2026-07-02T10:00:00+00:00"),
            ("post-3", "alpha boundary", "2026-03-01T10:00:00+00:00"),
            ("post-4", "omega boundary", "2026-07-07T10:00:00+00:00"),
            ("post-5", "outside boundary", "2026-08-01T10:00:00+00:00"),
        ):
            post = upsert_post(
                conn,
                platform="instagram",
                external_id=external_id,
                account_id=account_id,
                content_type="post",
                text=text,
                permalink=f"https://instagram.com/p/{external_id}",
                media_url=None,
                thumbnail_url=None,
                media_type="IMAGE",
                published_at=published_at,
                raw_json="{}",
            )
            sync_post_hashtags(conn, post.row_id, [])
        rebuild_search_index(conn)
        conn.commit()


def test_search_applies_single_date_filter(tmp_path: Path, monkeypatch) -> None:
    _seed_search_posts(tmp_path, monkeypatch)
    results = search(
        "match",
        platforms={"instagram"},
        entity_types={"post"},
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 1),
    )
    assert len(results) == 1
    assert results[0].text == "match on first day"


def test_search_applies_inclusive_date_range(tmp_path: Path, monkeypatch) -> None:
    _seed_search_posts(tmp_path, monkeypatch)
    results = search(
        "boundary",
        platforms={"instagram"},
        entity_types={"post"},
        start_date=date(2026, 3, 1),
        end_date=date(2026, 7, 7),
    )
    assert len(results) == 2
    assert {item.text for item in results} == {"alpha boundary", "omega boundary"}


def test_search_skips_date_filter_when_range_empty(tmp_path: Path, monkeypatch) -> None:
    _seed_search_posts(tmp_path, monkeypatch)
    results = search(
        "match",
        platforms={"instagram"},
        entity_types={"post", "comment"},
    )
    assert len(results) == 2


