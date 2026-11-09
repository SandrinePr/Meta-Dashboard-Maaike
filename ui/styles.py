"""RRO / Red Rock theme CSS for the Streamlit dashboard."""

RRO_CSS = """
<style>
/* rro-css-v32-comparison-fullwidth */
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap');

:root {
    --rro-bg: #101C2C;
    --rro-bg-deep: #0B1826;
    --rro-sidebar: #101C2C;
    --rro-card: #232E3B;
    --rro-card-light: #1C2433;
    --rro-panel: #313945;
    --rro-input: #4B5560;
    --rro-input-hover: #556070;
    --rro-cta: #B87844;
    --rro-cta-hover: #A45E2B;
    --rro-text: #F2F0EC;
    --rro-text-muted: rgba(242, 240, 236, 0.62);
    --rro-border: rgba(242, 240, 236, 0.12);
    --rro-border-accent: rgba(184, 120, 68, 0.45);
    /* Hover: border blijft --rro-border; alleen fill verandert */
    --rro-stroke: var(--rro-border);
    --rro-shadow: 0 4px 18px rgba(0, 0, 0, 0.28);
    --rro-highlight: #B87844;
    --rro-cyan: #A1BACA;
    --rro-badge: #303945;
    --rro-radius: 12px;
    --rro-radius-sm: 8px;
    --rro-control-h: 38px;
}

html, body, [class*="css"] {
    font-family: "Source Sans 3", sans-serif;
}

.stApp {
    background: linear-gradient(165deg, #313945 0%, #101C2C 100%);
    color: var(--rro-text);
    overflow-x: hidden;
}

/* Streamlit topbar: transparant, geen toolbar — ruimte komt via padding hieronder */
[data-testid="stHeader"] {
    background: transparent !important;
}

[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] {
    display: none !important;
}

/* 5rem ruimte boven de hoofdkaart (padding, niet margin — margin wordt door Streamlit weggedrukt) */
section.main[data-testid="stMain"],
[data-testid="stMain"] {
    padding-top: 5rem !important;
}

div.stMainBlockContainer.block-container,
[data-testid="stMain"] div.block-container,
[data-testid="stMain"] .stMainBlockContainer.block-container,
section.main .block-container {
    max-width: 1000px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding: 2rem !important;
    background: #313945 !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: 16px !important;
    box-shadow: var(--rro-shadow) !important;
}

/* Verticale ritme in de hoofdkaart */
[data-testid="stMain"] .block-container > div {
    gap: 1rem !important;
}

[data-testid="stMain"] [data-testid="stVerticalBlock"] {
    gap: 1rem !important;
}

[data-testid="stMain"] [data-testid="stElementContainer"] {
    margin-bottom: 0 !important;
}

h1,
.rro-page-title {
    font-size: 34px !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
    line-height: 1.15 !important;
    color: var(--rro-text) !important;
    margin: 0 0 8px 0 !important;
    padding: 0 !important;
    background: transparent !important;
}

/* Title and caption are separate Streamlit widgets — space between their containers */
[data-testid="stMain"] [data-testid="stElementContainer"]:has(.rro-page-title) {
    margin-bottom: 8px !important;
    padding-bottom: 0 !important;
}

.rro-page-title:hover,
h1:hover {
    background: transparent !important;
    color: var(--rro-text) !important;
}

[data-testid="stMain"] .stCaption {
    margin: 0 0 0.35rem 0 !important;
    padding: 0 !important;
}

/* Geen Streamlit/Baseweb lichtblauwe focus/hover glows */
.stApp *:focus,
.stApp *:focus-visible,
.stApp input:focus,
.stApp button:focus,
.stApp [data-baseweb="input"]:focus-within,
.stApp [data-baseweb="select"]:focus-within {
    outline: none !important;
    box-shadow: none !important;
}

.stApp a:hover:not(.rro-btn-link),
.stApp a:focus:not(.rro-btn-link) {
    background: transparent !important;
}

h2, h3, h4, h5, h6, p, label, span, div {
    color: var(--rro-text);
}

.stCaption, small, .muted {
    color: var(--rro-text-muted) !important;
}

section[data-testid="stSidebar"] {
    background: #101C2C !important;
    border-right: 1px solid var(--rro-border);
    box-shadow: none;
}

/* Desktop: sidebar 300px */
@media (min-width: 801px) {
    [data-testid="stSidebarCollapseButton"],
    [data-testid="collapsedControl"],
    button[kind="header"] {
        display: none !important;
    }

    section[data-testid="stSidebar"] {
        min-width: 300px !important;
        width: 300px !important;
        transform: translateX(0) !important;
        visibility: visible !important;
    }

    /* Exact one horizontal padding layer (Streamlit nests Content + UserContent). */
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }

    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        padding-left: 0 !important;
        padding-right: 0 !important;
    }

    .rro-mobile-sync-hint {
        display: none !important;
    }
}

@media (max-width: 800px) {
    /* Header-ruimte voor zichtbare Sync-knop */
    [data-testid="stHeader"] {
        height: 3.5rem !important;
        min-height: 3.5rem !important;
        background: transparent !important;
    }

    [data-testid="stSidebarCollapseButton"] {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        position: absolute !important;
        top: 10px !important;
        right: 10px !important;
        z-index: 1000002 !important;
        width: 36px !important;
        height: 36px !important;
        border-radius: 8px !important;
        border: 1px solid var(--rro-border) !important;
        background: #313945 !important;
        color: var(--rro-text) !important;
        cursor: pointer !important;
    }

    [data-testid="stSidebarCollapseButton"] svg {
        display: none !important;
    }

    [data-testid="stSidebarCollapseButton"]::after {
        content: "×";
        font-size: 1.5rem;
        line-height: 1;
        color: var(--rro-text);
        font-weight: 400;
    }

    /* Duidelijke Sync-knop linksboven op mobiel */
    [data-testid="collapsedControl"] {
        display: flex !important;
        align-items: center !important;
        position: fixed !important;
        top: 12px !important;
        left: 12px !important;
        z-index: 1000003 !important;
        width: auto !important;
        min-width: 44px !important;
        height: 40px !important;
        padding: 0 12px !important;
        border-radius: 8px !important;
        border: 1px solid var(--rro-border) !important;
        background: #313945 !important;
        color: var(--rro-text) !important;
        box-shadow: var(--rro-shadow) !important;
        cursor: pointer !important;
    }

    [data-testid="collapsedControl"] svg {
        color: var(--rro-text) !important;
        fill: var(--rro-text) !important;
    }

    [data-testid="collapsedControl"]::after {
        content: "Synchronisatie";
        font-size: 0.8rem;
        font-weight: 600;
        margin-left: 6px;
        color: var(--rro-text);
        white-space: nowrap;
    }

    section[data-testid="stSidebar"] {
        min-width: min(300px, 90vw) !important;
        width: min(300px, 90vw) !important;
    }

    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 48px !important;
    }

    [data-testid="stMain"] .block-container,
    [data-testid="stMain"] .stMainBlockContainer.block-container,
    section.main .block-container {
        max-width: calc(100% - 1rem) !important;
        margin-top: 0 !important;
        margin-left: auto !important;
        margin-right: auto !important;
        margin-bottom: 0.25rem !important;
        padding: 1.25rem 1rem !important;
    }

    section.main[data-testid="stMain"],
    [data-testid="stMain"] {
        padding-top: 4.5rem !important;
    }

    .rro-mobile-sync-hint {
        display: block;
        margin: 0 0 0.75rem 0;
        padding: 8px 10px;
        border-radius: 8px;
        border: 1px solid var(--rro-border);
        background: #1A2230;
        color: var(--rro-text-muted);
        font-size: 0.78rem;
        line-height: 1.4;
    }
}

section[data-testid="stSidebar"] > div {
    background: #101C2C !important;
}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span {
    color: var(--rro-text) !important;
}

section[data-testid="stSidebar"] .stButton > button {
    background: var(--rro-cta) !important;
    color: #FFFFFF !important;
    border: 1px solid var(--rro-cta) !important;
    border-radius: var(--rro-radius-sm) !important;
    font-weight: 700 !important;
    box-shadow: none;
    min-height: 38px !important;
}

section[data-testid="stSidebar"] .stButton > button:hover {
    background: var(--rro-cta-hover) !important;
    border-color: var(--rro-cta-hover) !important;
    color: #FFFFFF !important;
}

section[data-testid="stSidebar"] .stButton > button p {
    color: #FFFFFF !important;
}

/* Active nav page: same dark navy as sidebar + orange outline */
section[data-testid="stSidebar"] .stButton > button[kind="secondary"],
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"],
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"],
section[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"],
section[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
section[data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] {
    background: #101C2C !important;
    background-color: #101C2C !important;
    color: #FFFFFF !important;
    border: 1px solid #B87844 !important;
    border-color: #B87844 !important;
    box-shadow: none !important;
}

section[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover,
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"]:hover,
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover,
section[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"]:hover,
section[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover,
section[data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"]:hover {
    background: #101C2C !important;
    background-color: #101C2C !important;
    border: 1px solid #B87844 !important;
    border-color: #B87844 !important;
    color: #FFFFFF !important;
}

section[data-testid="stSidebar"] .stButton > button[kind="secondary"] p,
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"] p,
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] p,
section[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] p,
section[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] p,
section[data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] p {
    color: #FFFFFF !important;
}

/* Keep page navigation under the sync block, stretched to the bottom */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    display: flex;
    flex-direction: column;
    height: 100%;
}

section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    min-height: 0;
}

section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]
    > [data-testid="stVerticalBlock"] {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    min-height: 100%;
}

section[data-testid="stSidebar"] .st-key-nav_performance {
    margin-top: auto !important;
    padding-top: 1rem !important;
}

section[data-testid="stSidebar"] .st-key-nav_comparison button {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 0.45rem !important;
}

section[data-testid="stSidebar"] .st-key-nav_comparison button span,
section[data-testid="stSidebar"] .st-key-nav_comparison button [data-testid="stIconMaterial"] {
    color: #FFFFFF !important;
}

.rro-sidebar-title {
    font-size: 1rem;
    font-weight: 700;
    color: var(--rro-text);
    margin-bottom: 0.5rem;
}

.rro-stat-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 1px solid var(--rro-border);
}

.rro-stat-icon {
    width: 24px;
    height: 24px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--rro-cta);
    flex-shrink: 0;
}

.rro-svg-icon {
    width: 15px;
    height: 15px;
    display: block;
}

.rro-svg-icon-sm {
    width: 11px;
    height: 11px;
}

.rro-stat-label {
    flex: 1;
    color: var(--rro-text-muted);
    font-size: 0.82rem;
}

.rro-stat-value {
    color: var(--rro-cta);
    font-weight: 700;
    font-size: 0.9rem;
}

.rro-sync-metrics-note {
    margin: 0.65rem 0 0.85rem 0;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid var(--rro-border) !important;
    background: #313945 !important;
    background-color: #313945 !important;
    color: var(--rro-text-muted) !important;
    font-size: 0.74rem;
    line-height: 1.4;
}

.rro-sync-metrics-note strong {
    color: var(--rro-text) !important;
    font-weight: 700;
}

.rro-sync-metrics-note code {
    color: var(--rro-text) !important;
    font-size: 0.72rem;
    word-break: break-all;
}

.rro-deploy-version {
    margin: 0 0 0.75rem 0;
    color: var(--rro-text-muted) !important;
    font-size: 0.68rem;
    letter-spacing: 0.02em;
    opacity: 0.85;
}

/* Zoeken-header (geen aparte nested card; zit in hoofdkaart) */
[data-testid="stMain"] [data-testid="stVerticalBlock"]:has(.rro-search-form-header) {
    background: transparent;
    border: none;
    border-radius: 0;
    box-shadow: none;
    padding: 0;
    margin-bottom: 0.35rem;
}

.rro-search-form-header h3 {
    margin: 0 0 0.3rem 0;
    font-size: 1.05rem;
    font-weight: 700;
    color: var(--rro-text);
}

/* Loading indicator tijdens zoeken */
[data-testid="stSpinner"],
.stSpinner {
    color: var(--rro-text) !important;
}

.stSpinner > div {
    border-top-color: var(--rro-cta) !important;
    border-right-color: rgba(184, 120, 68, 0.25) !important;
    border-bottom-color: rgba(184, 120, 68, 0.25) !important;
    border-left-color: rgba(184, 120, 68, 0.25) !important;
}

.stSpinner p,
[data-testid="stSpinner"] p {
    color: var(--rro-text) !important;
}

.rro-filter-label {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--rro-text);
    margin: 0.2rem 0 0.25rem 0;
}

div[data-testid="stForm"] {
    background: transparent;
    border: none;
    box-shadow: none;
    padding: 0;
    margin: 0;
}

div[data-testid="stForm"] [data-testid="stFormSubmitHint"] {
    display: none !important;
}

/* Inputs — verticaal gecentreerde tekst */
.stTextInput input,
div[data-testid="stTextInput"] input,
div[data-testid="stForm"] input[type="text"] {
    background: #4B5560 !important;
    border: 1px solid var(--rro-border) !important;
    color: var(--rro-text) !important;
    border-radius: var(--rro-radius-sm) !important;
    height: var(--rro-control-h) !important;
    min-height: var(--rro-control-h) !important;
    max-height: var(--rro-control-h) !important;
    line-height: var(--rro-control-h) !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    padding-left: 0.85rem !important;
    padding-right: 6.5rem !important;
    box-sizing: border-box !important;
    transition: background-color 0.15s ease, border-color 0.15s ease;
}

.stTextInput input::placeholder {
    color: rgba(242, 240, 236, 0.42) !important;
    line-height: var(--rro-control-h) !important;
}

/* Hover/focus: border blijft --rro-border; alleen fill verandert */
.stTextInput input:hover,
div[data-testid="stTextInput"] input:hover,
.stTextInput input:focus,
div[data-testid="stTextInput"] input:focus {
    border-color: var(--rro-border) !important;
    box-shadow: none !important;
    outline: none !important;
    background: var(--rro-input-hover) !important;
}

div[data-testid="stTextInput"] [data-testid="stTextInputRootElement"],
div[data-testid="stTextInput"] > div,
div[data-testid="stTextInput"] [data-baseweb="input"],
div[data-testid="stTextInput"] [data-baseweb="base-input"] {
    position: relative !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    min-height: var(--rro-control-h) !important;
    height: var(--rro-control-h) !important;
}

/* Celine: Press enter rechts in balk, verticaal gecentreerd */
div[data-testid="stTextInput"] [data-testid="InputInstructions"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    position: absolute !important;
    right: 12px !important;
    top: 50% !important;
    bottom: auto !important;
    left: auto !important;
    transform: translateY(-50%) !important;
    align-items: center !important;
    justify-content: flex-end !important;
    height: auto !important;
    width: auto !important;
    max-width: 6.25rem !important;
    margin: 0 !important;
    padding: 0 !important;
    z-index: 3;
    pointer-events: none !important;
    color: var(--rro-text-muted) !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    line-height: 1 !important;
    white-space: nowrap !important;
}

div[data-testid="stTextInput"] [data-testid="InputInstructions"] *,
div[data-testid="stTextInput"] [data-testid="InputInstructions"] kbd,
div[data-testid="stTextInput"] [data-testid="InputInstructions"] span {
    display: inline !important;
    visibility: visible !important;
    opacity: 1 !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: var(--rro-text-muted) !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    line-height: 1 !important;
    padding: 0 !important;
    margin: 0 !important;
}

/* Datums: geen donkere schaduwranden; gelijk aan andere filters */
div[data-testid="stDateInput"] input,
div[data-testid="stDateInput"] button {
    pointer-events: auto !important;
    cursor: pointer !important;
}

div[data-testid="stDateInput"],
div[data-testid="stDateInput"] > div,
div[data-testid="stDateInput"] [data-baseweb="input"],
div[data-testid="stDateInput"] [data-baseweb="base-input"],
div[data-testid="stDateInput"] [data-baseweb="popover"] > div,
div[data-testid="stDateInput"] [data-baseweb="popover"] > div > div {
    background: transparent !important;
    box-shadow: none !important;
    filter: none !important;
    outline: none !important;
}

div[data-testid="stDateInput"] [data-baseweb="input"] {
    background: #4B5560 !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: var(--rro-radius-sm) !important;
    min-height: var(--rro-control-h) !important;
    height: var(--rro-control-h) !important;
    transition: background-color 0.15s ease, border-color 0.15s ease !important;
    overflow: hidden !important;
}

div[data-testid="stDateInput"] [data-baseweb="input"]:hover,
div[data-testid="stDateInput"] [data-baseweb="input"]:focus-within,
div[data-testid="stDateInput"]:hover [data-baseweb="input"] {
    border-color: var(--rro-border) !important;
    box-shadow: none !important;
    background: var(--rro-input-hover) !important;
}

div[data-testid="stDateInput"] input {
    height: var(--rro-control-h) !important;
    min-height: var(--rro-control-h) !important;
    line-height: var(--rro-control-h) !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    padding-right: 2.25rem !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
    color: var(--rro-text) !important;
}

div[data-testid="stDateInput"] button,
div[data-testid="stDateInput"] [role="button"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

div[data-testid="stDateInput"] svg {
    color: var(--rro-text-muted) !important;
    fill: var(--rro-text-muted) !important;
}

/* Zoeken-knop: stabiele anchor — ruimte tussen filterrij en knop weg */
[data-testid="stMain"]
[data-testid="stVerticalBlock"]:has(.rro-search-button-anchor) {
    gap: 0 !important;
    row-gap: 0 !important;
}

/* Filter+knop-wrapper: 16px boven de filters (unieke marker als eerste child) */
div[data-testid="stVerticalBlock"]:has(> div .rro-filter-block-anchor) {
    padding-top: 16px !important;
}

[data-testid="stMain"]
[data-testid="stElementContainer"]:has(.rro-filter-block-anchor),
[data-testid="stMain"]
[data-testid="stElementContainer"]:has(.rro-search-button-anchor) {
    display: none !important;
}

/* Oorzaak van de lege strook: Streamlit zet 24px margin-bottom op de filter-rij */
[data-testid="stMain"]
[data-testid="stVerticalBlock"]:has(.rro-search-button-anchor)
    [data-testid="stHorizontalBlock"] {
    margin-bottom: 0 !important;
}

[data-testid="stMain"]
[data-testid="stVerticalBlock"]:has(.rro-search-button-anchor)
    > [data-testid="stLayoutWrapper"] {
    margin-bottom: 0 !important;
    padding-bottom: 0 !important;
}

[data-testid="stMain"]
[data-testid="stVerticalBlock"]:has(.rro-search-button-anchor)
    > [data-testid="stElementContainer"]:has(.stButton) {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    width: 150px !important;
}

[data-testid="stMain"]
[data-testid="stVerticalBlock"]:has(.rro-search-button-anchor)
    .stButton,
[data-testid="stMain"]
[data-testid="stVerticalBlock"]:has(.rro-search-button-anchor)
    .stButton > button {
    width: 150px !important;
    min-width: 150px !important;
    max-width: 150px !important;
    box-sizing: border-box !important;
}

.stButton > button {
    background: var(--rro-cta) !important;
    color: #FFFFFF !important;
    border: 1px solid var(--rro-cta) !important;
    border-radius: var(--rro-radius-sm) !important;
    font-weight: 700 !important;
    height: var(--rro-control-h) !important;
    min-height: var(--rro-control-h) !important;
    padding: 0 0.9rem !important;
    box-shadow: none !important;
    transition: border-color 0.15s ease, background 0.15s ease;
}

.stButton > button:hover,
.stButton > button:focus,
.stButton > button:focus-visible {
    background: var(--rro-cta-hover) !important;
    border-color: var(--rro-cta-hover) !important;
    color: #FFFFFF !important;
    box-shadow: none !important;
    outline: none !important;
}

.stButton > button p {
    color: #FFFFFF !important;
}

/* Filters: lager, compact, één rij */
[data-testid="stMultiSelect"] label,
[data-testid="stMultiSelect"] label p,
[data-testid="stDateInput"] label,
[data-testid="stDateInput"] label p {
    color: var(--rro-text) !important;
    font-size: 0.82rem !important;
    font-weight: 700 !important;
    margin-bottom: 0.2rem !important;
}

[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {
    background-color: #4B5560 !important;
    color: var(--rro-text) !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: var(--rro-radius-sm) !important;
    min-height: var(--rro-control-h) !important;
    height: auto !important;
    max-height: none !important;
    box-shadow: none !important;
    transition: background-color 0.15s ease, border-color 0.15s ease;
    padding-top: 2px !important;
    padding-bottom: 2px !important;
}

[data-testid="stMultiSelect"] div[data-baseweb="select"] > div:hover,
[data-testid="stMultiSelect"] div[data-baseweb="select"]:hover > div,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div[aria-expanded="true"] {
    border-color: var(--rro-border) !important;
    box-shadow: none !important;
    background-color: var(--rro-input-hover) !important;
}

[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
    background-color: var(--rro-cta) !important;
    color: #FFFFFF !important;
    border-radius: 999px !important;
    font-size: 0.72rem !important;
    min-height: 22px !important;
}

[data-testid="stMultiSelect"] span[data-baseweb="tag"] span,
[data-testid="stMultiSelect"] span[data-baseweb="tag"] svg {
    color: #FFFFFF !important;
    fill: #FFFFFF !important;
}

div[data-baseweb="popover"] ul[role="listbox"],
div[data-baseweb="menu"] ul[role="listbox"] {
    background-color: var(--rro-card-light) !important;
    color: var(--rro-text) !important;
    border: 1px solid var(--rro-border) !important;
    box-shadow: var(--rro-shadow);
}

div[data-baseweb="popover"] li[role="option"],
div[data-baseweb="menu"] li[role="option"] {
    background-color: var(--rro-card-light) !important;
    color: var(--rro-text) !important;
}

div[data-baseweb="popover"] li[role="option"]:hover,
div[data-baseweb="popover"] li[aria-selected="true"],
div[data-baseweb="menu"] li[role="option"]:hover,
div[data-baseweb="menu"] li[aria-selected="true"] {
    background-color: rgba(184, 120, 68, 0.18) !important;
    color: var(--rro-text) !important;
}

[data-baseweb="calendar"],
[data-baseweb="datepicker"] {
    background-color: var(--rro-card-light) !important;
    color: var(--rro-text) !important;
    border: 1px solid var(--rro-border) !important;
    box-shadow: var(--rro-shadow);
}

[data-baseweb="calendar"] [role="gridcell"],
[data-baseweb="calendar"] [role="columnheader"],
[data-baseweb="calendar"] button,
[data-baseweb="calendar"] div {
    color: var(--rro-text) !important;
}

[data-baseweb="calendar"] [aria-selected="true"] {
    background-color: var(--rro-cta) !important;
    color: #FFFFFF !important;
}

[data-baseweb="calendar"] [aria-selected="true"] div {
    color: #FFFFFF !important;
}

[data-baseweb="calendar"] [role="gridcell"][aria-label*="between"],
[data-baseweb="calendar"] [data-range="true"] {
    background-color: rgba(184, 120, 68, 0.22) !important;
    color: var(--rro-text) !important;
}

[data-testid="stAlert"],
[data-baseweb="notification"],
[data-testid="stNotification"] {
    background-color: var(--rro-card) !important;
    color: var(--rro-text) !important;
    border-left: 3px solid var(--rro-cta) !important;
    border-radius: 8px !important;
}

[data-testid="stAlert"] *,
[data-baseweb="notification"] * {
    color: var(--rro-text) !important;
}

/* Resultaten in dezelfde hoofdkaart (geen aparte bordered card) */
[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-results-section) {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0.35rem 0 0 0 !important;
}

.rro-results-section {
    padding: 0.25rem 0 0;
    border-top: 1px solid var(--rro-border);
    margin-top: 0.4rem;
}

/* Filterrij: ruimte onder platforms/type/datums */
[data-testid="stMain"] [data-testid="stHorizontalBlock"]:has([data-testid="stMultiSelect"]) {
    margin-bottom: 1.5rem !important;
    gap: 1rem !important;
    flex-wrap: wrap !important;
}

.rro-results-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 1.5rem 0 0.35rem 0;
    padding-bottom: 0.3rem;
}

.rro-results-header h2 {
    margin: 0;
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--rro-text);
}

div.rro-results-totals,
.rro-results-totals {
    display: flex !important;
    flex-wrap: wrap !important;
    align-items: center !important;
    gap: 1rem !important;
    color: var(--rro-text-muted) !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    line-height: 1.45 !important;
    margin: 0 !important;
    padding: 0 !important;
    background: transparent !important;
    background-color: transparent !important;
    border: 0 !important;
    border-width: 0 !important;
    border-style: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
}

.rro-results-totals .rro-stat {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-right: 0;
}

/* Totals sit inside a Streamlit element container; margin there creates real
   space before the next sibling (first result card). */
[data-testid="stMain"] [data-testid="stElementContainer"]:has(.rro-results-totals) {
    margin-bottom: 20px !important;
}

.rro-comment-group {
    margin: -4px 0 14px 0;
    padding: 10px 12px 2px 12px;
    border-left: 2px solid var(--rro-cta);
    background: rgba(20, 27, 39, 0.55);
    border-radius: 0 8px 8px 0;
}

.rro-comment-group-title {
    color: var(--rro-text-muted);
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    margin-bottom: 8px;
}

.rro-comment-item {
    padding: 6px 0;
    border-top: 1px solid var(--rro-border);
}

.rro-comment-item:first-of-type {
    border-top: none;
}

.rro-comment-item-head {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    margin-bottom: 3px;
}

.rro-comment-card {
    max-width: 100%;
    background: var(--rro-card);
    border: 1px solid var(--rro-border);
    border-left: 2px solid var(--rro-cta);
    border-radius: var(--rro-radius-sm);
    padding: 10px 12px 14px;
    margin-bottom: 10px;
    box-shadow: none;
    transition: border-color 0.15s ease;
    overflow: visible;
}

.rro-comment-card:hover {
    border-color: var(--rro-cta);
}

.rro-comment-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--rro-text-muted);
    font-size: 0.74rem;
    font-weight: 700;
    margin-bottom: 6px;
}

.rro-comment-label .rro-svg-icon-sm {
    width: 11px;
    height: 11px;
}

.rro-comment-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    margin-bottom: 4px;
}

.rro-comment-date {
    color: var(--rro-text-muted);
    font-size: 0.74rem;
}

.rro-comment-text {
    color: var(--rro-text);
    font-size: 0.86rem;
    line-height: 1.4;
    word-break: break-word;
}

.rro-comment-parent {
    color: var(--rro-text-muted);
    font-size: 0.74rem;
    margin-top: 5px;
    font-style: italic;
}

.rro-comment-link {
    display: inline-block;
    margin-top: 6px;
    color: var(--rro-cta) !important;
    font-size: 0.78rem;
    text-decoration: none;
}

.rro-comment-link:hover {
    text-decoration: underline;
}

/* Resultaatkaarten: style ONLY the card's own BorderWrapper.
   NEVER use :has(.rro-result-card-marker) on stVerticalBlock — after search the
   main column also :has markers and then inherits card padding + height:auto,
   which expands leftover component iframes above the title (~159px each). */
.rro-result-card-marker {
    display: none !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(> div .rro-result-card-marker),
[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker),
[data-testid="stLayoutWrapper"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] .rro-result-card-marker) {
    background: #232E3B !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: 0.5rem !important;
    padding: 1rem !important;
    margin: 0 0 12px 0 !important;
    overflow: visible !important;
    box-shadow: none !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker):hover {
    border-color: var(--rro-border) !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    [data-testid="stHorizontalBlock"] {
    align-items: flex-start !important;
    gap: 0.75rem !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    [data-testid="stImage"],
[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    [data-testid="stImageContainer"],
[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    [data-testid="stHtml"] {
    margin: 0 !important;
    min-height: 0 !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    [data-testid="stElementContainer"]:has([data-testid="stHtml"]) {
    margin: 0 !important;
    padding: 0 !important;
    min-height: 0 !important;
}

[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    [data-testid="stImage"] img,
[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    [data-testid="stImageContainer"] img,
[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    [data-testid="stHtml"] img,
[data-testid="stVerticalBlockBorderWrapper"]:has(.rro-result-card-marker)
    .rro-thumb {
    width: 100% !important;
    height: auto !important;
    max-width: none !important;
    aspect-ratio: 1 / 1 !important;
    object-fit: cover !important;
    border-radius: var(--rro-radius-sm) !important;
    border: 1px solid var(--rro-border) !important;
    background: var(--rro-input);
    display: block !important;
}

.rro-result-card {
    display: grid;
    grid-template-columns: 160px 1fr 120px;
    gap: 12px;
    align-items: start;
    background: var(--rro-card);
    border: 1px solid var(--rro-border);
    border-radius: var(--rro-radius);
    padding: 12px 12px 18px;
    margin-bottom: 12px;
    box-shadow: none;
    transition: border-color 0.15s ease;
    overflow: visible;
}

.rro-result-card:hover {
    border-color: var(--rro-border);
    box-shadow: none;
}

.rro-thumb {
    width: 100%;
    aspect-ratio: 1 / 1;
    height: auto;
    border-radius: var(--rro-radius-sm);
    object-fit: cover;
    border: 1px solid var(--rro-border);
    background: var(--rro-input);
    transition: border-color 0.15s ease;
    display: block;
}

.rro-result-card:hover .rro-thumb,
.rro-result-card:hover .rro-thumb-placeholder {
    border-color: var(--rro-border);
}

.rro-thumb-placeholder {
    width: 100%;
    aspect-ratio: 1 / 1;
    border-radius: var(--rro-radius-sm);
    border: 1px dashed var(--rro-border);
    background: var(--rro-input);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--rro-text-muted);
    font-size: 0.68rem;
    text-align: center;
    padding: 6px;
    transition: border-color 0.15s ease;
}

.rro-card-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    margin-bottom: 6px;
}

.badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.02em;
}

.badge-platform .rro-svg-icon {
    width: 12px;
    height: 12px;
}

.badge-type .rro-svg-icon-sm {
    width: 10px;
    height: 10px;
}

.badge-instagram,
.badge-facebook {
    background: var(--rro-badge);
    color: var(--rro-text);
    border: 1px solid var(--rro-border);
}

.badge-post,
.badge-content {
    background: rgba(184, 120, 68, 0.14);
    color: var(--rro-cta);
    border: 1px solid rgba(184, 120, 68, 0.45);
}

.badge-comment {
    background: var(--rro-badge);
    color: var(--rro-text);
    border: 1px solid var(--rro-border);
}

.badge-match {
    font-size: 0.66rem;
    padding: 2px 7px;
}

.badge-caption {
    background: rgba(232, 226, 216, 0.08);
    color: var(--rro-text);
    border: 1px solid rgba(232, 226, 216, 0.22);
}

.badge-hashtag {
    background: rgba(184, 120, 68, 0.14);
    color: var(--rro-cta);
    border: 1px solid rgba(184, 120, 68, 0.55);
}

.badge-tag {
    background: rgba(161, 186, 202, 0.14);
    color: #A1BACA;
    border: 1px solid rgba(161, 186, 202, 0.45);
}

.badge-unavailable {
    background: rgba(242, 240, 236, 0.06);
    color: var(--rro-text-muted);
    border: 1px solid var(--rro-border);
}

.rro-unavailable-notice {
    margin: 0 0 6px 0;
    padding: 6px 8px;
    border-radius: var(--rro-radius-sm);
    border: 1px solid var(--rro-border);
    background: rgba(242, 240, 236, 0.04);
    color: var(--rro-text-muted);
    font-size: 0.76rem;
    line-height: 1.35;
}

.rro-card-date {
    color: var(--rro-text-muted);
    font-size: 0.76rem;
    margin-bottom: 4px;
}

.rro-card-text {
    color: var(--rro-text);
    font-size: 0.88rem;
    line-height: 1.4;
    word-break: break-word;
}

.rro-card-text--full {
    white-space: pre-wrap;
    line-height: 1.55;
    font-size: 0.9rem;
}

.rro-stat-value-inline--highlight {
    color: var(--rro-cta) !important;
    font-weight: 800 !important;
    font-size: 0.92rem !important;
}

.rro-card-stats-wrap {
    display: block !important;
    width: 100% !important;
    padding: 0 0 2px 0 !important;
    margin: 0 !important;
    overflow: visible !important;
}

.rro-card-stats {
    display: flex !important;
    flex-wrap: wrap !important;
    align-items: center !important;
    gap: 1rem !important;
    margin: 10px 0 0 0 !important;
    padding: 10px 12px 12px !important;
    color: var(--rro-text-muted) !important;
    font-size: 0.78rem !important;
    line-height: 1.45 !important;
    background: transparent !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: var(--rro-radius-sm) !important;
    overflow: visible !important;
    min-height: auto !important;
    height: auto !important;
    max-height: none !important;
    box-sizing: border-box !important;
}

.rro-card-stats-spacer {
    display: block !important;
    height: 10px !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    flex-shrink: 0 !important;
}

.rro-stat {
    display: inline-flex !important;
    align-items: center !important;
    gap: 4px !important;
    white-space: nowrap !important;
    line-height: 1.35 !important;
}

.rro-stat-svg {
    width: 13px;
    height: 13px;
    flex-shrink: 0;
    display: block;
    color: var(--rro-cta);
}

.rro-stat-label-inline {
    color: var(--rro-text-muted);
    font-weight: 500;
    line-height: 1;
}

.rro-stat-value-inline {
    color: var(--rro-text);
    font-weight: 700;
    line-height: 1;
}

.rro-stat-missing {
    color: var(--rro-text-muted) !important;
    font-weight: 500 !important;
    font-style: italic;
    font-size: 0.82em;
}

.rro-results-views-note {
    margin: -0.2rem 0 0.75rem 0;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid var(--rro-border);
    background: var(--rro-input);
    color: var(--rro-text-muted);
    font-size: 0.8rem;
    line-height: 1.4;
}

.rro-results-views-note code {
    color: var(--rro-text);
    font-size: 0.78rem;
}

.rro-totals-sep {
    display: none;
}

.rro-results-totals .rro-stat-label-inline {
    font-weight: 600;
}

.rro-card-text .hashtag,
.hashtag {
    color: var(--rro-cta);
    font-weight: 700;
}

.rro-card-text .mention,
.mention {
    color: #A1BACA;
    font-weight: 700;
}

.text-match {
    background: var(--rro-highlight);
    color: #FFFFFF;
    border-radius: 4px;
    padding: 0 4px;
}

.hashtag-match,
.mention-match {
    text-decoration: underline;
    text-decoration-color: var(--rro-highlight);
    text-decoration-thickness: 2px;
    text-underline-offset: 3px;
    background: transparent;
}

a.rro-btn-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    border: 1px solid var(--rro-border) !important;
    color: var(--rro-text) !important;
    background: transparent;
    border-radius: var(--rro-radius-sm) !important;
    padding: 8px 10px;
    text-decoration: none !important;
    font-weight: 700;
    font-size: 0.82rem;
    text-align: center;
    cursor: pointer;
    transition: background-color 0.15s ease, border-color 0.15s ease;
}

a.rro-btn-link:hover,
a.rro-btn-link:focus,
a.rro-btn-link:focus-visible {
    border-color: var(--rro-border) !important;
    box-shadow: none !important;
    outline: none !important;
    background: var(--rro-input) !important;
    color: var(--rro-text) !important;
    text-decoration: none !important;
    cursor: pointer;
}

.rro-btn-disabled {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    border: 1px solid var(--rro-border);
    color: var(--rro-text-muted);
    background: transparent;
    border-radius: var(--rro-radius-sm);
    padding: 8px 10px;
    font-weight: 700;
    font-size: 0.82rem;
    text-align: center;
}

@media (max-width: 700px) {
    .rro-result-card {
        grid-template-columns: 96px 1fr;
    }
    .rro-result-card > div:last-child {
        grid-column: 1 / -1;
    }
    .rro-thumb, .rro-thumb-placeholder {
        width: 100%;
        height: auto;
        aspect-ratio: 1 / 1;
    }
    .rro-page-title,
    h1 {
        font-size: 26px !important;
    }
}

/* Tabs: Zoeken / Beste prestaties */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    border-bottom: 1px solid var(--rro-border);
    margin-bottom: 1rem;
}

.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: var(--rro-text-muted) !important;
    border-radius: var(--rro-radius-sm) var(--rro-radius-sm) 0 0 !important;
    font-weight: 700 !important;
    padding: 0.55rem 1rem !important;
}

.stTabs [aria-selected="true"] {
    background: rgba(184, 120, 68, 0.12) !important;
    color: var(--rro-text) !important;
    border-bottom: 2px solid var(--rro-cta) !important;
}

.rro-perf-refresh-spacer {
    height: 1.45rem;
}

.rro-perf-section-header {
    margin: 1.5rem 0 0.85rem 0;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--rro-border);
    color: var(--rro-text);
    font-size: 1.15rem;
    font-weight: 700;
    line-height: 1.35;
}

.rro-perf-section-divider {
    border: 0;
    border-top: 1px solid var(--rro-border);
    margin: 1.75rem 0 0.25rem 0;
}

.rro-perf-rank-banner {
    margin: 0 0 12px 0;
    padding: 10px 12px;
    border-radius: var(--rro-radius-sm);
    border: 1px solid var(--rro-border);
    background: #313945;
}

.rro-perf-rank-line {
    display: block;
    color: var(--rro-text-muted);
    font-size: 0.86rem;
    font-weight: 600;
    line-height: 1.45;
}

.rro-perf-rank-badge {
    color: var(--rro-text);
    font-weight: 800;
}

.rro-perf-rank-value {
    color: var(--rro-text);
    font-weight: 800;
}

.rro-empty-state,
.rro-performance-empty {
    margin: 0 0 0.75rem 0;
    padding: 12px 14px;
    border-radius: var(--rro-radius-sm);
    border: 1px dashed var(--rro-border);
    color: var(--rro-text-muted);
    font-size: 0.84rem;
}

[data-testid="stSelectbox"] label,
[data-testid="stSelectbox"] label p {
    color: var(--rro-text) !important;
    font-size: 0.82rem !important;
    font-weight: 700 !important;
    margin-bottom: 0.2rem !important;
}

[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    background-color: #4B5560 !important;
    color: var(--rro-text) !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: var(--rro-radius-sm) !important;
    min-height: var(--rro-control-h) !important;
    box-shadow: none !important;
}

[data-testid="stSelectbox"] div[data-baseweb="select"] > div:hover,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div[aria-expanded="true"] {
    background-color: var(--rro-input-hover) !important;
    border-color: var(--rro-border) !important;
    box-shadow: none !important;
}

[data-testid="stSelectbox"] svg {
    fill: var(--rro-text) !important;
}

.rro-comparison-label {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    margin: 0 0 0.35rem 0;
    color: var(--rro-text);
    font-size: 0.82rem;
    font-weight: 700;
}

.rro-comparison-label span {
    color: var(--rro-text-muted);
    font-weight: 600;
}

.rro-comparison-error {
    margin: 0.15rem 0 0.45rem 0;
    color: #E7C4A8;
    font-size: 0.82rem;
    font-weight: 600;
}

.rro-competitor-name {
    display: flex;
    align-items: center;
    min-height: var(--rro-control-h);
    padding: 0 0.85rem;
    border: 1px solid var(--rro-border);
    border-radius: var(--rro-radius-sm);
    background: #1A2230;
    color: var(--rro-text);
    font-size: 0.9rem;
    font-weight: 600;
}

/* Compact “+” under the competitor list (Streamlit maps help= to title) */
button[title="Concurrent toevoegen"] {
    min-width: 2.5rem !important;
    padding-left: 0.55rem !important;
    padding-right: 0.55rem !important;
    font-size: 1.25rem !important;
    font-weight: 700 !important;
    line-height: 1 !important;
}

.rro-comparison-block {
    margin: 0.35rem 0 0.5rem 0;
}

.rro-comparison-section {
    margin: 0.35rem 0 0.45rem 0;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--rro-border);
    color: var(--rro-text);
    font-size: 1.05rem;
    font-weight: 700;
    line-height: 1.35;
}

.rro-comparison-note {
    margin: 0 0 0.65rem 0;
    color: var(--rro-text-muted);
    font-size: 0.86rem;
    line-height: 1.4;
}

.rro-comparison-growth .rro-empty-state {
    min-height: 120px;
    display: flex;
    align-items: center;
}

[data-testid="stMarkdownContainer"] .rro-comparison-table-wrap,
.rro-comparison-table-wrap {
    width: 100% !important;
    max-width: 100% !important;
    overflow-x: auto !important;
    margin: 0 0 0.75rem 0 !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: var(--rro-radius-sm) !important;
    background: #1A2230 !important;
    box-sizing: border-box !important;
}

[data-testid="stMarkdownContainer"] table.rro-comparison-table,
table.rro-comparison-table {
    width: 100% !important;
    min-width: 720px !important;
    border-collapse: collapse !important;
    table-layout: auto !important;
    color: var(--rro-text) !important;
    font-size: 0.84rem !important;
    line-height: 1.35 !important;
    margin: 0 !important;
}

table.rro-comparison-table th,
table.rro-comparison-table td {
    padding: 10px 10px !important;
    border-bottom: 1px solid var(--rro-border) !important;
    vertical-align: top !important;
    text-align: left !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
    min-width: 0 !important;
}

table.rro-comparison-table th {
    color: var(--rro-text-muted) !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    background: #151C28 !important;
}

table.rro-comparison-table tr:last-child td {
    border-bottom: 0 !important;
}

table.rro-comparison-table .rro-num {
    text-align: right !important;
    font-variant-numeric: tabular-nums !important;
    white-space: nowrap !important;
}

table.rro-comparison-table .rro-muted {
    color: var(--rro-text-muted) !important;
    font-style: italic !important;
    text-align: left !important;
}

table.rro-comparison-table th {
    white-space: nowrap !important;
}

table.rro-comparison-table .rro-account-cell strong {
    display: block !important;
    color: var(--rro-text) !important;
}

table.rro-comparison-table small,
.rro-comparison-top-row small,
.rro-comparison-growth-row small {
    color: var(--rro-text-muted) !important;
    font-size: 0.74rem !important;
}

.rro-comparison-top-row,
.rro-comparison-growth-row {
    display: block !important;
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    margin: 0 0 0.55rem 0 !important;
    padding: 10px 12px !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: var(--rro-radius-sm) !important;
    background: #1A2230 !important;
    color: var(--rro-text) !important;
    font-size: 0.84rem !important;
    line-height: 1.35 !important;
    overflow-wrap: anywhere !important;
}

.rro-comparison-top-row {
    display: grid !important;
    grid-template-columns: 42px minmax(0, 1fr) !important;
    gap: 8px !important;
    align-items: start !important;
}

.rro-comparison-top-rank {
    font-weight: 800 !important;
    color: var(--rro-cta) !important;
}

.rro-week-alert {
    background: #3a2a1c !important;
    border: 1px solid var(--rro-cta) !important;
    border-radius: var(--rro-radius-sm) !important;
    padding: 12px 14px !important;
    margin: 0 0 12px 0 !important;
    font-weight: 700 !important;
}
.rro-week-meta {
    display: grid !important;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px !important;
    margin: 0 0 8px 0 !important;
}
.rro-week-meta div {
    background: #1A2230 !important;
    border: 1px solid var(--rro-border) !important;
    border-radius: var(--rro-radius-sm) !important;
    padding: 10px 12px !important;
    font-size: 0.9rem !important;
}

@media print {
    section[data-testid="stSidebar"],
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    .stButton,
    .stDownloadButton,
    [data-testid="stSelectbox"],
    [data-testid="stDateInput"] {
        display: none !important;
    }
    .stApp,
    section.main,
    [data-testid="stMain"],
    div.stMainBlockContainer.block-container {
        background: #ffffff !important;
        color: #1c1915 !important;
        box-shadow: none !important;
        border: 0 !important;
    }
    .rro-week-meta div,
    table.rro-comparison-table,
    table.rro-comparison-table th,
    table.rro-comparison-table td,
    h1, h2, h3, p, li, span, div {
        color: #1c1915 !important;
        background: #ffffff !important;
    }
}
</style>
"""
