"""Printable HTML for a stored or live weekly snapshot. No network calls."""

from __future__ import annotations

import html
from typing import Any

from ai.analyze import NOT_CONFIGURED_MESSAGE
from analytics.weekly_report import (
    NOT_AVAILABLE,
    STAND_LABEL,
    format_avg,
    format_delta,
    format_int,
    format_published,
)


def _esc(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _stand_cell(post: dict[str, Any], key: str) -> str:
    if post.get("stand_status") != "ok":
        return NOT_AVAILABLE
    value = post.get(key)
    if value is None:
        return NOT_AVAILABLE
    return format_int(int(value))


def _advice_block(
    ai_status: str,
    ai_summary: str | None,
    ai_advice: list[str] | None,
    *,
    ai_configured: bool,
) -> str:
    if ai_status == "stored" and ai_summary and ai_advice and len(ai_advice) == 3:
        items = "".join(f"<li>{_esc(item)}</li>" for item in ai_advice)
        return (
            "<h2>Samenvatting en adviezen</h2>"
            "<p class='note'>De cijfers in de tabellen zijn berekend door de app. "
            "De tekst hieronder is een toelichting en geen extra statistiek.</p>"
            f"<p>{_esc(ai_summary)}</p><ol>{items}</ol>"
        )
    if ai_status == "error" and ai_summary:
        return (
            "<h2>Samenvatting en adviezen</h2>"
            f"<p>{_esc(ai_summary)}</p>"
        )
    if ai_configured:
        message = (
            "Er is nog geen AI-analyse opgeslagen. "
            "Die wordt pas geschreven als je daar zelf om vraagt."
        )
    else:
        message = NOT_CONFIGURED_MESSAGE
    return (
        "<h2>Samenvatting en adviezen</h2>"
        f"<p>{_esc(message)}</p>"
    )


def build_weekly_report_html(
    snapshot: dict[str, Any],
    *,
    ai_status: str = "not_configured",
    ai_summary: str | None = None,
    ai_advice: list[str] | None = None,
    created_at_display: str | None = None,
    ai_configured: bool = False,
) -> str:
    """Self-contained page that can be opened and saved as PDF via the browser print dialog."""
    own = snapshot.get("own") or {}

    def _account_row(block: dict[str, Any]) -> str:
        stand = block.get("followers_stand")
        stand_text = format_int(stand) if stand is not None else NOT_AVAILABLE
        return (
            "<tr>"
            f"<td>{_esc(block.get('display_name'))}</td>"
            f"<td>{_esc(format_published(block.get('posts_published'), block.get('posts_published_coverage', 'unavailable')))}</td>"
            f"<td>{_esc(stand_text)}</td>"
            f"<td>{_esc(format_delta(block.get('followers_delta'), block.get('followers_delta_status', 'unavailable')))}</td>"
            f"<td>{_esc(format_delta(block.get('likes_delta'), block.get('interaction_status', 'unavailable')))}</td>"
            f"<td>{_esc(format_delta(block.get('comments_delta'), block.get('interaction_status', 'unavailable')))}</td>"
            "</tr>"
        )

    own_row = _account_row(own) if own else "<tr><td colspan='6'>niet beschikbaar</td></tr>"
    competitor_rows = "".join(
        _account_row(block) for block in (snapshot.get("competitors") or [])
    ) or "<tr><td colspan='6'>niet beschikbaar</td></tr>"

    published_rows = []
    for post in snapshot.get("published_posts") or []:
        opening = post.get("opening_line") or NOT_AVAILABLE
        link = post.get("permalink")
        link_html = f"<a href='{_esc(link)}'>openen</a>" if link else NOT_AVAILABLE
        published_rows.append(
            "<tr>"
            f"<td>{_esc(post.get('published_display'))}</td>"
            f"<td>{_esc(post.get('content_label'))}</td>"
            f"<td>{_esc(opening)}</td>"
            f"<td>{_esc(_stand_cell(post, 'stand_likes'))}</td>"
            f"<td>{_esc(_stand_cell(post, 'stand_comments'))}</td>"
            f"<td>{_esc(STAND_LABEL)}</td>"
            f"<td>{link_html}</td>"
            "</tr>"
        )

    ranked_rows = []
    for post in snapshot.get("ranked_posts") or []:
        ranked_rows.append(
            "<tr>"
            f"<td>{_esc(post.get('rank'))}</td>"
            f"<td>{_esc(post.get('published_display'))}</td>"
            f"<td>{_esc(post.get('content_label'))}</td>"
            f"<td>{_esc(post.get('opening_line') or NOT_AVAILABLE)}</td>"
            f"<td>{_esc(format_delta(post.get('likes_delta'), 'ok'))}</td>"
            f"<td>{_esc(format_delta(post.get('comments_delta'), 'ok'))}</td>"
            f"<td>{_esc(format_delta(post.get('interaction_delta'), 'ok'))}</td>"
            f"<td>{_esc(post.get('basis_label'))}</td>"
            "</tr>"
        )

    type_rows = []
    for row in snapshot.get("content_types") or []:
        type_rows.append(
            "<tr>"
            f"<td>{_esc(row.get('label'))}</td>"
            f"<td>{_esc(format_int(row.get('published_count')))}</td>"
            f"<td>{_esc(format_int(row.get('comparable_posts')) if row.get('performance_status') == 'ok' else 'nog onvoldoende meetgegevens')}</td>"
            f"<td>{_esc(format_delta(row.get('interaction_delta'), row.get('performance_status', 'insufficient')))}</td>"
            f"<td>{_esc(format_avg(row.get('interaction_avg')) if row.get('performance_status') == 'ok' else 'nog onvoldoende meetgegevens')}</td>"
            "</tr>"
        )

    saved = created_at_display or "nog niet bewaard"
    notes = "".join(f"<li>{_esc(note)}</li>" for note in snapshot.get("notes") or [])
    published_body = (
        "".join(published_rows)
        if published_rows
        else f"<tr><td colspan='7'>{_esc('Geen opgeslagen posts met een publicatiedatum in deze week, of niet beschikbaar.')}</td></tr>"
    )
    ranked_body = (
        "".join(ranked_rows)
        if ranked_rows
        else "<tr><td colspan='8'>nog onvoldoende meetgegevens</td></tr>"
    )
    type_body = (
        "".join(type_rows)
        if type_rows
        else "<tr><td colspan='5'>nog onvoldoende meetgegevens</td></tr>"
    )
    compare_body = own_row

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<title>Weekrapport {_esc(snapshot.get('period_label'))}</title>
<style>
  body {{ font-family: "Segoe UI", sans-serif; color: #1c1915; background: #fff; margin: 24px; }}
  h1 {{ font-size: 28px; margin: 0 0 8px; }}
  h2 {{ font-size: 18px; margin: 28px 0 8px; }}
  p, li {{ line-height: 1.4; }}
  table {{ width: 100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 13px; }}
  th, td {{ border: 1px solid #d9d3cb; padding: 6px 8px; vertical-align: top; text-align: left; }}
  th {{ background: #f4efe8; }}
  .meta {{ color: #5c564e; margin: 0 0 4px; }}
  .note {{ color: #5c564e; font-size: 13px; }}
  .alert {{ background: #fff4e8; border: 2px solid #8a5a32; padding: 10px 12px; font-weight: 700; }}
  button {{ background: #8a5a32; color: white; border: 0; border-radius: 8px; padding: 8px 14px; cursor: pointer; }}
  @media print {{
    button, .no-print {{ display: none !important; }}
    body {{ margin: 12mm; }}
    a {{ color: inherit; text-decoration: none; }}
  }}
</style>
</head>
<body>
<button class="no-print" onclick="window.print()">Afdrukken of opslaan als PDF</button>
<h1>Weekrapport</h1>
<p class="alert">{_esc(snapshot.get('measurement_window_notice'))}</p>
<p class="meta">Account: {_esc(snapshot.get('account_label') or NOT_AVAILABLE)}</p>
<p class="meta">Week: {_esc(snapshot.get('period_label'))}</p>
<p class="meta">Laatste ophaalmoment: {_esc(snapshot.get('last_fetch_display') or NOT_AVAILABLE)}</p>
<p class="meta">Rapport bewaard: {_esc(saved)}</p>
<p class="note">Geplaatste posts en ontvangen interacties staan apart. Een stand op een meetmoment is geen weektoename.</p>
<h2>Weekcijfers</h2>
<table>
<thead><tr><th>Account</th><th>Geplaatst deze week</th><th>Volgersstand in de week</th><th>Volgersverschil</th><th>Like-toename</th><th>Reactie-toename</th></tr></thead>
<tbody>{compare_body}</tbody>
</table>
<p class="note">{_esc((own or {}).get('followers_note') or '')}</p>
<p class="note">{_esc((own or {}).get('interaction_note') or '')}</p>
<h2>Posts geplaatst deze week</h2>
<table>
<thead><tr><th>Geplaatst</th><th>Soort</th><th>Openingszin</th><th>Likes, stand</th><th>Reacties, stand</th><th>Betekenis</th><th>Link</th></tr></thead>
<tbody>{published_body}</tbody>
</table>
<h2>Best presterende posts</h2>
<p class="note">{_esc(snapshot.get('ranking_basis'))}</p>
<table>
<thead><tr><th>#</th><th>Geplaatst</th><th>Soort</th><th>Openingszin</th><th>Likes</th><th>Reacties</th><th>Som</th><th>Waarop gebaseerd</th></tr></thead>
<tbody>{ranked_body}</tbody>
</table>
<h2>Vergelijking met concurrenten</h2>
<p class="note">Zelfde soort cijfers als hierboven, alleen waar echte metingen zijn opgeslagen.</p>
<table>
<thead><tr><th>Account</th><th>Geplaatst deze week</th><th>Volgersstand in de week</th><th>Volgersverschil</th><th>Like-toename</th><th>Reactie-toename</th></tr></thead>
<tbody>{competitor_rows}</tbody>
</table>
<h2>Soorten posts</h2>
<p class="note">De gemiddelden zijn berekend uit posts met twee bruikbare metingen. Een hoger gemiddelde is geen garantie.</p>
<table>
<thead><tr><th>Soort</th><th>Geplaatst deze week</th><th>Posts met toename</th><th>Interactietoename</th><th>Gemiddelde</th></tr></thead>
<tbody>{type_body}</tbody>
</table>
<h2>Berekende samenvatting</h2>
<p>{_esc(snapshot.get('summary'))}</p>
{_advice_block(ai_status, ai_summary, ai_advice, ai_configured=ai_configured)}
<h2>Hoe de cijfers zijn begrensd</h2>
<ul>{notes}</ul>
</body>
</html>
"""
