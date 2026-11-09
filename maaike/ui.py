"""Streamlit screens for Maaike's clients. No AI calls and no automatic Meta calls."""

from __future__ import annotations

import html
import os
import secrets

import streamlit as st
from dotenv import load_dotenv

from maaike.config import MaaikeConfigError, database_path
from maaike.db import initialize_database, transaction
from maaike.meta_connect import (
    LOGIN_SCOPES,
    MetaConnectError,
    OAuthReadiness,
    PageOption,
    PendingLogin,
    build_login_url,
    collect_pages,
    confirm_selected_page,
    normalize_redirect_uri,
    readiness,
    recheck_stored_link,
    record_failed_attempt,
)
from maaike.presentation import (
    EDITABLE_COLUMNS,
    OVERVIEW_COLUMNS,
    RATING_PENDING,
    editorial_changes,
    format_sync_moment,
    overview_table,
)
from maaike.repository import (
    UNSET_LABEL,
    Client,
    ClientInputError,
    LegendInputError,
    add_client,
    add_format,
    add_pillar,
    connection_label,
    is_verified_link,
    latest_sync_at,
    list_clients,
    list_formats,
    list_pillars,
    list_posts,
    rename_client,
    save_editorial,
    update_format,
    update_pillar,
)
from ui import styles as styles_mod

MAAIKE_CSS = """
<style>
div.stMainBlockContainer.block-container,
[data-testid="stMain"] div.block-container,
[data-testid="stMain"] .stMainBlockContainer.block-container,
section.main .block-container {
    max-width: 1440px !important;
}
</style>
"""


def render_app() -> None:
    _inject_styles()
    try:
        initialize_database()
        db_name = database_path().name
    except MaaikeConfigError as exc:
        st.error(str(exc))
        return

    _consume_meta_return()
    if "maaike_page" not in st.session_state:
        st.session_state.maaike_page = "posts"
    notice = st.session_state.pop("maaike_notice", None)
    error = st.session_state.pop("maaike_error", None)

    with transaction() as conn:
        clients = list_clients(conn)
    client = _selected_client(clients)

    with st.sidebar:
        st.markdown("**Klanten**")
        st.caption("Dashboard voor Maaike.")
        st.caption("De klantkiezer is geen toegangsbeveiliging. Iedereen die dit scherm opent, ziet alle klanten.")
        st.caption(f"Database: {db_name}")
        _render_client_picker(clients)
        page = st.session_state.maaike_page
        if st.button(
            "Klanten",
            type="tertiary" if page == "clients" else "primary",
            icon=":material/groups:",
            use_container_width=True,
            key="nav_clients",
        ):
            st.session_state.maaike_page = "clients"
            st.rerun()
        if st.button(
            "Postoverzicht",
            type="tertiary" if page == "posts" else "primary",
            icon=":material/table_rows:",
            use_container_width=True,
            key="nav_posts",
        ):
            st.session_state.maaike_page = "posts"
            st.rerun()
        if st.button(
            "Legenda",
            type="tertiary" if page == "legend" else "primary",
            icon=":material/menu_book:",
            use_container_width=True,
            key="nav_legend",
        ):
            st.session_state.maaike_page = "legend"
            st.rerun()

    title = client.name if client is not None else "Klanten"
    st.markdown(
        f'<h1 class="rro-page-title">{html.escape(title)}</h1>',
        unsafe_allow_html=True,
    )
    if client is not None:
        st.caption(connection_label(client))
    if notice:
        st.success(notice)
    if error:
        st.error(error)

    if st.session_state.maaike_page == "clients" or client is None:
        _render_clients(client)
    elif st.session_state.maaike_page == "legend":
        _render_legend(client)
    else:
        _render_posts(client)


def _inject_styles() -> None:
    import importlib

    importlib.reload(styles_mod)
    st.markdown(styles_mod.RRO_CSS, unsafe_allow_html=True)
    st.markdown(MAAIKE_CSS, unsafe_allow_html=True)


def _selected_client(clients: list[Client]) -> Client | None:
    if not clients:
        return None
    ids = [item.client_id for item in clients]
    coming = st.session_state.pop("maaike_client_picker_next", None)
    if coming in ids:
        st.session_state.maaike_client_picker_widget = coming
    choice = st.session_state.get("maaike_client_picker_widget")
    if choice not in ids:
        choice = ids[0]
        st.session_state.maaike_client_picker_widget = choice
    previous = st.session_state.get("maaike_client_picker")
    st.session_state.maaike_client_picker = choice
    if previous is not None and previous != choice:
        _clear_pending_if_other_client(choice)
    return next(item for item in clients if item.client_id == choice)


