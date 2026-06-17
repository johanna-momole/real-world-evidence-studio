"""Real-World Evidence Studio — Streamlit application entry point."""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Real-World Evidence Studio",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": (
            "**Real-World Evidence Studio** — synthetic EHR analytics portfolio. "
            "All data is synthetic. Results do not represent real patients "
            "or clinical outcomes."
        )
    },
)

from evidence_studio.config import AppConfig  # noqa: E402
from evidence_studio.ui.components import render_sidebar  # noqa: E402
from evidence_studio.ui.pages import (  # noqa: E402
    cohort_attrition,
    data_quality,
    evidence_brief,
    methodology,
    overview,
    results,
    sql_audit,
    study_designer,
)

_cfg = AppConfig()
render_sidebar(db_exists=_cfg.resolved_db_path.exists())

pg = st.navigation(
    {
        "Data": [
            st.Page(
                overview.show,
                title="Overview",
                icon="🏠",
                url_path="overview",
                default=True,
            ),
            st.Page(
                data_quality.show,
                title="Data Quality",
                icon="🔍",
                url_path="data-quality",
            ),
        ],
        "Study": [
            st.Page(
                study_designer.show,
                title="Study Designer",
                icon="⚙️",
                url_path="study-designer",
            ),
            st.Page(
                cohort_attrition.show,
                title="Cohort Attrition",
                icon="📊",
                url_path="cohort-attrition",
            ),
        ],
        "Analysis": [
            st.Page(
                results.show,
                title="Results",
                icon="📈",
                url_path="results",
            ),
        ],
        "Outputs": [
            st.Page(
                sql_audit.show,
                title="SQL & Audit Trail",
                icon="🔎",
                url_path="sql-audit",
            ),
            st.Page(
                evidence_brief.show,
                title="Evidence Brief",
                icon="📄",
                url_path="evidence-brief",
            ),
        ],
        "Documentation": [
            st.Page(
                methodology.show,
                title="Methodology & Limitations",
                icon="📚",
                url_path="methodology",
            ),
        ],
    }
)

pg.run()
