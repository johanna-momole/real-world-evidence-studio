"""Tests for explicit categorical-predictor exclusion warnings.

Validates the fix that emits a named warning when sex/race/ethnicity has fewer
than 2 usable levels in the complete-case sample, rather than silently dropping
the predictor.

Scenarios covered:
1.  Single-level sex  → warning names 'sex' and 'fewer than 2 usable levels'
2.  Single-level race → warning names 'race' and 'fewer than 2 usable levels'
3.  Single-level ethnicity → same pattern
4.  Two categorical exclusions → two separate named warnings, no duplicates
5.  All three excluded (numerics vary) → three warnings, model still fits
6.  Varied sex (>1 level) → no 'fewer than 2 usable levels' warning for sex
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ── Shared helpers ─────────────────────────────────────────────────────────────


def _build_df(
    n: int = 120,
    n_events: int = 36,
    seed: int = 42,
    **overrides,
) -> pd.DataFrame:
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
    event_idx = rng.choice(n, size=n_events, replace=False).tolist()
    for i in event_idx:
        data["any_ed_visit"][i] = 1
        data["fu_ed_count"][i] = 1
        data["days_to_first_ed"][i] = 30
    for col, val in overrides.items():
        data[col] = [val] * n if not isinstance(val, list) else val
    return pd.DataFrame(data)


def _make_conn(df: pd.DataFrame, tmp_path: Path):
    import duckdb

    conn = duckdb.connect(str(tmp_path / "cattest.duckdb"))
    conn.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    conn.register("_src", df)
    conn.execute("CREATE TABLE analytics.analysis_dataset AS SELECT * FROM _src")
    conn.unregister("_src")
    return conn


def _cat_exclusion_warnings(warnings: list[str]) -> list[str]:
    return [w for w in warnings if "fewer than 2 usable levels" in w]


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_single_level_sex_emits_named_warning(tmp_path: Path) -> None:
    """Single-level sex emits a warning that names 'sex' and 'fewer than 2 usable levels'."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    conn = _make_conn(_build_df(sex="m"), tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    matched = [w for w in result.warnings if "'sex'" in w and "fewer than 2 usable levels" in w]
    assert matched, (
        f"Expected a warning naming 'sex' and 'fewer than 2 usable levels'. Got: {result.warnings}"
    )


def test_single_level_race_emits_named_warning(tmp_path: Path) -> None:
    """Single-level race emits a warning that names 'race' and 'fewer than 2 usable levels'."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    conn = _make_conn(_build_df(race="white"), tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    matched = [w for w in result.warnings if "'race'" in w and "fewer than 2 usable levels" in w]
    assert matched, (
        f"Expected a warning naming 'race' and 'fewer than 2 usable levels'. Got: {result.warnings}"
    )


def test_single_level_ethnicity_emits_named_warning(tmp_path: Path) -> None:
    """Single-level ethnicity emits a warning naming 'ethnicity'."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    conn = _make_conn(_build_df(ethnicity="nonhispanic"), tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    matched = [
        w for w in result.warnings if "'ethnicity'" in w and "fewer than 2 usable levels" in w
    ]
    assert matched, (
        f"Expected a warning naming 'ethnicity' and 'fewer than 2 usable levels'. "
        f"Got: {result.warnings}"
    )


def test_two_categorical_exclusions_emit_separate_warnings(tmp_path: Path) -> None:
    """Two single-level categoricals each emit their own named warning (no merging)."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    conn = _make_conn(_build_df(sex="m", race="white"), tmp_path)
    result = fit_ed_logistic_regression(conn)
    conn.close()

    cat_warns = _cat_exclusion_warnings(result.warnings)
    assert len(cat_warns) == 2, (
        f"Expected exactly 2 categorical-exclusion warnings, got {len(cat_warns)}: {cat_warns}"
    )
    assert any("'sex'" in w for w in cat_warns), "Missing warning for 'sex'"
    assert any("'race'" in w for w in cat_warns), "Missing warning for 'race'"


def test_all_three_categoricals_excluded_numeric_model_fits(tmp_path: Path) -> None:
    """All three categoricals excluded by single level; model still fits on numeric predictors."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    conn = _make_conn(
        _build_df(sex="m", race="white", ethnicity="nonhispanic"),
        tmp_path,
    )
    result = fit_ed_logistic_regression(conn)
    conn.close()

    cat_warns = _cat_exclusion_warnings(result.warnings)
    assert len(cat_warns) == 3, (
        f"Expected 3 categorical-exclusion warnings, got {len(cat_warns)}: {cat_warns}"
    )
    assert not result.model_not_fit, (
        f"Model should still fit using numeric predictors. Warnings: {result.warnings}"
    )


def test_varied_sex_no_exclusion_warning(tmp_path: Path) -> None:
    """When sex has 2 levels the exclusion warning must not be emitted for sex."""
    from evidence_studio.statistics import fit_ed_logistic_regression

    conn = _make_conn(_build_df(), tmp_path)  # default: sex varied
    result = fit_ed_logistic_regression(conn)
    conn.close()

    sex_exclusion = [
        w for w in result.warnings if "'sex'" in w and "fewer than 2 usable levels" in w
    ]
    assert sex_exclusion == [], (
        f"sex has >1 level — should not produce an exclusion warning. Got: {sex_exclusion}"
    )