def _render_client_picker(clients: list[Client]) -> None:
    if not clients:
        st.info("Voeg eerst een klant toe.")
        return
    ids = [item.client_id for item in clients]
    names = {item.client_id: item.name for item in clients}
    choice = st.selectbox(
        "Klant",
        options=ids,
        format_func=lambda item_id: names[item_id],
        key="maaike_client_picker_widget",
    )
    selected = next(item for item in clients if item.client_id == choice)
    st.caption(connection_label(selected))


def _render_posts(client: Client) -> None:
    with transaction() as conn:
        moment = latest_sync_at(conn, client.client_id)
        posts = list_posts(conn, client.client_id)
        formats = list_formats(conn, client.client_id)
        pillars = list_pillars(conn, client.client_id)

    shown = format_sync_moment(moment)
    st.markdown(
        f"**Cijfers laatst bijgewerkt:** {html.escape(shown)}",
        unsafe_allow_html=True,
    )
    st.caption(
        "Ontbrekende cijfers staan als ‘niet beschikbaar’. "
        f"Beoordeling blijft ‘{RATING_PENDING}’. Insight en actie blijven leeg."
    )
    _render_fetch_button(client)

    if not posts:
        st.info(
            f"Nog geen posts voor {client.name}. "
            "Er zijn geen voorbeeldposts toegevoegd. "
            "Posts ophalen kan pas nadat de Meta-koppeling voor deze klant gecontroleerd is."
        )
        st.dataframe(
            {column: [] for column in OVERVIEW_COLUMNS},
            hide_index=True,
            width="stretch",
        )
        return

    post_ids, rows = overview_table(posts)
    format_options = [UNSET_LABEL, *[item.name for item in formats]]
    pillar_options = [UNSET_LABEL, *[item.name for item in pillars]]
    generation = int(st.session_state.get("post_editor_generation", 0))
    edited = st.data_editor(
        rows,
        column_order=list(OVERVIEW_COLUMNS),
        column_config={
            "Contentformat": st.column_config.SelectboxColumn(
                "Contentformat",
                options=format_options,
                required=True,
            ),
            "Contentpijler": st.column_config.SelectboxColumn(
                "Contentpijler",
                options=pillar_options,
                required=True,
            ),
            "Hook": st.column_config.TextColumn("Hook", width="large"),
            "Post-URL": st.column_config.TextColumn("Post-URL", width="medium"),
        },
        disabled=[column for column in OVERVIEW_COLUMNS if column not in EDITABLE_COLUMNS],
        hide_index=True,
        num_rows="fixed",
        width="stretch",
        key=f"posts-{client.client_id}-{generation}",
    )
    if st.button("Bewaar format, pijler en hook", type="primary"):
        _save_post_edits(
            client.client_id,
            post_ids,
            rows,
            _as_records(edited),
            formats=formats,
            pillars=pillars,
        )


def _render_fetch_button(client: Client) -> None:
    verified = is_verified_link(client)
    st.button("Posts ophalen", disabled=True, key=f"fetch-{client.client_id}")
    if verified:
        st.caption("De koppeling is gecontroleerd. Posts ophalen is de volgende bouwstap en draait nu nog niet.")
    else:
        st.caption("Posts ophalen blijft dicht tot deze klant gekoppeld en gecontroleerd is.")


