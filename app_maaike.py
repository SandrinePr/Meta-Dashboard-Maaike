"""Streamlit fallback for Maaike's clients.

The React app in frontend/ with the API in maaike_web/ is the development base.
This entry stays available. Start locally, from the project root:

    streamlit run app_maaike.py

This process does not start the TAOL scheduler and does not open social_search.db.
It does not call an AI provider. Meta is called only after someone uses
Koppelen met Meta or Controleer koppeling.
"""

from __future__ import annotations

import streamlit as st

from maaike.ui import render_app


def main() -> None:
    st.set_page_config(
        page_title="Maaike",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render_app()


if __name__ == "__main__":
    main()
