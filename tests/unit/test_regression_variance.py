"""Tests for zero-variance predictor handling in fit_ed_logistic_regression.

Validates the fix that drops constant numeric predictors before model fitting
to prevent a singular design matrix (numpy.linalg.LinAlgError).

Scenarios covered:
1.  Single constant numeric predictor → dropped with warning, model fits
2.  Multiple constant predictors → all dropped individually, model fits
3.  Categorical predictor with one observed level → excluded from formula, model fits
4.  All candidate predictors constant → model_not_fit=True, "No valid predictors" warning
5.  Normal dataset with full variation → no dropped-predictor warnings, model fits
6.  Warning message must name the dropped variable
7.  analytics.analysis_dataset row count unchanged after the call
8.  Result is always a RegressionResult, never raises
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ── Data builder ─────────────────────────────────────────────────────────────


def _build_df(
    n: int = 120,
    n_events: int = 36,
    seed: int = 42,
    **overrides,
) -> pd.DataFrame:
    """Return a minimal analytics.analysis_dataset DataFrame.

    All columns are present with variation by default.  Pass keyword
    arguments to pin individual columns to a single constant value, e.g.
    ``bl_inpatient_count=0`` or ``sex="m"``.
    """
    rng = np.random.default_rng(seed)

    data: dict = {
        "patient_id": [f"PT{i:04d}" for i in range(n)],
        "index_date": ["2015-01-01"] * n,
        "glp1_drug": ["semaglutide 1 MG/ML Injectable Solution"] * n,
        "sex": rng.choice(["m", "f"], size=n).tolist(),
        "race": rng.choice(["white", "black", "asian", "other"], size=n).tolist(),
        "ethnicity": rng.choice(["nonhispanic", "hispanic"], size=n).tolist(),
        "age_at_index": rng.integers(35, 76, size=n).tolist(),
        "age_group": ["35-49"] * n,
        "bl_ed_count": rng.integers(0, 5, size=n).tolist(),
        "bl_inpatient_count": rng.integers(0, 4, size=n).tolist(),
        "bl_outpatient_count": rng.integers(1, 10, size=n).tolist(),
        "n_conditions": rng.integers(1, 9, size=n).tolist(),
        "n_medications": rng.integers(1, 7, size=n).tolist(),
        "has_hypertension": rng.integers(0, 2, size=n).tolist(),
        "has_ckd": rng.integers(0, 2, size=n).tolist(),
        "has_cvd": rng.integers(0, 2, size=n).tolist(),
        "hba1c_pct": rng.uniform(6.0, 11.0, size=n).tolist(),
        "bmi_value": rng.uniform(24.0, 42.0, size=n).tolist(),
        "follow_up_end": ["2015-07-01"] * n,
        "follow_up_days_observed": [180] * n,
        "follow_up_months": [5.91] * n,
        "fu_ed_count": [0] * n,
        "any_ed_visit": [0] * n,
        "days_to_first_ed": [None] * n,
        "fu_ip_count": [0] * n,
        "any_ip_visit": [0] * n,
    }

    # Assign outcome events deterministically
    event_idx = rng.choice(n, size=n_events, replace=False).tolist()
    for i in event_idx:
        data["any_ed_visit"][i] = 1
        data["fu_ed_count"][i] = 1
        data["days_to_first_ed"][i] = 30

    # Apply caller-supplied overrides (scalar → repeat for all rows; list → use as-is)
    for col, val in overrides.items():
        data[col] = [val] * n if not isinstance(val, list) else val

    return pd.DataFrame(data)


def _make_conn(df: pd.DataFrame, tmp_path: Path):
    """Return a DuckDB connection with analytics.analysis_dataset loaded from df."""
    import duckdb

    conn = duckdb.connect(str(tmp_path / "regtest.duckdb"))
    conn.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    conn.register("_src", df)
    conn.execute("CREATE TABLE analytics.analysis_dataset AS SELECT * FROM _src")
    conn.unregister("_src")
    return conn


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_single_constant_predictor_dropped_model_fits(tmp_path: Path) -> None:
    """A single zero-variance numeric predictor is dropped; the model still fits."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    df = _build_df(bl_inpatient_count=0)  # constant — should be dropped
    conn = _make_conn(df, tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    assert not result.model_not_fit, f"Model should fit. Warnings: {result.warnings}"
    assert any("bl_inpatient_count" in w and "zero variance" in w for w in result.warnings), (
        f"Expected warning naming 'bl_inpatient_count'. Got: {result.warnings}"
    )


def test_multiple_constant_predictors_each_warned(tmp_path: Path) -> None:
    """Each zero-variance predictor emits its own warning; the model still fits."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    df = _build_df(bl_inpatient_count=0, has_cvd=0)
    conn = _make_conn(df, tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    variance_warnings = [w for w in result.warnings if "zero variance" in w]
    assert len(variance_warnings) == 2, (
        f"Expected exactly 2 zero-variance warnings, got {len(variance_warnings)}: {variance_warnings}"
    )
    assert any("bl_inpatient_count" in w for w in variance_warnings)
    assert any("has_cvd" in w for w in variance_warnings)
    assert not result.model_not_fit, f"Model should still fit. Warnings: {result.warnings}"


def test_categorical_single_level_excluded_not_warned_as_numeric_variance(tmp_path: Path) -> None:
    """Categorical with one level emits a named warning but NOT the numeric zero-variance message."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    df = _build_df(sex="m")  # only "m" — C(sex) must not appear in formula
    conn = _make_conn(df, tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    assert not result.model_not_fit, f"Model should fit without C(sex). Warnings: {result.warnings}"
    # sex must not appear in the NUMERIC zero-variance warning ("has zero variance and was dropped")
    assert not any(
        "sex" in w and "has zero variance and was dropped" in w for w in result.warnings
    ), "sex must not appear in the numeric zero-variance warning — it is handled as a categorical"


def test_all_predictors_constant_returns_unfitted(tmp_path: Path) -> None:
    """When every candidate predictor is constant the model cannot be fitted."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    df = _build_df(
        # Pin every numeric predictor to a single value
        age_at_index=55,
        has_hypertension=1,
        has_ckd=0,
        has_cvd=0,
        bl_ed_count=0,
        bl_inpatient_count=0,
        n_conditions=3,
        n_medications=2,
        hba1c_pct=7.5,
        bmi_value=30.0,
        # Pin every categorical predictor to a single level
        sex="m",
        race="white",
        ethnicity="nonhispanic",
    )
    conn = _make_conn(df, tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    assert result.model_not_fit is True
    assert any("No valid predictors" in w for w in result.warnings), (
        f"Expected 'No valid predictors' warning. Got: {result.warnings}"
    )


def test_normal_dataset_no_predictors_dropped(tmp_path: Path) -> None:
    """With genuine variation in all predictors, no zero-variance warnings are emitted."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    df = _build_df()  # all columns varied by default
    conn = _make_conn(df, tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    dropped = [w for w in result.warnings if "zero variance" in w]
    assert dropped == [], f"No predictors should be dropped on a normal dataset. Got: {dropped}"


def test_warning_message_names_the_dropped_column(tmp_path: Path) -> None:
    """The zero-variance warning must include the exact column name."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    df = _build_df(hba1c_pct=7.2)  # constant HbA1c
    conn = _make_conn(df, tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    matched = [w for w in result.warnings if "hba1c_pct" in w and "zero variance" in w]
    assert matched, f"Warning must name 'hba1c_pct'. Got: {result.warnings}"


def test_analysis_dataset_row_count_unchanged(tmp_path: Path) -> None:
    """fit_ed_logistic_regression must not mutate analytics.analysis_dataset."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    df = _build_df(bl_inpatient_count=0)  # exercises the drop path
    conn = _make_conn(df, tmp_path)

    before = conn.execute("SELECT count(*) FROM analytics.analysis_dataset").fetchone()[0]

    fit_ed_logistic_regression(conn)

    after = conn.execute("SELECT count(*) FROM analytics.analysis_dataset").fetchone()[0]
    conn.close()

    assert before == after, f"analytics.analysis_dataset row count changed: {before} -> {after}"


def test_result_always_a_regression_result_never_raises(tmp_path: Path) -> None:
    """fit_ed_logistic_regression always returns RegressionResult, never raises."""
    from evidence_studio.statistics import RegressionResult, fit_ed_logistic_regression

    # Worst case: every numeric and categorical predictor is constant
    df = _build_df(
        age_at_index=55,
        has_hypertension=0,
        has_ckd=0,
        has_cvd=0,
        bl_ed_count=0,
        bl_inpatient_count=0,
        n_conditions=3,
        n_medications=2,
        hba1c_pct=7.5,
        bmi_value=30.0,
        sex="f",
        race="white",
        ethnicity="nonhispanic",
    )
    conn = _make_conn(df, tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    assert isinstance(result, RegressionResult)
    assert isinstance(result.warnings, list)
    assert isinstance(result.model_not_fit, bool)
