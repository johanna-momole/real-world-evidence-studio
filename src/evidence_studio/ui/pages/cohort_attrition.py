"""Cohort Attrition page — waterfall chart, attrition table, run metadata."""

from __future__ import annotations

import streamlit as st

from evidence_studio.config import AppConfig
from evidence_studio.ui.components import no_cohort_banner, show_disclaimer


def show() -> None:
    """Render the Cohort Attrition page."""
    st.title("Cohort Attrition")
    show_disclaimer()

    config = AppConfig()
    if not config.resolved_db_path.exists():
        no_cohort_banner()
        return

    from evidence_studio.database import get_connection, table_exists

    conn = get_connection(config.resolved_db_path)

    if not table_exists(conn, "audit", "cohort_attrition"):
        no_cohort_banner()
        return

    run_id = st.session_state.get("cohort_run_id")
    _render_run_selector(conn, run_id)


def _render_run_selector(conn, selected_run_id) -> None:
    """Render run selector and attrition for the selected run."""
    from evidence_studio.database import run_query

    runs = run_query(
        conn,
        "SELECT run_id, run_timestamp, n_enrolled "
        "FROM audit.study_runs ORDER BY run_timestamp DESC LIMIT 20",
    )
    if runs.empty:
        st.info("No cohort runs found. Use the Study Designer to build a cohort.")
        return

    options = runs["run_id"].tolist()
    default = options.index(selected_run_id) if selected_run_id in options else 0
    chosen = st.selectbox(
        "Study run",
        options=options,
        index=default,
        format_func=lambda r: (
            f"{r[:16]}… ({runs.loc[runs['run_id'] == r, 'run_timestamp'].iloc[0]})"
        ),
    )

    _render_config_summary(conn, chosen, run_query)

    attrition = run_query(
        conn,
        "SELECT step_number, rule_label, patients_remaining, patients_removed, "
        "       pct_retained FROM audit.cohort_attrition "
        "WHERE run_id = ? ORDER BY step_number",
        {"run_id": chosen},
    )

    if attrition.empty:
        st.warning("No attrition data for this run.")
        return

    final_n = int(attrition["patients_remaining"].iloc[-1])
    st.metric("Final cohort size", final_n)

    st.subheader("Attrition table")
    st.dataframe(attrition, use_container_width=True)

    st.subheader("Attrition waterfall")
    _render_waterfall(attrition)


def _render_config_summary(conn, run_id: str, run_query) -> None:
    """Show the study configuration used for this run."""
    import json

    from evidence_studio.database import table_exists

    if not table_exists(conn, "audit", "study_runs"):
        return

    df = run_query(
        conn,
        "SELECT config_json FROM audit.study_runs WHERE run_id = ? LIMIT 1",
        {"run_id": run_id},
    )
    if df.empty or df["config_json"].iloc[0] is None:
        return

    with st.expander("Study configuration for this run"):
        try:
            cfg = json.loads(df["config_json"].iloc[0])
            for k, v in cfg.items():
                st.markdown(f"- **{k}**: `{v}`")
        except Exception:
            st.code(df["config_json"].iloc[0])


def _render_waterfall(attrition) -> None:
    """Render a Plotly waterfall chart from the attrition DataFrame."""
    import plotly.graph_objects as go

    labels = attrition["rule_label"].tolist()
    remaining = attrition["patients_remaining"].tolist()

    measures = ["absolute"] + ["relative"] * (len(remaining) - 1)
    y_values = [remaining[0]] + [remaining[i] - remaining[i - 1] for i in range(1, len(remaining))]
    text_labels = [f"n = {r}" for r in remaining]

    fig = go.Figure(
        go.Waterfall(
            name="Patients",
            orientation="v",
            measure=measures,
            x=labels,
            y=y_values,
            text=text_labels,
            textposition="outside",
            connector={"line": {"color": "rgb(63,63,63)"}},
            increasing={"marker": {"color": "#2196F3"}},
            decreasing={"marker": {"color": "#F44336"}},
            totals={"marker": {"color": "#4CAF50"}},
            hovertemplate="<b>%{x}</b><br>Patients remaining: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Patient attrition cascade (synthetic data)",
        xaxis_title="Attrition step",
        yaxis_title="Patients remaining",
        showlegend=False,
        height=480,
        margin={"t": 60, "b": 120},
    )
    fig.update_xaxes(tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)