def _save_post_edits(client_id, post_ids, original_rows, edited_rows, *, formats, pillars) -> None:
    format_ids = {item.name: item.item_id for item in formats}
    pillar_ids = {item.name: item.item_id for item in pillars}
    try:
        changes = editorial_changes(
            post_ids,
            original_rows,
            edited_rows,
            format_ids=format_ids,
            pillar_ids=pillar_ids,
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    if not changes:
        st.info("Geen wijzigingen om op te slaan.")
        return
    try:
        with transaction() as conn:
            for change in changes:
                save_editorial(
                    conn,
                    client_id,
                    post_id=change.post_id,
                    format_id=change.format_id,
                    pillar_id=change.pillar_id,
                    hook=change.hook,
                )
    except LegendInputError as exc:
        st.error(str(exc))
        return
    st.session_state.post_editor_generation = int(
        st.session_state.get("post_editor_generation", 0)
    ) + 1
    st.session_state.maaike_notice = "Opgeslagen."
    st.rerun()


def _as_records(edited: object) -> list[dict]:
    to_dict = getattr(edited, "to_dict", None)
    if callable(to_dict):
        return list(to_dict(orient="records"))
    if isinstance(edited, list):
        return [dict(row) for row in edited]
    raise ValueError("Het postoverzicht kon niet worden gelezen.")


def _render_legend(client: Client) -> None:
    st.caption(f"Contentformats en contentpijlers gelden alleen voor {client.name}.")
    _render_catalog(
        client_id=client.client_id,
        kind="format",
        title="Contentformats",
        empty=f"Nog geen contentformats voor {client.name}.",
        add_label="Nieuw contentformat",
        list_items=list_formats,
        add_item=add_format,
        update_item=update_format,
    )
    st.divider()
    _render_catalog(
        client_id=client.client_id,
        kind="pillar",
        title="Contentpijlers",
        empty=f"Nog geen contentpijlers voor {client.name}.",
        add_label="Nieuwe contentpijler",
        list_items=list_pillars,
        add_item=add_pillar,
        update_item=update_pillar,
    )


def _render_catalog(*, client_id, kind, title, empty, add_label, list_items, add_item, update_item) -> None:
    st.subheader(title)
    with transaction() as conn:
        items = list_items(conn, client_id)
    if not items:
        st.info(empty)
    for item in items:
        with st.expander(item.name, expanded=False):
            if item.explanation:
                st.caption(item.explanation)
            else:
                st.caption("Nog geen uitleg.")
            with st.form(f"edit-{client_id}-{kind}-{item.item_id}"):
                name = st.text_input("Naam", value=item.name)
                explanation = st.text_area("Uitleg", value=item.explanation, height=100)
                submitted = st.form_submit_button("Opslaan")
            if submitted:
                _store_legend(update_item, client_id, item.item_id, name, explanation)

    generation_key = f"add-{client_id}-{kind}-generation"
    generation = int(st.session_state.get(generation_key, 0))
    with st.form(f"add-{client_id}-{kind}-{generation}"):
        st.markdown(f"**{html.escape(add_label)}**")
        name = st.text_input("Naam", key=f"add-{client_id}-{kind}-name-{generation}")
        explanation = st.text_area(
            "Uitleg",
            key=f"add-{client_id}-{kind}-explanation-{generation}",
            height=100,
        )
        submitted = st.form_submit_button("Toevoegen")
    if submitted:
        _store_legend(add_item, client_id, name, explanation, generation_key=generation_key)


def _store_legend(action, *args, generation_key: str | None = None) -> None:
    try:
        with transaction() as conn:
            action(conn, *args)
    except (LegendInputError, ClientInputError) as exc:
        st.error(str(exc))
        return
    if generation_key is not None:
        st.session_state[generation_key] = int(st.session_state.get(generation_key, 0)) + 1
    st.session_state.maaike_notice = "Opgeslagen."
    st.rerun()


def _render_clients(client: Client | None) -> None:
    st.caption("Een klant is een naam in dit dashboard. De koppeling met Meta hoort bij die ene klant.")
    generation = int(st.session_state.get("add-client-generation", 0))
    with st.form(f"add-client-{generation}"):
        name = st.text_input("Nieuwe klant")
        submitted = st.form_submit_button("Klant toevoegen")
    if submitted:
        _add_client(name)

    if client is None:
        return

    with st.form(f"rename-client-{client.client_id}"):
        renamed = st.text_input("Naam van de gekozen klant", value=client.name)
        rename_submitted = st.form_submit_button("Naam opslaan")
    if rename_submitted:
        _rename_client(client.client_id, renamed)

    st.subheader("Meta")
    st.markdown(f"**Status:** {html.escape(connection_label(client))}")
    if client.meta_status_detail and not is_verified_link(client):
        st.caption(client.meta_status_detail)
    if is_verified_link(client):
        if st.button("Controleer koppeling", key=f"recheck-{client.client_id}"):
            _recheck(client.client_id)
    if is_verified_link(client) and client.meta_token_expires_at:
        st.caption(
            "Gebruikerstoegang tot "
            f"{format_sync_moment(client.meta_token_expires_at)}. "
            "Paginatoegang blijft geldig tot Meta die intrekt."
        )
    _render_meta_panel(client)


def _add_client(name: str) -> None:
    try:
        with transaction() as conn:
            client_id = add_client(conn, name)
    except ClientInputError as exc:
        st.error(str(exc))
        return
    st.session_state["add-client-generation"] = int(st.session_state.get("add-client-generation", 0)) + 1
    st.session_state.maaike_client_picker_next = client_id
    st.session_state.maaike_notice = "Klant toegevoegd."
    st.rerun()


def _rename_client(client_id: int, name: str) -> None:
    try:
        with transaction() as conn:
            rename_client(conn, client_id, name)
    except ClientInputError as exc:
        st.error(str(exc))
        return
    st.session_state.maaike_notice = "Naam opgeslagen."
    st.rerun()


def _render_meta_panel(client: Client) -> None:
    current = _callback_uri()
    state = readiness(current)
    _render_setup_notes(state)
    pending = st.session_state.get("maaike_pending")
    if isinstance(pending, PendingLogin) or (
        isinstance(pending, dict) and pending.get("client_id") == client.client_id
    ):
        _render_page_choice(client, pending)
        return

    label = "Reconnect" if is_verified_link(client) else "Connect with Meta"
    if st.button(label, type="primary", disabled=not state.ready, key=f"arm-{client.client_id}"):
        _arm_login(client.client_id, state)
        st.rerun()
    login_url = st.session_state.get("maaike_login_url")
    armed_for = st.session_state.get("maaike_oauth_client_id")
    if state.ready and armed_for == client.client_id and isinstance(login_url, str):
        st.link_button("Doorgaan naar Meta", login_url)
        st.caption("Status shows Connected only after you choose a page and verification succeeds.")


def _recheck(client_id: int) -> None:
    try:
        with transaction() as conn:
            page_name = recheck_stored_link(conn, client_id)
    except MetaConnectError as exc:
        _remember_failure(client_id, exc, replace_verified=True)
        st.session_state.maaike_error = str(exc)
        st.rerun()
        return
    st.session_state.maaike_notice = f"Koppeling gecontroleerd voor {page_name}."
    st.rerun()


def _render_page_choice(client: Client, pending: PendingLogin | dict) -> None:
    login = pending.get("login") if isinstance(pending, dict) else None
    if not isinstance(login, PendingLogin) or pending_client_id(pending) != client.client_id:
        return
    selectable = [page for page in login.pages if page.selectable]
    blocked = [page for page in login.pages if not page.selectable]
    st.markdown("**Kies de Facebook-pagina**")
    if not login.pages:
        st.warning("Meta gaf geen Facebook-pagina terug waar dit account een taak op heeft.")
    if blocked:
        names = ", ".join(page.page_name for page in blocked)
        st.caption(f"Zonder professioneel Instagram-account: {names}.")
    if selectable:
        index = st.selectbox(
            "Facebook-pagina",
            options=list(range(len(selectable))),
            format_func=lambda position: _page_label(selectable[position]),
            key=f"page-choice-{client.client_id}",
        )
        if st.button("Controleer en bewaar deze koppeling", type="primary"):
            _confirm_page(client.client_id, login, selectable[int(index)])
    if st.button("Annuleer deze login"):
        _clear_login_memory()
        st.rerun()


def _page_label(page: PageOption) -> str:
    if page.ig_username:
        return f"{page.page_name} (@{page.ig_username})"
    return page.page_name


def pending_client_id(pending: PendingLogin | dict) -> int | None:
    if isinstance(pending, dict):
        value = pending.get("client_id")
        return int(value) if isinstance(value, int) else None
    return None


def _confirm_page(client_id: int, pending: PendingLogin, option: PageOption) -> None:
    try:
        with transaction() as conn:
            page_name = confirm_selected_page(conn, client_id, pending, option)
    except MetaConnectError as exc:
        _remember_failure(client_id, exc)
        _clear_login_memory()
        st.session_state.maaike_error = str(exc)
        st.rerun()
        return
    _clear_login_memory()
    st.session_state.maaike_notice = f"Connected to {page_name}."
    st.rerun()


def _remember_failure(
    client_id: int,
    exc: MetaConnectError,
    *,
    replace_verified: bool = False,
) -> None:
    try:
        with transaction() as conn:
            record_failed_attempt(
                conn,
                client_id,
                exc,
                replace_verified=replace_verified,
            )
    except ClientInputError as inner:
        st.session_state.maaike_error = str(inner)


def _render_setup_notes(state: OAuthReadiness) -> None:
    if state.redirect_uri:
        st.markdown("**Callback-adres dat Meta exact moet accepteren**")
        st.code(state.redirect_uri, language=None)
        st.caption(
            "Zet dit adres in de Meta-app bij Facebook Login for Business → Settings → "
            "Valid OAuth Redirect URIs. Het adres, de poort en de schuine streep moeten gelijk zijn."
        )
    for item in state.missing:
        st.warning(item)
    if state.ready and state.uses_configuration:
        st.caption("De login gebruikt de ingestelde Meta-configuratie.")
    elif state.ready:
        scopes = ", ".join(LOGIN_SCOPES)
        st.caption(
            "Er is nog geen MAAIKE_META_LOGIN_CONFIG_ID. De knop vraagt deze rechten rechtstreeks: "
            f"{scopes}. Voor Facebook Login for Business is een configuratie-id de aanbevolen weg."
        )
    st.caption(
        "Tokens blijven in de database op deze computer en worden niet getoond. "
        "Die database is niet versleuteld. Zet dit dashboard niet op de huidige TAOL-service."
    )


def _arm_login(client_id: int, state: OAuthReadiness) -> None:
    if not state.ready or not state.redirect_uri:
        st.session_state.maaike_error = "Meta-login is nog niet ingesteld."
        return
    oauth_state = f"{client_id}.{secrets.token_urlsafe(24)}"
    try:
        url = build_login_url(redirect_uri=state.redirect_uri, state=oauth_state)
    except MetaConnectError as exc:
        st.session_state.maaike_error = str(exc)
        return
    st.session_state.maaike_oauth_state = oauth_state
    st.session_state.maaike_oauth_client_id = client_id
    st.session_state.maaike_oauth_redirect = state.redirect_uri
    st.session_state.maaike_login_url = url
    _clear_pending_if_other_client(client_id)


def _consume_meta_return() -> None:
    params = st.query_params
    if "code" not in params and "error" not in params:
        return
    code = str(params.get("code") or "")
    returned_state = str(params.get("state") or "")
    error = str(params.get("error") or "")
    st.query_params.clear()
    client_id = st.session_state.get("maaike_oauth_client_id")
    expected = st.session_state.get("maaike_oauth_state")
    redirect = st.session_state.get("maaike_oauth_redirect")
    st.session_state.pop("maaike_oauth_state", None)
    st.session_state.pop("maaike_login_url", None)
    if error:
        st.session_state.maaike_error = "De Meta-login is afgebroken of geweigerd."
        st.session_state.maaike_page = "clients"
        if isinstance(client_id, int):
            st.session_state.maaike_client_picker_widget = client_id
        return
    if (
        not code
        or not isinstance(client_id, int)
        or not isinstance(expected, str)
        or returned_state != expected
        or not isinstance(redirect, str)
    ):
        st.session_state.maaike_error = "Deze Meta-login hoort niet bij deze sessie. Start het koppelen opnieuw."
        st.session_state.maaike_page = "clients"
        return
    try:
        pending = collect_pages(code=code, redirect_uri=redirect)
    except MetaConnectError as exc:
        _remember_failure(client_id, exc)
        st.session_state.maaike_error = str(exc)
        st.session_state.maaike_page = "clients"
        st.session_state.maaike_client_picker_widget = client_id
        return
    st.session_state.maaike_pending = {"client_id": client_id, "login": pending}
    st.session_state.maaike_page = "clients"
    st.session_state.maaike_client_picker_widget = client_id


def _callback_uri() -> str | None:
    load_dotenv(override=False)
    configured = normalize_redirect_uri(st.session_state.get("maaike_redirect_override"))
    env_value = normalize_redirect_uri(os.getenv("MAAIKE_OAUTH_REDIRECT_URI"))
    if env_value:
        return env_value
    if configured:
        return configured
    try:
        raw = str(st.context.url)
    except Exception:
        return None
    return normalize_redirect_uri(raw)


def _clear_login_memory() -> None:
    st.session_state.pop("maaike_pending", None)
    st.session_state.pop("maaike_login_url", None)
    st.session_state.pop("maaike_oauth_state", None)
    st.session_state.pop("maaike_oauth_client_id", None)
    st.session_state.pop("maaike_oauth_redirect", None)


def _clear_pending_if_other_client(client_id: int) -> None:
    pending = st.session_state.get("maaike_pending")
    if isinstance(pending, dict) and pending.get("client_id") not in {None, client_id}:
        st.session_state.pop("maaike_pending", None)
