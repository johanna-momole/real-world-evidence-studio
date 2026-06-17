"""Results page — characteristics table, outcomes, subgroups, regression."""

from __future__ import annotations

import streamlit as st

from evidence_studio.config import AppConfig
from evidence_studio.ui.components import (
    download_csv_button,
    no_cohort_banner,
    show_disclaimer,
)

_SUBGROUP_OPTIONS: dict[str, str] = {
    "Age group": "age_group",
    "Sex": "sex",
    "Race": "race",
    "Ethnicity": "ethnicity",
    "Hypertension": "has_hypertension",
    "Chronic kidney disease": "has_ckd",
    "Cardiovascular disease": "has_cvd",
    "GLP-1 drug initiated": "glp1_drug",
}


def show() -> None:
    """Render the Results page."""
    st.title("Results")
    show_disclaimer()
    st.caption(
        "All figures are derived from synthetic records. "
        "They do not represent real clinical incidence, effectiveness, or risk."
    )

    config = AppConfig()
    if not config.resolved_db_path.exists():
        no_cohort_banner()
        return

    from evidence_studio.database import get_connection, table_exists

    conn = get_connection(config.resolved_db_path)

    if not table_exists(conn, "analytics", "analysis_dataset"):
        no_cohort_banner()
        return

    tabs = st.tabs(
        [
            "Cohort Characteristics",
            "Outcomes",
            "Subgroups",
            "ED Distribution",
            "Missingness",
            "Regression",
        ]
    )

    with tabs[0]:
        _render_characteristics(conn)
    with tabs[1]:
        _render_outcomes(conn)
    with tabs[2]:
        _render_subgroups(conn)
    with tabs[3]:
        _render_ed_distribution(conn)
    with tabs[4]:
        _render_missingness(conn)
    with tabs[5]:
        _render_regression(conn)


def _render_characteristics(conn) -> None:
    """Render Table 1 — cohort characteristics."""
    from evidence_studio.analysis import characteristics_table

    st.subheader("Cohort characteristics (Table 1)")
    st.caption(
        "Continuous variables: Mean (SD). Categorical variables: N (%). "
        "Missing counts refer to the analysis dataset."
    )
    df = characteristics_table(conn)
    if df.empty:
        st.info("No data available. Run `evidence-studio analyze` first.")
        return
    st.dataframe(df, use_container_width=True)
    download_csv_button(df, "characteristics.csv", "Download Table 1")


def _render_outcomes(conn) -> None:
    """Render outcome summary metrics."""
    from evidence_studio.analysis import outcome_summary

    st.subheader("Primary and secondary outcomes")
    st.caption(
        "Primary outcome: any ED encounter during the follow-up window. "
        "All figures from synthetic data only."
    )
    df = outcome_summary(conn)
    if df.empty:
        st.info("No outcome data available.")
        return

    row = df.iloc[0]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Patients enrolled", int(row.get("n_patients", 0)))
    col2.metric(
        "Any ED visit",
        f"{int(row.get('n_any_ed', 0))} ({row.get('pct_any_ed', '—')}%)",
    )
    col3.metric(
        "ED / 100 person-months",
        str(row.get("ed_per_100_person_months", "—")),
    )
    col4.metric(
        "Mean follow-up (days)",
        str(row.get("mean_follow_up_days", "—")),
    )

    st.dataframe(df.T.rename(columns={0: "Value"}), use_container_width=True)
    download_csv_button(df, "outcomes.csv", "Download outcomes table")


