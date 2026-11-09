"""Local image test. Opening this page does not call AI or Meta."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from ai.config import is_configured
from ai.content_describe import describe_post
from ai.image_test import load_image_test_posts
from db.database import get_connection, initialize_database


def _kind_label(media_type: str) -> str:
    if media_type == "CAROUSEL_ALBUM":
        return "Carrousel"
    if media_type == "IMAGE":
        return "Foto"
    return media_type or "Post"


def _usage_line(description: dict[str, Any] | None) -> str:
    usage = description.get("api_usage") if isinstance(description, dict) else None
    if not isinstance(usage, dict) or not usage.get("reported"):
        return "Nog geen API-verbruik opgeslagen."
    return (
        "API-verbruik: "
        f"input {usage.get('prompt_tokens')} tokens, "
        f"output {usage.get('completion_tokens')} tokens, "
        f"totaal {usage.get('total_tokens')} tokens."
    )


def _render_post(post: dict[str, Any]) -> None:
    description = post.get("description") if isinstance(post.get("description"), dict) else None
    slides = description.get("slides") if description else []
    by_number = {
        int(item["slide"]): item
        for item in slides
        if isinstance(item, dict) and isinstance(item.get("slide"), int)
    }
    st.markdown(f"### {_kind_label(str(post.get('media_type') or ''))}")
    st.caption(
        f"Geplaatst {post.get('published_at') or ''}. "
        f"Dekking: {post.get('coverage') or 'Nog niet geanalyseerd'}."
    )
    if post.get("coverage_note"):
        st.caption(str(post["coverage_note"]))

    st.markdown("**Caption, apart van het beeld**")
    st.text(post.get("caption") or "Geen caption opgeslagen.")

    for part in post.get("parts") or []:
        number = int(part["position"])
        left, right = st.columns(2)
        with left:
            st.markdown(f"**Slide {number}**")
            path = part.get("local_path")
            if path:
                st.image(path, width="stretch")
            else:
                st.info("Het beeldbestand staat nog niet lokaal. Er is geen Meta-aanvraag gedaan.")
        with right:
            item = by_number.get(number)
            if item is None:
                st.markdown("**In beeld gezien**")
                st.write("Nog geen beschrijving. De AI-aanvraag wacht tot de sleutel is ingesteld.")
                continue
            st.markdown("**In beeld gezien**")
            st.write(item.get("seen") or "")
            st.markdown("**Leesbare tekst**")
            st.write(item.get("visible_text") or "Geen leesbare tekst vermeld.")
            st.markdown("**Onduidelijk**")
            st.write(item.get("unclear") or "Niets onduidelijks vermeld.")

    if description:
        st.markdown("**Alleen uit de caption**")
        st.write(description.get("caption_only") or "Niets dat alleen uit de caption komt.")
        st.markdown("**Samenvatting van wat in beeld is gezien**")
        st.write(description.get("seen_only") or "")
        st.markdown("**Onduidelijk in het geheel**")
        st.write(description.get("unclear") or "Niets onduidelijks vermeld.")
        st.caption(
            "Model: "
            f"{html.escape(str(post.get('model') or ''))}. "
            f"Prompt {html.escape(str(post.get('prompt_version') or ''))}. "
            f"Moment {html.escape(str(post.get('analyzed_at') or ''))}."
        )
        st.caption(_usage_line(description))
        files = ", ".join(post.get("files_processed") or [])
        if files:
            st.caption(f"Verwerkte bestanden: {html.escape(files)}")


def render_image_test_page() -> None:
    initialize_database()
    st.caption(
        "Deze pagina toont de opgeslagen foto en de carrousel met twee slides. "
        "Openen doet geen AI-aanvraag en geen Meta-aanvraag. "
        "Likes en andere prestatiecijfers gaan niet mee."
    )
    with get_connection() as conn:
        posts = load_image_test_posts(conn)
    if len(posts) < 2:
        st.warning("De foto of de carrousel met twee slides is niet compleet in de lokale database.")
    for post in posts:
        _render_post(post)
        st.divider()

    if not is_configured():
        st.info(
            "AI_API_KEY ontbreekt nog. Er is geen beschrijving gemaakt en er gaat geen aanvraag weg. "
            "Zet de sleutel in het lokale bestand .env, samen met AI_BASE_URL en AI_MODEL."
        )
        return

    ready = [
        post
        for post in posts
        if post.get("parts") and all(part.get("ready") for part in post["parts"])
    ]
    described = [post for post in ready if isinstance(post.get("description"), dict)]
    if described and len(described) == len(ready) and ready:
        st.success("De opgeslagen beschrijvingen zijn heropend. Deze pagina doet geen nieuwe aanvraag.")
        return
    if st.button("Maak de beeldbeschrijving", type="primary"):
        for post in ready:
            describe_post(int(post["post_id"]))
        st.rerun()
