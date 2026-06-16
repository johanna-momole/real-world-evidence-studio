"""Study Designer page — concept-set inspection, inclusion/exclusion, follow-up window."""

from __future__ import annotations

import streamlit as st

from evidence_studio.config import AppConfig, StudyConfig
from evidence_studio.ui.components import no_data_banner, show_disclaimer


def show() -> None:
    """Render the Study Designer page."""
    st.title("Study Designer")
    show_disclaimer()
    st.caption(
        "Configure study parameters, review concept-set matches in your Synthea data, "
        "then build the cohort. The configuration is preserved in session state and "
        "recorded with every study run."
    )

    config = AppConfig()

    _render_config_form(config)

    if not config.has_synthea_files:
        no_data_banner("Ingest data first to inspect concept-set matches.")
        return

    _render_concept_matches(config)
    _render_build_button(config)


def _render_config_form(config: AppConfig) -> None:
    """Render the study parameter form and save to session state."""
    st.subheader("Study parameters")

    defaults = StudyConfig.from_yaml()

    with st.form("study_config_form"):
        col1, col2 = st.columns(2)

        with col1:
            follow_up = st.selectbox(
                "Follow-up window (days)",
                options=[30, 90, 180, 365],
                index=[30, 90, 180, 365].index(defaults.follow_up_days),
                help="Duration of the outcome ascertainment window after the index date.",
            )
            min_age = st.number_input(
                "Minimum age at index (years)",
                min_value=18,
                max_value=90,
                value=defaults.min_age_at_index,
            )

        with col2:
            st.markdown("**Configurable exclusions**")
            excl_t1 = st.checkbox(
                "Exclude type 1 diabetes",
                value=defaults.exclude_type1_diabetes,
                help="Exclude patients with any T1DM condition record on or before index date.",
            )
            excl_gest = st.checkbox(
                "Exclude gestational diabetes",
                value=defaults.exclude_gestational_diabetes,
            )
            excl_preg = st.checkbox(
                "Exclude pregnancy overlapping index date",
                value=defaults.exclude_pregnancy_at_index,
                help="Uses a ±30-day window around the index date.",
            )
            excl_demo = st.checkbox(
                "Exclude missing demographics",
                value=defaults.exclude_missing_demographics,
                help="Excludes patients missing sex, race, or birth date.",
            )

        submitted = st.form_submit_button("Save parameters", type="primary")

    if submitted:
        st.session_state["study_config"] = StudyConfig(
            follow_up_days=follow_up,
            min_age_at_index=min_age,
            exclude_type1_diabetes=excl_t1,
            exclude_gestational_diabetes=excl_gest,
            exclude_pregnancy_at_index=excl_preg,
            exclude_missing_demographics=excl_demo,
            min_follow_up_days=follow_up,
        )
        st.success(
            f"Parameters saved: {follow_up}-day follow-up, min age {min_age}. "
            "Click **Build Cohort** below to apply them."
        )

    current = st.session_state.get("study_config")
    if current:
        with st.expander("Active configuration"):
            for k, v in current.to_dict().items():
                st.markdown(f"- **{k}**: `{v}`")


def _render_concept_matches(config: AppConfig) -> None:
    """Show which GLP-1 drugs and clinical codes matched in the loaded data."""
    st.subheader("Concept-set matches in loaded data")
    st.caption(
        "Text matching against Synthea description fields. "
        "This is **not** a validated clinical phenotype — review matches carefully."
    )

    if not config.resolved_db_path.exists():
        st.info("Run ingestion to see concept-set matches.")
        return

    from evidence_studio.concepts import ConceptMatcher
    from evidence_studio.database import get_connection

    conn = get_connection(config.resolved_db_path)
    matcher = ConceptMatcher(conn)

    tabs = st.tabs(
        ["GLP-1 Medications", "T2DM Conditions", "Exclusion Conditions", "Comorbidities"]
    )

    with tabs[0]:
        df = matcher.match_glp1_medications()
        if df.empty:
            st.warning(
                "No GLP-1 medication records found. "
                "Ensure Synthea generated diabetes management scenarios "
                "(population size ≥ 1,000 recommended)."
            )
        else:
            st.success(f"Found {len(df)} distinct GLP-1 medication descriptions.")
            st.dataframe(df, use_container_width=True)

    with tabs[1]:
        df = matcher.match_conditions("type2_diabetes")
        if df.empty:
            st.warning("No type 2 diabetes condition records found.")
        else:
            st.success(f"Found {len(df)} distinct T2DM condition records.")
            st.dataframe(df, use_container_width=True)

    with tabs[2]:
        for key, label in [
            ("type1_diabetes", "Type 1 diabetes"),
            ("gestational_diabetes", "Gestational diabetes"),
            ("pregnancy", "Pregnancy"),
        ]:
            df = matcher.match_conditions(key)
            st.markdown(f"**{label}**")
            if df.empty:
                st.caption(f"No {label} records found.")
            else:
                st.dataframe(df, use_container_width=True)

    with tabs[3]:
        for key, label in [
            ("hypertension", "Hypertension"),
            ("chronic_kidney_disease", "Chronic kidney disease"),
            ("cardiovascular_disease", "Cardiovascular disease"),
        ]:
            df = matcher.match_conditions(key)
            st.markdown(f"**{label}**")
            if df.empty:
                st.caption(f"No {label} records found.")
            else:
                st.dataframe(df, use_container_width=True)


def _render_build_button(config: AppConfig) -> None:
    """Render the cohort build button with a confirmation step."""
    st.subheader("Build cohort")
    st.caption(
        "Applies the saved parameters, records the attrition cascade in the audit schema, "
        "and assigns a deterministic run ID. Then run `evidence-studio analyze` (CLI) "
        "or navigate to Results to trigger analysis."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        build = st.button("Build Cohort", type="primary")
    with col2:
        st.caption(
            "This overwrites the existing `analytics.cohort` table "
            "but preserves the full audit history."
        )

    if build:
        study_cfg = st.session_state.get("study_config") or StudyConfig.from_yaml()
        with st.spinner("Building cohort — this may take a few seconds…"):
            try:
                from evidence_studio.audit import ensure_audit_schema
                from evidence_studio.cohort import CohortBuilder
                from evidence_studio.database import get_connection

                conn = get_connection(config.resolved_db_path)
                ensure_audit_schema(conn)
                builder = CohortBuilder(conn, study_cfg)
                run_id = builder.build()
                st.session_state["cohort_run_id"] = run_id
                st.success(f"Cohort built successfully. Run ID: `{run_id}`")
                st.info("Navigate to **Cohort Attrition** to see the exclusion cascade.")
            except Exception as exc:
                st.error(f"Cohort build failed: {exc}")