def _render_subgroups(conn) -> None:
    """Render subgroup outcome comparisons with a bar chart."""
    import plotly.express as px

    from evidence_studio.analysis import subgroup_summary

    st.subheader("Subgroup comparisons")
    st.caption(
        "Unadjusted ED event rates by subgroup. "
        "Differences reflect simulation patterns and do not represent real clinical associations."
    )

    label = st.selectbox("Stratify by", list(_SUBGROUP_OPTIONS.keys()))
    col = _SUBGROUP_OPTIONS[label]

    df = subgroup_summary(conn, by=col)
    if df.empty:
        st.info("No subgroup data available.")
        return

    fig = px.bar(
        df,
        x="subgroup_value",
        y="pct_ed",
        text="pct_ed",
        labels={
            "subgroup_value": label,
            "pct_ed": "% with any ED visit",
        },
        title=f"ED visit rate by {label} (synthetic data)",
        color="pct_ed",
        color_continuous_scale="Blues",
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(
        coloraxis_showscale=False,
        yaxis_title="% with any ED visit (synthetic)",
        xaxis_title=label,
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(df, use_container_width=True)
    download_csv_button(df, f"subgroup_{col}.csv", f"Download {label} subgroup table")


def _render_ed_distribution(conn) -> None:
    """Render distribution of ED visit counts per patient."""
    import plotly.express as px

    from evidence_studio.database import run_query

    st.subheader("Distribution of ED visit counts")
    st.caption("Number of ED encounters per patient during the follow-up window (synthetic data).")

    df = run_query(
        conn,
        "SELECT fu_ed_count AS ed_visits, count(*) AS n_patients "
        "FROM analytics.analysis_dataset "
        "GROUP BY fu_ed_count ORDER BY fu_ed_count",
    )
    if df.empty:
        st.info("No data available.")
        return

    fig = px.bar(
        df,
        x="ed_visits",
        y="n_patients",
        labels={
            "ed_visits": "ED visits during follow-up",
            "n_patients": "Number of patients",
        },
        title="ED visit count distribution (synthetic data)",
        text="n_patients",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(height=380, xaxis={"dtick": 1})
    st.plotly_chart(fig, use_container_width=True)


def _render_missingness(conn) -> None:
    """Render the missingness summary."""
    import plotly.express as px

    from evidence_studio.analysis import missingness_summary

    st.subheader("Covariate missingness")
    st.caption(
        "Percent of patients with missing values for each baseline covariate. "
        "The regression uses complete-case analysis and excludes missing rows."
    )
    df = missingness_summary(conn)
    if df.empty:
        st.info("No data available.")
        return

    fig = px.bar(
        df[df["% missing"] > 0],
        x="Variable",
        y="% missing",
        color="Flag",
        color_discrete_map={"HIGH": "#F44336", "": "#2196F3"},
        title="% missing by covariate (analysis dataset)",
        labels={"% missing": "% missing", "Variable": "Covariate"},
        text="% missing",
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(showlegend=False, height=380)
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(df, use_container_width=True)


def _render_regression(conn) -> None:
    """Render logistic regression results with forest-plot style display."""
    import plotly.express as px

    from evidence_studio.statistics import RegressionResult, fit_ed_logistic_regression

    st.subheader("Multivariable logistic regression")
    st.caption(
        "Outcome: any ED encounter during follow-up. "
        "Associations are descriptive and **non-causal**. "
        "Odds ratios derived from synthetic data only."
    )

    result: RegressionResult = fit_ed_logistic_regression(conn)

    for warning in result.warnings:
        st.warning(warning, icon="⚠️")

    if result.model_not_fit:
        st.error("Model was not fitted due to diagnostic failures. See warnings above.")
        return

    st.markdown(
        f"**n = {result.n_observations}** "
        f"| Outcome events: **{result.n_outcomes}** "
        f"| AIC: **{result.aic:.1f}**"
    )

    if result.table.empty:
        st.info("No regression results available.")
        return

    fig = px.scatter(
        result.table,
        x="OR",
        y="Variable",
        error_x_minus=result.table["OR"] - result.table["95% CI lower"],
        error_x=result.table["95% CI upper"] - result.table["OR"],
        title="Odds ratios with 95% CIs (synthetic data — non-causal)",
        labels={"OR": "Odds Ratio", "Variable": ""},
    )
    fig.add_vline(x=1.0, line_dash="dash", line_color="grey", annotation_text="OR = 1")
    fig.update_layout(height=max(350, len(result.table) * 30 + 100))
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(result.table, use_container_width=True)
    download_csv_button(result.table, "regression.csv", "Download regression table")
