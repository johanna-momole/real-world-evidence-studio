"""Data Quality page — manifest, row counts, DQ rule results."""

from __future__ import annotations

import streamlit as st

from evidence_studio.config import AppConfig
from evidence_studio.ui.components import no_data_banner, show_disclaimer


@st.cache_resource
def _get_conn(db_path: str):
    """Return a cached DuckDB connection, keyed by path string."""
    from pathlib import Path

    from evidence_studio.database import get_connection

    return get_connection(Path(db_path))


def show() -> None:
    """Render the Data Quality page."""
    st.title("Data Quality")
    show_disclaimer()

    config = AppConfig()
    db_path = str(config.resolved_db_path)

    if not config.resolved_db_path.exists():
        no_data_banner("Run `evidence-studio ingest` to populate the database.")
        return

    conn = _get_conn(db_path)

    from evidence_studio.database import run_query, table_exists

    if not table_exists(conn, "audit", "data_manifest"):
        no_data_banner("Run `evidence-studio ingest` to see data quality results.")
        return

    tabs = st.tabs(
        ["Manifest", "Record Counts", "Patient Coverage", "DQ Rules", "Concept Availability"]
    )

    with tabs[0]:
        _render_manifest(conn, run_query, table_exists)
    with tabs[1]:
        _render_record_counts(conn, run_query, table_exists)
    with tabs[2]:
        _render_patient_coverage(conn, run_query, table_exists)
    with tabs[3]:
        _render_dq_results(conn, run_query, table_exists)
    with tabs[4]:
        _render_concept_availability(conn, run_query, table_exists)


def _render_manifest(conn, run_query, table_exists) -> None:
    """Render the data manifest section."""
    st.subheader("Source file manifest")
    st.caption(
        "Each row represents one CSV file loaded into the raw schema. "
        "SHA-256 hashes allow run-to-run reproducibility verification."
    )
    df = run_query(
        conn,
        "SELECT file_name, row_count, column_count, "
        "       file_size_bytes, sha256_hash, load_timestamp "
        "FROM audit.data_manifest ORDER BY load_timestamp DESC",
    )
    if df.empty:
        st.info("No manifest entries found.")
        return
    st.dataframe(df, use_container_width=True)


def _render_record_counts(conn, run_query, table_exists) -> None:
    """Render row counts for each standardized table."""
    st.subheader("Standardized record counts")
    tables = {
        "patients": "standardized.patients",
        "encounters": "standardized.encounters",
        "conditions": "standardized.conditions",
        "medications": "standardized.medications",
        "observations": "standardized.observations",
    }

    rows = []
    for label, full_table in tables.items():
        schema, tbl = full_table.split(".")
        if table_exists(conn, schema, tbl):
            n = int(run_query(conn, f"SELECT count(*) AS n FROM {full_table}")["n"].iloc[0])
        else:
            n = None
        rows.append({"Domain": label.title(), "Table": full_table, "Row count": n})

    import pandas as pd

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)


