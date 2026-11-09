"""Weekly report page. Reads stored measurements and saved reports only."""

from __future__ import annotations

import html
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from ai.analyze import NOT_CONFIGURED_MESSAGE, can_request_analysis, run_analysis
from ai.config import is_configured
from analytics.weekly_report import (
    NOT_AVAILABLE,
    STAND_LABEL,
    build_weekly_snapshot,
    format_avg,
    format_delta,
    format_int,
    format_published,
    previous_complete_week,
    week_containing,
)
from db.comparison_repository import ensure_default_comparison_accounts, get_preferences
from db.database import get_connection, initialize_database
from db.weekly_report_repository import (
    get_prompts,
    get_weekly_report,
    list_weekly_reports,
    save_analysis,
    save_weekly_report,
)
from reports.weekly_html import build_weekly_report_html

AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def _selection() -> tuple[int | None, list[str]]:
    initialize_database()
    with get_connection() as conn:
        ensure_default_comparison_accounts(conn)
        own_id, competitors = get_preferences(conn)
        conn.commit()
    if st.session_state.get("comparison_own_account_id"):
        own_id = st.session_state.comparison_own_account_id
    if st.session_state.get("comparison_competitors") is not None:
        competitors = list(st.session_state.comparison_competitors)
    return own_id, competitors


