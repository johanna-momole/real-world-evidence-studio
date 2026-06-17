"""Overview page — project summary, data source status, and disclaimer."""

from __future__ import annotations

import streamlit as st

from evidence_studio.config import AppConfig
from evidence_studio.ui.components import show_disclaimer


def show() -> None:
    """Render the Overview page."""
    st.title("Real-World Evidence Studio")
    show_disclaimer()

    st.markdown(
        """
        **Real-World Evidence Studio** demonstrates transparent RWE generation
        using synthetic EHR data in [Synthea](https://github.com/synthetichealth/synthea)-compatible
        CSV format. This is a portfolio and educational project only — all patient records are
        synthetic and results must not be used for any clinical purpose.

        **Primary clinical question**

        > Among synthetic adult patients with type 2 diabetes who initiate a
        > GLP-1 receptor agonist therapy, what patient characteristics are
        > associated with emergency department (ED) utilization during the
        > following 180 days?
        """
    )

    config = AppConfig()

    st.divider()
    _render_data_flow()

    st.divider()
    _render_data_status(config)

    st.divider()
    _render_recent_run(config)

    st.divider()
    st.subheader("Navigation guide")
    st.markdown(
        """
        | Page | Purpose |
        |------|---------|
        | **Data Quality** | Review manifest, record counts, and DQ rule results |
        | **Study Designer** | Configure study parameters and build the cohort |
        | **Cohort Attrition** | Visualise the inclusion/exclusion cascade |
        | **Results** | Cohort characteristics, outcomes, and regression |
        | **SQL & Audit Trail** | Inspect generated SQL and run history |
        | **Evidence Brief** | Download a Markdown/HTML study summary |
        | **Methodology** | Study design narrative and limitations |
        """
    )


def _render_data_flow() -> None:
    """Render a concise data-flow summary."""
    st.subheader("Data flow")
    st.markdown(
        """
        ```
        Source CSVs  →  raw schema  →  standardized schema
                                               ↓
                                     Concept matching (GLP-1 drugs, T2DM)
                                               ↓
                                     Cohort build (attrition cascade)
                                               ↓
                              Baseline features + Outcome ascertainment
                                               ↓
                              Logistic regression + Evidence brief
        ```
        All transformations run inside DuckDB. The pipeline is reproducible
        via the study-run ID recorded in every analysis.
        """
    )


def _render_data_status(config: AppConfig) -> None:
    """Render source-file status and database status."""
    st.subheader("Data source status")

    files = config.required_files_present
    all_present = all(files.values())

    if all_present:
        st.success(
            f"All required source files found in `{config.synthea_data_dir}`.",
            icon="✅",
        )
    else:
        missing = [k for k, v in files.items() if not v]
        st.warning(
            f"Missing required files: {', '.join(missing)}. "
            "See [docs/data_setup.md](docs/data_setup.md) for setup instructions.",
            icon="📂",
        )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Required source files**")
        for name, present in files.items():
            icon = "✅" if present else "❌"
            st.markdown(f"{icon} `{name}.csv`")
    with col2:
        st.markdown("**Database**")
        db_exists = config.resolved_db_path.exists()
        icon = "✅" if db_exists else "⬜"
        st.markdown(f"{icon} `{config.db_path}`")
        if not db_exists:
            st.caption("Database will be created on first ingestion.")

    st.divider()
    st.subheader("Quick start")
    st.code(
        "# 1. Prepare source data (see docs/data_setup.md)\n"
        "# 2. Ingest into DuckDB\n"
        "evidence-studio ingest --data-dir data/raw\n\n"
        "# 3. Build the cohort\n"
        "evidence-studio build-cohort\n\n"
        "# 4. Run analysis\n"
        "evidence-studio analyze",
        language="bash",
    )


def _render_recent_run(config: AppConfig) -> None:
    """Render the most recent study run summary if the database exists."""
    st.subheader("Most recent study run")

    if not config.resolved_db_path.exists():
        st.caption("No database found. Ingest data to create one.")
        return

    from evidence_studio.database import get_connection, run_query, table_exists

    try:
        conn = get_connection(config.resolved_db_path)
        if not table_exists(conn, "audit", "study_runs"):
            st.caption("No study runs recorded yet.")
            return

        df = run_query(
            conn,
            "SELECT run_id, run_timestamp, data_source, n_enrolled, n_with_outcome "
            "FROM audit.study_runs ORDER BY run_timestamp DESC LIMIT 1",
        )
        if df.empty:
            st.caption("No study runs recorded yet.")
            return

        row = df.iloc[0]
        run_id_short = str(row["run_id"])[:16] + "…"
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Run ID", run_id_short)
        col2.metric("Timestamp", str(row["run_timestamp"])[:16])
        col3.metric("Enrolled", int(row["n_enrolled"]) if row["n_enrolled"] else "—")
        col4.metric(
            "ED outcomes",
            int(row["n_with_outcome"]) if row["n_with_outcome"] else "—",
        )
        ds = str(row.get("data_source") or "unknown_synthetic_source")
        st.caption(f"Full run ID: `{row['run_id']}`  |  Data source: `{ds}`")
    except Exception:
        st.caption("Could not load run history.")
