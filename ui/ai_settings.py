"""Place to connect a later AI endpoint and edit the instruction texts."""

from __future__ import annotations

import html

import streamlit as st

from ai.config import public_ai_status
from ai.prompts import DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_PROMPT
from db.database import get_connection, initialize_database
from db.weekly_report_repository import get_prompts, save_prompts


def _flag(present: bool) -> str:
    return "aanwezig" if present else "ontbreekt"


def render_ai_settings_page() -> None:
    """Show what is needed for AI. Does not call a provider and does not store a key."""
    st.caption(
        "De lokale beeldtest gebruikt Gemini 3.5 Flash-Lite via het officiële OpenAI-compatibele adres. "
        "Zet de drie waarden in het bestand .env in de projectmap. "
        "De sleutel wordt hier niet getoond en niet opgeslagen. Deze pagina start geen facturatie."
    )
    status = public_ai_status()
    host = html.escape(str(status["base_host"] or ""))
    model = html.escape(str(status["model"] or "ontbreekt"))
    if status["configured"]:
        st.success("De drie instellingen zijn aanwezig. Een analyse start pas als je die op een bewaard rapport zelf start.")
    else:
        st.info("AI is nog niet ingesteld. Het weekrapport met cijfers werkt wel.")

    st.markdown(
        "<table class='rro-comparison-table'>"
        "<thead><tr><th>Instelling</th><th>Status</th></tr></thead><tbody>"
        f"<tr><td>AI_BASE_URL</td><td>{_flag(bool(status['has_base_url']))}"
        + (f" ({host})" if host else "")
        + "</td></tr>"
        f"<tr><td>AI_API_KEY</td><td>{_flag(bool(status['has_api_key']))}</td></tr>"
        f"<tr><td>AI_MODEL</td><td>{model}</td></tr>"
        "</tbody></table>",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
Zet deze drie waarden in `.env` in de projectmap, niet in dit scherm en niet in `.env.example`:

- `AI_BASE_URL` — `https://generativelanguage.googleapis.com/v1beta/openai`
- `AI_MODEL` — `gemini-3.5-flash-lite`
- `AI_API_KEY` — de Gemini-sleutel. Die blijft buiten git.

De app voegt zelf `/chat/completions` toe aan het adres. Een pagina openen doet geen aanvraag. De beeldtest stuurt alleen afbeeldingsbestanden, geen likes of andere prestatiecijfers.
"""
    )

    initialize_database()
    with get_connection() as conn:
        system_prompt, user_prompt = get_prompts(conn)
        conn.commit()

    st.markdown("**Instructies**")
    st.caption("De cijfers worden bij het maken van een analyse automatisch onder de tweede tekst gezet.")
    system_value = st.text_area("Instructie aan het model", value=system_prompt, height=220)
    user_value = st.text_area(
        "Opdracht bij elk rapport",
        value=user_prompt,
        height=160,
        help="Laat {snapshot_json} staan. Daar komen de berekende cijfers.",
    )
    col_save, col_reset = st.columns(2)
    with col_save:
        if st.button("Instructies opslaan", type="primary", use_container_width=True):
            with get_connection() as conn:
                save_prompts(conn, system_value, user_value)
                conn.commit()
            st.success("Instructies opgeslagen.")
    with col_reset:
        if st.button("Standaardtekst terugzetten", use_container_width=True):
            with get_connection() as conn:
                save_prompts(conn, DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_PROMPT)
                conn.commit()
            st.rerun()
