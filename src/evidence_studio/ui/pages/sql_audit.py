"""SQL and Audit Trail page — generated SQL viewer, assumption log, run history."""

from __future__ import annotations

import streamlit as st

from evidence_studio.config import AppConfig
from evidence_studio.ui.components import no_data_banner, show_disclaimer


def show() -> None:
    """Render the SQL and Audit Trail page."""
    st.title("SQL & Audit Trail")
    show_disclaimer()
    st.caption(
        "This page provides full transparency into the SQL executed, "
        "assumptions logged, and the provenance of each study run."
    )

    config = AppConfig()
    if not config.resolved_db_path.exists():
        no_data_banner("Run ingestion and cohort build to populate the audit trail.")
        return

    from evidence_studio.database import get_connection

    conn = get_connection(config.resolved_db_path)

    tabs = st.tabs(
        ["Run Summary", "Generated SQL", "Data Manifest", "Assumption Log", "Run History"]
    )

    with tabs[0]:
        _render_run_summary(conn)
    with tabs[1]:
        _render_sql_log(conn)
    with tabs[2]:
        _render_manifest(conn)
    with tabs[3]:
        _render_assumption_log(conn)
    with tabs[4]:
        _render_run_history(conn)


def _render_run_summary(conn) -> None:
    """Render study-run ID, configuration, and key counts."""
    import json

    from evidence_studio.database import run_query, table_exists

    st.subheader("Active study run")

    run_id = st.session_state.get("cohort_run_id")

    if not table_exists(conn, "audit", "study_runs"):
        st.info("No study runs found.")
        return

    if run_id:
        df = run_query(
            conn,
            "SELECT * FROM audit.study_runs WHERE run_id = ? LIMIT 1",
            {"run_id": run_id},
        )
    else:
        df = run_query(
            conn,
            "SELECT * FROM audit.study_runs ORDER BY run_timestamp DESC LIMIT 1",
        )

    if df.empty:
        st.info("No study runs found.")
        return

    row = df.iloc[0]
    st.markdown(f"**Run ID:** `{row['run_id']}`")
    st.markdown(f"**Timestamp:** {row['run_timestamp']}")
    col1, col2 = st.columns(2)
    col1.metric("Enrolled", int(row["n_enrolled"]) if row.get("n_enrolled") is not None else "—")
    col2.metric(
        "ED outcomes", int(row["n_with_outcome"]) if row.get("n_with_outcome") is not None else "—"
    )

    if row.get("config_json"):
        st.subheader("Study configuration")
        try:
            cfg = json.loads(row["config_json"])
            import pandas as pd

            cfg_df = pd.DataFrame([{"Parameter": k, "Value": str(v)} for k, v in cfg.items()])
            st.dataframe(cfg_df, use_container_width=True, hide_index=True)
        except Exception:
            st.code(row["config_json"])

    _render_version_info()


def _render_version_info() -> None:
    """Show application version and package metadata."""
    import evidence_studio

    st.subheader("Application version")
    col1, col2 = st.columns(2)
    col1.markdown(f"**evidence-studio:** `{evidence_studio.__version__}`")
    col2.markdown("**Python:** `3.11+` required")

    try:
        import duckdb
        import pandas as pd
        import streamlit

        st.markdown(
            f"DuckDB `{duckdb.__version__}` · "
            f"Streamlit `{streamlit.__version__}` · "
            f"Pandas `{pd.__version__}`"
        )
    except Exception:
        pass


def _render_sql_log(conn) -> None:
    """Render the generated SQL log with syntax highlighting."""
    from evidence_studio.database import run_query, table_exists

    st.subheader("Generated SQL")

    if not table_exists(conn, "audit", "generated_sql"):
        st.info("No SQL log found.")
        return

    df = run_query(
        conn,
        "SELECT label, created_at FROM audit.generated_sql ORDER BY created_at DESC",
    )
    if df.empty:
        st.info("No SQL recorded yet.")
        return

    selected_label = st.selectbox("Select statement", df["label"].tolist())
    if selected_label:
        sql_row = run_query(
            conn,
            "SELECT sql_text FROM audit.generated_sql WHERE label = ? "
            "ORDER BY created_at DESC LIMIT 1",
            {"label": selected_label},
        )
        if not sql_row.empty:
            st.code(sql_row["sql_text"].iloc[0], language="sql")


def _render_manifest(conn) -> None:
    """Render the source-file manifest with hashes."""
    from evidence_studio.database import run_query, table_exists

    st.subheader("Source file manifest")
    st.caption("SHA-256 hashes allow verification that source data matches a given study run.")

    if not table_exists(conn, "audit", "data_manifest"):
        st.info("No manifest found.")
        return

    df = run_query(
        conn,
        "SELECT file_name, row_count, file_size_bytes, sha256_hash, data_source, load_timestamp "
        "FROM audit.data_manifest ORDER BY load_timestamp DESC",
    )
    if df.empty:
        st.info("No manifest entries.")
    else:
        st.dataframe(df, use_container_width=True)


def _render_assumption_log(conn) -> None:
    """Render the assumption log."""
    from evidence_studio.database import run_query, table_exists

    st.subheader("Assumption log")
    st.caption("Processing decisions and assumptions recorded during the pipeline run.")

    if not table_exists(conn, "audit", "assumption_log"):
        st.info("No assumption log found.")
        return

    df = run_query(
        conn,
        "SELECT created_at, context, assumption_text FROM audit.assumption_log "
        "ORDER BY created_at DESC",
    )
    if df.empty:
        st.info("No assumptions recorded yet.")
        return
    st.dataframe(df, use_container_width=True)


def _render_run_history(conn) -> None:
    """Render the complete study-run history."""
    from evidence_studio.audit import get_run_history

    st.subheader("Study run history")
    st.caption(
        "Each row corresponds to one cohort build. "
        "The run ID encodes the configuration hash and timestamp."
    )
    df = get_run_history(conn)
    if df.empty:
        st.info("No study runs found. Build a cohort to create a run record.")
        return
    st.dataframe(df, use_container_width=True)
