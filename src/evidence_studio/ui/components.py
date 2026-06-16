"""Shared Streamlit widget helpers used across pages."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

DISCLAIMER = (
    "> **Synthetic data only.** All results are derived from Synthea-generated "
    "synthetic records. They do not represent real patients, clinical outcomes, "
    "treatment effectiveness, drug safety, or incidence rates. This project must "
    "not be used for clinical decisions, regulatory submissions, or public health "
    "reporting."
)


def show_disclaimer() -> None:
    """Render the mandatory synthetic-data disclaimer."""
    st.info(
        "**Synthetic data only.** All results are derived from Synthea-generated "
        "records. They do not represent real patients or clinical outcomes and must "
        "not be used for clinical decisions or public health reporting.",
        icon="⚠️",
    )


def no_data_banner(page_hint: str = "") -> None:
    """Render a banner directing the user to load Synthea data."""
    st.warning(
        "**No Synthea data loaded.** "
        f"{page_hint + ' ' if page_hint else ''}"
        "Place Synthea CSV files in `data/raw/` then use the CLI or the "
        "ingestion step to load them into the database. "
        "See [docs/data_setup.md](docs/data_setup.md) for instructions.",
        icon="📂",
    )


def no_cohort_banner() -> None:
    """Render a banner directing the user to build a cohort."""
    st.warning(
        "**No cohort has been built yet.** "
        "Go to **Study Designer** to configure inclusion/exclusion criteria, "
        "then click **Build Cohort** to generate the analysis population.",
        icon="👥",
    )


def section_header(title: str, help_text: str = "") -> None:
    """Render a consistent section header with optional help text."""
    st.subheader(title, help=help_text or None)


def download_csv_button(df: pd.DataFrame, filename: str, label: str = "Download CSV") -> None:
    """Render a download button for a DataFrame as CSV."""
    st.download_button(
        label=label,
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
    )


def metric_row(metrics: list[tuple[str, str, Optional[str]]]) -> None:
    """Render a row of st.metric tiles from (label, value, delta) tuples."""
    cols = st.columns(len(metrics))
    for col, (label, value, delta) in zip(cols, metrics, strict=False):
        col.metric(label=label, value=value, delta=delta)


def status_badge(ok: bool, ok_text: str = "OK", fail_text: str = "Missing") -> str:
    """Return a coloured emoji badge string for a boolean status."""
    return f"✅ {ok_text}" if ok else f"❌ {fail_text}"


def render_sidebar(db_exists: bool) -> None:
    """Render the global sidebar with active study config and run ID."""
    with st.sidebar:
        st.markdown("### Real-World Evidence Studio")
        st.caption("Portfolio · Synthetic data · Educational use only")
        st.divider()

        run_id = st.session_state.get("cohort_run_id")
        cfg = st.session_state.get("study_config")

        st.markdown("**Active study run**")
        if run_id:
            st.code(run_id[:16] + "…", language=None)
        else:
            st.caption("No run built yet.")

        st.divider()
        st.markdown("**Study configuration**")
        if cfg:
            st.markdown(f"- Follow-up: **{cfg.follow_up_days} days**")
            st.markdown(f"- Baseline: **{cfg.baseline_days} days**")
            st.markdown(f"- Min age: **{cfg.min_age_at_index}**")
            excl = []
            if cfg.exclude_type1_diabetes:
                excl.append("T1DM")
            if cfg.exclude_gestational_diabetes:
                excl.append("Gestational DM")
            if cfg.exclude_pregnancy_at_index:
                excl.append("Pregnancy")
            if excl:
                st.markdown(f"- Exclusions: {', '.join(excl)}")
        else:
            st.caption("Using defaults (180-day follow-up).")

        st.divider()
        st.markdown("**Database**")
        if db_exists:
            st.caption("✅ Connected")
        else:
            st.caption("⬜ Not initialised")
