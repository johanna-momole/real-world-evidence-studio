"""Evidence Brief page — downloadable Markdown / HTML brief via Jinja2 template."""

from __future__ import annotations

import streamlit as st

from evidence_studio.config import AppConfig
from evidence_studio.ui.components import no_cohort_banner, show_disclaimer


def show() -> None:
    """Render the Evidence Brief page."""
    st.title("Evidence Brief")
    show_disclaimer()

    config = AppConfig()
    if not config.resolved_db_path.exists():
        no_cohort_banner()
        return

    from evidence_studio.database import get_connection, table_exists

    conn = get_connection(config.resolved_db_path)

    if not table_exists(conn, "analytics", "analysis_dataset"):
        no_cohort_banner()
        return

    st.markdown(
        "Generate a structured summary of this study run. "
        "The brief embeds the mandatory synthetic-data disclaimer and lists "
        "all study parameters, concept-set decisions, and analytic results."
    )

    fmt = st.radio("Output format", ["Markdown", "HTML"], horizontal=True)

    if st.button("Generate brief", type="primary"):
        with st.spinner("Rendering evidence brief…"):
            from evidence_studio.reporting import render_brief

            run_id = st.session_state.get("cohort_run_id", "latest")
            brief_text = render_brief(conn, run_id=run_id, output_format=fmt.lower())

        ext = "md" if fmt == "Markdown" else "html"
        mime = "text/markdown" if fmt == "Markdown" else "text/html"

        st.download_button(
            label=f"Download {fmt}",
            data=brief_text.encode("utf-8"),
            file_name=f"evidence_brief_{run_id}.{ext}",
            mime=mime,
        )

        st.divider()
        st.subheader("Preview")
        if fmt == "Markdown":
            st.markdown(brief_text)
        else:
            st.components.v1.html(brief_text, height=600, scrolling=True)