def _table(headers: list[str], body_rows: list[str]) -> None:
    head = "".join(f"<th>{html.escape(label)}</th>" for label in headers)
    st.markdown(
        "<div class='rro-comparison-table-wrap'><table class='rro-comparison-table'>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _account_cells(block: dict) -> str:
    stand = block.get("followers_stand")
    stand_text = format_int(stand) if stand is not None else NOT_AVAILABLE
    return (
        f"<td>{html.escape(str(block.get('display_name') or NOT_AVAILABLE))}</td>"
        f"<td class='rro-num'>{html.escape(format_published(block.get('posts_published'), block.get('posts_published_coverage', 'unavailable')))}</td>"
        f"<td class='rro-num'>{html.escape(stand_text)}</td>"
        f"<td class='rro-num'>{html.escape(format_delta(block.get('followers_delta'), block.get('followers_delta_status', 'unavailable')))}</td>"
        f"<td class='rro-num'>{html.escape(format_delta(block.get('likes_delta'), block.get('interaction_status', 'unavailable')))}</td>"
        f"<td class='rro-num'>{html.escape(format_delta(block.get('comments_delta'), block.get('interaction_status', 'unavailable')))}</td>"
    )


def _render_snapshot(snapshot: dict) -> None:
    own = snapshot.get("own")
    st.markdown('<h3 class="rro-comparison-section">Weekcijfers</h3>', unsafe_allow_html=True)
    st.caption(
        "Geplaatst telt posts met een publicatiedatum in deze week. "
        "Toename telt alleen het verschil tussen twee opgeslagen metingen."
    )
    if not own:
        st.markdown(
            f'<div class="rro-empty-state">{html.escape(NOT_AVAILABLE)}</div>',
            unsafe_allow_html=True,
        )
    else:
        _table(
            [
                "Account",
                "Geplaatst deze week",
                "Volgersstand in de week",
                "Volgersverschil",
                "Like-toename",
                "Reactie-toename",
            ],
            [f"<tr>{_account_cells(own)}</tr>"],
        )
        st.caption(str(own.get("followers_note") or ""))
        st.caption(str(own.get("interaction_note") or ""))

    st.markdown(
        '<h3 class="rro-comparison-section">Posts geplaatst deze week</h3>',
        unsafe_allow_html=True,
    )
    published = snapshot.get("published_posts") or []
    if not published:
        st.markdown(
            '<div class="rro-empty-state">Geen opgeslagen posts met een publicatiedatum in deze week, of niet beschikbaar.</div>',
            unsafe_allow_html=True,
        )
    else:
        body = []
        for post in published:
            if post.get("stand_status") == "ok":
                likes = format_int(post.get("stand_likes"))
                comments = format_int(post.get("stand_comments"))
            else:
                likes = NOT_AVAILABLE
                comments = NOT_AVAILABLE
            opening = post.get("opening_line") or NOT_AVAILABLE
            link = post.get("permalink")
            link_html = (
                f"<a href='{html.escape(str(link))}' target='_blank' rel='noopener'>openen</a>"
                if link
                else NOT_AVAILABLE
            )
            body.append(
                "<tr>"
                f"<td>{html.escape(str(post.get('published_display') or ''))}</td>"
                f"<td>{html.escape(str(post.get('content_label') or ''))}</td>"
                f"<td>{html.escape(str(opening))}</td>"
                f"<td class='rro-num'>{html.escape(likes)}</td>"
                f"<td class='rro-num'>{html.escape(comments)}</td>"
                f"<td>{html.escape(STAND_LABEL)}</td>"
                f"<td>{link_html}</td>"
                "</tr>"
            )
        _table(
            ["Geplaatst", "Soort", "Openingszin", "Likes, stand", "Reacties, stand", "Betekenis", "Link"],
            body,
        )

    st.markdown(
        '<h3 class="rro-comparison-section">Best presterende posts</h3>',
        unsafe_allow_html=True,
    )
    st.caption(str(snapshot.get("ranking_basis") or ""))
    ranked = snapshot.get("ranked_posts") or []
    if not ranked:
        st.markdown(
            '<div class="rro-empty-state">nog onvoldoende meetgegevens</div>',
            unsafe_allow_html=True,
        )
    else:
        total = int(snapshot.get("ranked_total") or len(ranked))
        if total > len(ranked):
            st.caption(f"Top {len(ranked)} van {total} posts met een bekende toename.")
        body = []
        for post in ranked:
            body.append(
                "<tr>"
                f"<td class='rro-num'>{html.escape(str(post.get('rank')))}</td>"
                f"<td>{html.escape(str(post.get('published_display') or ''))}</td>"
                f"<td>{html.escape(str(post.get('content_label') or ''))}</td>"
                f"<td>{html.escape(str(post.get('opening_line') or NOT_AVAILABLE))}</td>"
                f"<td class='rro-num'>{html.escape(format_delta(post.get('likes_delta'), 'ok'))}</td>"
                f"<td class='rro-num'>{html.escape(format_delta(post.get('comments_delta'), 'ok'))}</td>"
                f"<td class='rro-num'>{html.escape(format_delta(post.get('interaction_delta'), 'ok'))}</td>"
                f"<td>{html.escape(str(post.get('basis_label') or ''))}</td>"
                "</tr>"
            )
        _table(
            ["#", "Geplaatst", "Soort", "Openingszin", "Likes", "Reacties", "Som", "Waarop gebaseerd"],
            body,
        )

    st.markdown(
        '<h3 class="rro-comparison-section">Contentbeschrijving</h3>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Een beschrijving bestaat alleen als een model de bestanden echt heeft bekeken. "
        "Zonder AI-sleutel blijft de status ‘Niet geanalyseerd’."
    )
    coverage_rows = snapshot.get("published_posts") or []
    if not coverage_rows:
        st.markdown(
            '<div class="rro-empty-state">Niet geanalyseerd. Nog geen posts in deze week om te beschrijven.</div>',
            unsafe_allow_html=True,
        )
    else:
        body = []
        for post in coverage_rows:
            body.append(
                "<tr>"
                f"<td>{html.escape(str(post.get('published_display') or ''))}</td>"
                f"<td>{html.escape(str(post.get('content_label') or ''))}</td>"
                f"<td>{html.escape(str(post.get('content_coverage') or 'Niet geanalyseerd'))}</td>"
                f"<td>{html.escape(str(post.get('content_coverage_note') or ''))}</td>"
                "</tr>"
            )
        _table(["Geplaatst", "Soort", "Dekking", "Toelichting"], body)

    st.markdown(
        '<h3 class="rro-comparison-section">Vergelijking met concurrenten</h3>',
        unsafe_allow_html=True,
    )
    st.caption("Alleen cijfers uit opgeslagen metingen. Ontbrekende accounts blijven leeg van verzonnen cijfers.")
    competitors = snapshot.get("competitors") or []
    if not competitors:
        st.markdown(
            f'<div class="rro-empty-state">{html.escape(NOT_AVAILABLE)}</div>',
            unsafe_allow_html=True,
        )
    else:
        _table(
            [
                "Account",
                "Geplaatst deze week",
                "Volgersstand in de week",
                "Volgersverschil",
                "Like-toename",
                "Reactie-toename",
            ],
            [f"<tr>{_account_cells(block)}</tr>" for block in competitors],
        )

    st.markdown('<h3 class="rro-comparison-section">Soorten posts</h3>', unsafe_allow_html=True)
    st.caption(
        "Gemiddelden zijn berekend uit posts met twee bruikbare metingen. "
        "Een hoger gemiddelde betekent niet dat die soort altijd beter werkt."
    )
    content_types = snapshot.get("content_types") or []
    if not content_types:
        st.markdown(
            '<div class="rro-empty-state">nog onvoldoende meetgegevens</div>',
            unsafe_allow_html=True,
        )
    else:
        body = []
        for row in content_types:
            compared = (
                format_int(row.get("comparable_posts"))
                if row.get("performance_status") == "ok"
                else "nog onvoldoende meetgegevens"
            )
            average = (
                format_avg(row.get("interaction_avg"))
                if row.get("performance_status") == "ok"
                else "nog onvoldoende meetgegevens"
            )
            body.append(
                "<tr>"
                f"<td>{html.escape(str(row.get('label') or ''))}</td>"
                f"<td class='rro-num'>{html.escape(format_int(row.get('published_count')))}</td>"
                f"<td class='rro-num'>{html.escape(compared)}</td>"
                f"<td class='rro-num'>{html.escape(format_delta(row.get('interaction_delta'), row.get('performance_status', 'insufficient')))}</td>"
                f"<td class='rro-num'>{html.escape(average)}</td>"
                "</tr>"
            )
        _table(
            ["Soort", "Geplaatst deze week", "Posts met toename", "Interactietoename", "Gemiddelde"],
            body,
        )

    st.markdown('<h3 class="rro-comparison-section">Onderwerp en soort inhoud</h3>', unsafe_allow_html=True)
    st.caption(
        "Deze totalen komen uit opgeslagen beschrijvingen en de berekende toenames. "
        "Een verschil is geen bewezen oorzaak."
    )
    topic_groups = snapshot.get("topic_groups") or []
    if not topic_groups:
        st.markdown(
            '<div class="rro-empty-state">Nog geen beschreven posts om te vergelijken.</div>',
            unsafe_allow_html=True,
        )
    else:
        body = []
        for row in topic_groups:
            body.append(
                "<tr>"
                f"<td>{html.escape(str(row.get('topic') or ''))}</td>"
                f"<td>{html.escape(str(row.get('content_kind') or ''))}</td>"
                f"<td class='rro-num'>{html.escape(format_int(row.get('posts')))}</td>"
                f"<td class='rro-num'>{html.escape(format_int(row.get('likes_delta')))}</td>"
                f"<td class='rro-num'>{html.escape(format_int(row.get('comments_delta')))}</td>"
                "</tr>"
            )
        _table(["Onderwerp", "Soort inhoud", "Posts", "Like-toename", "Reactie-toename"], body)

    st.markdown(
        '<h3 class="rro-comparison-section">Berekende samenvatting</h3>',
        unsafe_allow_html=True,
    )
    st.markdown(html.escape(str(snapshot.get("summary") or NOT_AVAILABLE)))
    notes = snapshot.get("notes") or []
    if notes:
        items = "".join(f"<li>{html.escape(str(note))}</li>" for note in notes)
        st.markdown(f"<ul>{items}</ul>", unsafe_allow_html=True)


def _render_describe_action(snapshot: dict) -> None:
    del snapshot
    st.caption(
        "De handmatige beeldtest staat op de pagina Beeldtest. "
        "Die pagina stuurt alleen de klaargezette foto en carrousel, en alleen nadat je daar op de knop drukt."
    )


def _render_advice(record) -> None:
    st.markdown(
        '<h3 class="rro-comparison-section">Samenvatting en adviezen</h3>',
        unsafe_allow_html=True,
    )
    if record is not None and record.ai_status == "stored" and record.ai_summary and len(record.ai_advice) == 3:
        st.caption(
            "De cijfers in de tabellen zijn berekend door de app. "
            "De tekst hieronder is een toelichting en geen extra statistiek."
        )
        st.markdown(html.escape(record.ai_summary))
        items = "".join(f"<li>{html.escape(item)}</li>" for item in record.ai_advice)
        st.markdown(f"<ol>{items}</ol>", unsafe_allow_html=True)
        return
    if record is not None and record.ai_status == "error" and record.ai_summary:
        st.warning(record.ai_summary)
        return
    if is_configured():
        st.info(
            "Er is nog geen AI-analyse opgeslagen. "
            "Bewaar het rapport en gebruik daarna de knop. Opnieuw openen doet geen nieuwe aanroep."
        )
        return
    st.info(NOT_CONFIGURED_MESSAGE)


def _export(snapshot: dict, *, record) -> None:
    created = None
    ai_status = "not_configured"
    ai_summary = None
    ai_advice = None
    if record is not None:
        created = record.created_at
        ai_status = record.ai_status
        ai_summary = record.ai_summary
        ai_advice = record.ai_advice
    document = build_weekly_report_html(
        snapshot,
        ai_status=ai_status,
        ai_summary=ai_summary,
        ai_advice=ai_advice,
        created_at_display=created,
        ai_configured=is_configured(),
    )
    filename = f"weekrapport-{snapshot.get('period_start')}-{snapshot.get('period_end')}.html"
    st.download_button(
        "Exporteer voor PDF",
        data=document.encode("utf-8"),
        file_name=filename,
        mime="text/html",
        use_container_width=True,
        help="Open het bestand en kies Afdrukken, daarna Opslaan als PDF.",
    )


def render_weekly_report_page() -> None:
    """Results page for one calendar week, plus saved copies of earlier reports."""
    st.caption(
        "Cijfers uit opgeslagen metingen. Deze pagina haalt niets bij Meta op. "
        "Dit is iets anders dan Performance per maand: daar staan totalen van de laatste sync, geen weektoename."
    )
    own_id, competitors = _selection()
    today = datetime.now(tz=AMSTERDAM).date()
    default_start, _default_end = previous_complete_week(today)

    with get_connection() as conn:
        saved = list_weekly_reports(conn)
        conn.commit()

    labels = ["Actuele berekening"]
    ids: list[int | None] = [None]
    for report in saved:
        labels.append(
            f"{report.period_start} t/m {report.period_end} · bewaard {report.created_at[:16].replace('T', ' ')}"
        )
        ids.append(report.report_id)

    if st.session_state.get("weekly_saved_notice"):
        st.success(st.session_state.pop("weekly_saved_notice"))

    choice = st.selectbox("Rapport", labels, key="weekly_report_choice")
    selected_id = ids[labels.index(choice)] if choice in labels else None
    record = None
    if selected_id is not None:
        with get_connection() as conn:
            record = get_weekly_report(conn, selected_id)
            conn.commit()

    if record is None:
        picked = st.date_input(
            "Kies een dag in de gewenste week",
            value=default_start,
            format="DD-MM-YYYY",
            key="weekly_report_day",
        )
        if isinstance(picked, date):
            period_start, period_end = week_containing(picked)
        else:
            period_start, period_end = default_start, _default_end
        snapshot = build_weekly_snapshot(
            period_start=period_start,
            period_end=period_end,
            own_account_id=own_id,
            competitor_usernames=competitors,
        )
    else:
        snapshot = record.snapshot
        period_start = date.fromisoformat(str(snapshot.get("period_start")))
        period_end = date.fromisoformat(str(snapshot.get("period_end")))

    notice = str(snapshot.get("measurement_window_notice") or "")
    if notice:
        st.markdown(
            f"<div class='rro-week-alert'>{html.escape(notice)}</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        "<div class='rro-week-meta'>"
        f"<div><strong>Account</strong><br>{html.escape(str(snapshot.get('account_label') or NOT_AVAILABLE))}</div>"
        f"<div><strong>Week</strong><br>{html.escape(str(snapshot.get('period_label') or ''))}</div>"
        f"<div><strong>Laatste ophaalmoment</strong><br>{html.escape(str(snapshot.get('last_fetch_display') or NOT_AVAILABLE))}</div>"
        f"<div><strong>Rapport bewaard</strong><br>{html.escape(record.created_at[:16].replace('T', ' ') if record else 'nog niet bewaard')}</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    _render_snapshot(snapshot)
    _render_advice(record)
    _render_describe_action(snapshot)

    if record is not None and can_request_analysis(record.ai_status, configured=is_configured()):
        st.caption("Dit doet één AI-aanroep. Daarna blijft de tekst bij dit rapport staan.")
        if st.button("Schrijf samenvatting en adviezen", type="primary"):
            with get_connection() as conn:
                system_prompt, user_prompt = get_prompts(conn)
                conn.commit()
            with st.spinner("Analyse wordt geschreven…"):
                result = run_analysis(
                    record.snapshot,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            with get_connection() as conn:
                save_analysis(
                    conn,
                    record.report_id,
                    status=result.status,
                    summary=result.summary or result.message,
                    advice=result.advice,
                    model=result.model,
                )
                conn.commit()
            if result.status == "stored":
                st.success(result.message)
            else:
                st.warning(result.message)
            st.rerun()

    col_save, col_export = st.columns(2)
    with col_save:
        if record is None and st.button("Bewaar dit rapport", type="primary", use_container_width=True):
            with get_connection() as conn:
                save_weekly_report(
                    conn,
                    period_start=period_start.isoformat(),
                    period_end=period_end.isoformat(),
                    own_account_id=own_id,
                    account_label=str(snapshot.get("account_label") or ""),
                    snapshot=snapshot,
                )
                conn.commit()
            st.session_state.weekly_saved_notice = (
                "Rapport bewaard. Open het opnieuw in de lijst Rapport."
            )
            st.rerun()
    with col_export:
        _export(snapshot, record=record)
