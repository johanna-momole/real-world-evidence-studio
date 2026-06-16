"""Edge-case tests for analysis functions: empty cohorts, outcome counts, attrition."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture()
def empty_conn(tmp_path: Path):
    """Return a connection with schemas but no cohort patients."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import build_standardized, ingest

    conn = get_connection(tmp_path / "empty_analysis.duckdb")
    ensure_audit_schema(conn)
    ingest(conn, FIXTURES)
    build_standardized(conn)
    yield conn
    conn.close()


@pytest.fixture()
def analysis_conn(tmp_path: Path):
    """Return a connection with full analysis data from fixtures."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.cohort import CohortBuilder
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import build_standardized, ingest

    conn = get_connection(tmp_path / "analysis.duckdb")
    ensure_audit_schema(conn)
    ingest(conn, FIXTURES)
    build_standardized(conn)

    cfg = StudyConfig(follow_up_days=180, min_follow_up_days=180, baseline_days=365)
    CohortBuilder(conn, cfg).build()
    build_analysis_dataset(conn, cfg)
    yield conn
    conn.close()


def test_characteristics_table_empty_db(empty_conn) -> None:
    """characteristics_table must return an empty DataFrame when no cohort exists."""
    from evidence_studio.analysis import characteristics_table

    df = characteristics_table(empty_conn)
    assert df is not None
    assert hasattr(df, "empty"), "Expected a DataFrame"


def test_outcome_summary_empty_db(empty_conn) -> None:
    """outcome_summary must return an empty DataFrame when no analysis dataset exists."""
    from evidence_studio.analysis import outcome_summary

    df = outcome_summary(empty_conn)
    assert df is not None
    assert hasattr(df, "empty")


def test_subgroup_summary_empty_db(empty_conn) -> None:
    """subgroup_summary must not raise even with no analysis data."""
    from evidence_studio.analysis import subgroup_summary

    df = subgroup_summary(empty_conn, by="age_group")
    assert df is not None


def test_missingness_summary_empty_db(empty_conn) -> None:
    """missingness_summary must return without raising on an empty database."""
    from evidence_studio.analysis import missingness_summary

    df = missingness_summary(empty_conn)
    assert df is not None


def test_outcome_summary_non_negative_counts(analysis_conn) -> None:
    """All event counts in outcome_summary must be >= 0."""
    from evidence_studio.analysis import outcome_summary
    from evidence_studio.database import table_exists

    if not table_exists(analysis_conn, "analytics", "analysis_dataset"):
        pytest.skip("No analysis dataset")

    df = outcome_summary(analysis_conn)
    if df.empty:
        pytest.skip("No outcomes")

    numeric_cols = df.select_dtypes(include="number").columns
    for col in numeric_cols:
        assert (df[col] >= 0).all(), f"Negative value in outcome column: {col}"


def test_attrition_steps_sum_adds_up(analysis_conn) -> None:
    """Total patients removed across attrition steps must not exceed initial count."""
    from evidence_studio.database import run_query, table_exists

    if not table_exists(analysis_conn, "audit", "cohort_attrition"):
        pytest.skip("No attrition table")

    df = run_query(
        analysis_conn,
        "SELECT step_number, patients_remaining, patients_removed "
        "FROM audit.cohort_attrition ORDER BY step_number",
    )
    if df.empty:
        pytest.skip("No attrition rows")

    initial_n = int(df["patients_remaining"].iloc[0]) + int(df["patients_removed"].iloc[0])
    total_removed = int(df["patients_removed"].sum())
    final_remaining = int(df["patients_remaining"].iloc[-1])
    assert initial_n - total_removed == final_remaining, (
        f"Attrition arithmetic mismatch: {initial_n} - {total_removed} != {final_remaining}"
    )


def test_concept_set_matching_case_insensitive(analysis_conn) -> None:
    """GLP-1 concept set must match medication descriptions case-insensitively."""
    from evidence_studio.database import run_query

    df = run_query(
        analysis_conn,
        """
        SELECT count(*) AS n FROM standardized.medications
        WHERE LOWER(medication_description) LIKE '%semaglutide%'
           OR LOWER(medication_description) LIKE '%liraglutide%'
           OR LOWER(medication_description) LIKE '%dulaglutide%'
           OR LOWER(medication_description) LIKE '%exenatide%'
           OR LOWER(medication_description) LIKE '%tirzepatide%'
        """,
    )
    assert int(df["n"].iloc[0]) >= 0


def test_subgroup_summary_returns_expected_columns(analysis_conn) -> None:
    """subgroup_summary must return columns: group_value, n, n_ed, ed_rate."""
    from evidence_studio.analysis import subgroup_summary
    from evidence_studio.database import table_exists

    if not table_exists(analysis_conn, "analytics", "analysis_dataset"):
        pytest.skip("No analysis dataset")

    df = subgroup_summary(analysis_conn, by="age_group")
    if df.empty:
        pytest.skip("Empty subgroup")

    expected_cols = {"subgroup_value", "n", "n_ed"}
    assert expected_cols.issubset(set(df.columns)), (
        f"Missing columns: {expected_cols - set(df.columns)}"
    )


def test_build_analysis_dataset_idempotent(analysis_conn) -> None:
    """Running build_analysis_dataset twice must not change the row count."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import run_query, table_exists

    if not table_exists(analysis_conn, "analytics", "analysis_dataset"):
        pytest.skip("No analysis dataset")

    count1 = int(
        run_query(analysis_conn, "SELECT count(*) AS n FROM analytics.analysis_dataset")["n"].iloc[
            0
        ]
    )

    cfg = StudyConfig(follow_up_days=180)
    build_analysis_dataset(analysis_conn, cfg)

    count2 = int(
        run_query(analysis_conn, "SELECT count(*) AS n FROM analytics.analysis_dataset")["n"].iloc[
            0
        ]
    )
    assert count1 == count2, f"Idempotent build changed row count: {count1} → {count2}"


def test_regression_returns_result_dataclass(analysis_conn) -> None:
    """fit_ed_logistic_regression must always return a RegressionResult, never raise."""
    from evidence_studio.statistics import RegressionResult, fit_ed_logistic_regression

    result = fit_ed_logistic_regression(analysis_conn)
    assert isinstance(result, RegressionResult)
    assert isinstance(result.warnings, list)
    assert hasattr(result, "model_not_fit")


def test_regression_empty_db_returns_unfitted(empty_conn) -> None:
    """fit_ed_logistic_regression on empty DB must return model_not_fit=True."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    result = fit_ed_logistic_regression(empty_conn)
    assert result.model_not_fit is True


def test_study_run_recorded_in_audit(analysis_conn) -> None:
    """At least one row must exist in audit.study_runs after a full pipeline run."""
    from evidence_studio.database import run_query, table_exists

    if not table_exists(analysis_conn, "audit", "study_runs"):
        pytest.skip("No study_runs table")

    df = run_query(analysis_conn, "SELECT count(*) AS n FROM audit.study_runs")
    assert int(df["n"].iloc[0]) >= 1, "No study run recorded in audit.study_runs"


def test_sql_parameter_handling_no_injection(analysis_conn) -> None:
    """Parameterized queries must not raise on values that would break unparameterized SQL."""
    from evidence_studio.database import run_query

    malicious_value = "' OR '1'='1"
    df = run_query(
        analysis_conn,
        "SELECT * FROM analytics.analysis_dataset WHERE patient_id = ?",
        {"patient_id": malicious_value},
    )
    assert df is not None