def _render_patient_coverage(conn, run_query, table_exists) -> None:
    """Render patient count and date coverage."""
    st.subheader("Patient and date coverage")

    if not table_exists(conn, "standardized", "patients"):
        st.info("Standardized patients table not found.")
        return

    stats = run_query(
        conn,
        "SELECT count(*) AS n_patients, "
        "       sum(CASE WHEN death_date IS NOT NULL THEN 1 ELSE 0 END) AS n_deceased, "
        "       min(birth_date) AS earliest_birth, "
        "       max(birth_date) AS latest_birth "
        "FROM standardized.patients",
    )
    row = stats.iloc[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total patients", int(row["n_patients"]))
    col2.metric("Deceased", int(row["n_deceased"]))
    col3.metric("Earliest birth", str(row["earliest_birth"])[:10] if row["earliest_birth"] else "—")
    col4.metric("Latest birth", str(row["latest_birth"])[:10] if row["latest_birth"] else "—")

    if table_exists(conn, "standardized", "encounters"):
        enc_stats = run_query(
            conn,
            "SELECT min(CAST(encounter_start AS DATE)) AS first_enc, "
            "       max(CAST(encounter_start AS DATE)) AS last_enc, "
            "       count(DISTINCT patient_id) AS n_with_enc "
            "FROM standardized.encounters",
        )
        erow = enc_stats.iloc[0]
        st.markdown("**Encounter date coverage**")
        col1, col2, col3 = st.columns(3)
        col1.metric("First encounter", str(erow["first_enc"])[:10] if erow["first_enc"] else "—")
        col2.metric("Last encounter", str(erow["last_enc"])[:10] if erow["last_enc"] else "—")
        col3.metric("Patients with encounters", int(erow["n_with_enc"]))

    st.subheader("Missingness by domain")
    _render_missingness(conn, run_query, table_exists)


def _render_missingness(conn, run_query, table_exists) -> None:
    """Render a missingness summary for key patient fields."""
    if not table_exists(conn, "standardized", "patients"):
        return

    checks = {
        "sex": "sex IS NULL OR sex = ''",
        "race": "race IS NULL OR race = ''",
        "ethnicity": "ethnicity IS NULL OR ethnicity = ''",
        "birth_date": "birth_date IS NULL",
    }
    n_total = int(run_query(conn, "SELECT count(*) AS n FROM standardized.patients")["n"].iloc[0])

    import pandas as pd

    rows = []
    for col, clause in checks.items():
        n_miss = int(
            run_query(
                conn,
                f"SELECT count(*) AS n FROM standardized.patients WHERE {clause}",
            )["n"].iloc[0]
        )
        pct = round(n_miss / n_total * 100, 1) if n_total else 0
        rows.append(
            {
                "Field": col,
                "Missing": n_miss,
                "% Missing": pct,
                "Flag": "⚠️ HIGH" if pct > 5 else "",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


def _render_dq_results(conn, run_query, table_exists) -> None:
    """Render the DQ rule results section."""
    st.subheader("Data quality rule results")

    if not table_exists(conn, "audit", "dq_results"):
        st.info("No DQ results found. Run `evidence-studio ingest` first.")
        return

    df = run_query(
        conn,
        "SELECT rule_name, status, affected_rows, message, checked_at "
        "FROM audit.dq_results ORDER BY status DESC, rule_name",
    )
    if df.empty:
        st.success("No DQ results recorded.")
        return

    failed = df[df["status"] == "FAIL"]
    warned = df[df["status"] == "WARN"]
    passed = df[df["status"] == "PASS"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Passed", len(passed), delta=None)
    col2.metric("Warnings", len(warned), delta=None)
    col3.metric("Failed", len(failed), delta=None)

    if not failed.empty:
        st.error(f"{len(failed)} DQ rule(s) **FAILED**.")
        st.dataframe(failed, use_container_width=True)

    if not warned.empty:
        st.warning(f"{len(warned)} DQ rule(s) produced **warnings**.")
        with st.expander("Warnings"):
            st.dataframe(warned, use_container_width=True)

    with st.expander(f"Passed rules ({len(passed)})"):
        st.dataframe(passed, use_container_width=True)


def _render_concept_availability(conn, run_query, table_exists) -> None:
    """Report GLP-1 drug descriptions and T2DM codes found in the data."""
    st.subheader("Concept availability")
    st.caption(
        "Shows medication descriptions and condition codes actually present in the "
        "loaded Synthea data. A text match is not a validated clinical phenotype."
    )

    if not table_exists(conn, "standardized", "medications"):
        st.info("Standardized medications table not found.")
        return

    glp1_terms = ["semaglutide", "liraglutide", "dulaglutide", "exenatide", "tirzepatide"]
    like_clauses = " OR ".join(f"LOWER(medication_description) LIKE '%{t}%'" for t in glp1_terms)
    glp1_df = run_query(
        conn,
        f"SELECT medication_description, medication_code, count(DISTINCT patient_id) AS n_patients "
        f"FROM standardized.medications WHERE {like_clauses} "
        f"GROUP BY medication_description, medication_code ORDER BY n_patients DESC",
    )

    st.markdown("**GLP-1 medications found in data**")
    if glp1_df.empty:
        st.warning(
            "No GLP-1 medication records found. "
            "Check that Synthea generated diabetes management scenarios."
        )
    else:
        st.dataframe(glp1_df, use_container_width=True)

    if table_exists(conn, "standardized", "conditions"):
        t2dm_terms = ["type 2 diabetes", "diabetes mellitus type 2", "noninsulin-dependent"]
        t2dm_clauses = " OR ".join(f"LOWER(condition_description) LIKE '%{t}%'" for t in t2dm_terms)
        t2dm_df = run_query(
            conn,
            f"SELECT condition_description, condition_code, count(DISTINCT patient_id) AS n_patients "
            f"FROM standardized.conditions WHERE {t2dm_clauses} "
            f"GROUP BY condition_description, condition_code ORDER BY n_patients DESC",
        )
        st.markdown("**Type 2 diabetes conditions found in data**")
        if t2dm_df.empty:
            st.warning("No type 2 diabetes condition records found.")
        else:
            st.dataframe(t2dm_df, use_container_width=True)
