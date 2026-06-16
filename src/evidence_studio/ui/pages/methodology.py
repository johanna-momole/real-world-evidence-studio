"""Methodology and Limitations page — study design narrative and disclaimers."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from evidence_studio.ui.components import show_disclaimer

_DOCS_DIR = Path(__file__).resolve().parents[4] / "docs"


def show() -> None:
    """Render the Methodology and Limitations page."""
    st.title("Methodology & Limitations")
    show_disclaimer()

    tabs = st.tabs(["Study Design", "Limitations", "OMOP Mapping", "Architecture"])

    with tabs[0]:
        _render_doc("methodology.md", "Study design documentation not found.")
    with tabs[1]:
        _render_doc("limitations.md", "Limitations documentation not found.")
    with tabs[2]:
        _render_doc("omop_mapping.md", "OMOP mapping documentation not found.")
    with tabs[3]:
        _render_doc("architecture.md", "Architecture documentation not found.")


def _render_doc(filename: str, fallback: str) -> None:
    """Render a Markdown doc file, or show a fallback message."""
    path = _DOCS_DIR / filename
    if path.exists():
        st.markdown(path.read_text(encoding="utf-8"))
    else:
        st.warning(fallback)
