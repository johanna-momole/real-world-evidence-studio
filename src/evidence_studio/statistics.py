"""Logistic regression and statistical modelling for RWE Studio."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_MIN_N = 50
_MIN_EVENTS = 10
_MIN_EVENT_RATE = 0.05


@dataclass
class RegressionResult:
    """Output of the logistic regression fit."""

    model_not_fit: bool = False
    warnings: list[str] = field(default_factory=list)
    n_observations: int = 0
    n_outcomes: int = 0
    aic: float = float("nan")
    table: pd.DataFrame = field(default_factory=pd.DataFrame)


def fit_ed_logistic_regression(conn: duckdb.DuckDBPyConnection) -> RegressionResult:
    """Fit multivariable logistic regression for any follow-up ED visit.

    Returns a RegressionResult with warnings if diagnostics fail.
    """
    from evidence_studio.database import run_query, table_exists

    result = RegressionResult()

    if not table_exists(conn, "analytics", "analysis_dataset"):
        result.model_not_fit = True
        result.warnings.append("analysis_dataset not found. Run 'analyze' first.")
        return result

    df = run_query(
        conn,
        "SELECT * FROM analytics.analysis_dataset",
    )

    if df.empty:
        result.model_not_fit = True
        result.warnings.append("Analysis dataset is empty.")
        return result

    # ── Pre-flight diagnostics ────────────────────────────────────────────────
    n = len(df)
    n_events = int(df["any_ed_visit"].sum())
    event_rate = n_events / n if n > 0 else 0

    result.n_observations = n
    result.n_outcomes = n_events

    if n < _MIN_N:
        result.warnings.append(
            f"Sample too small for reliable regression (n={n}; minimum recommended: {_MIN_N}). "
            "Results are illustrative only."
        )

    if n_events < _MIN_EVENTS:
        result.warnings.append(
            f"Fewer than {_MIN_EVENTS} outcome events (observed: {n_events}). "
            "Odds ratios are highly unstable."
        )

    if event_rate < _MIN_EVENT_RATE:
        result.warnings.append(
            f"Outcome event rate is {event_rate:.1%} — estimates may be unreliable."
        )

    if n_events == 0:
        result.model_not_fit = True
        result.warnings.append("No outcome events observed. Model cannot be fitted.")
        return result

    if n_events == n:
        result.model_not_fit = True
        result.warnings.append(
            "All patients experienced the outcome (perfect prediction). Model cannot be fitted."
        )
        return result

    # ── Prepare model dataset ─────────────────────────────────────────────────
    predictors = [
        "age_at_index",
        "sex",
        "race",
        "ethnicity",
        "has_hypertension",
        "has_ckd",
        "has_cvd",
        "bl_ed_count",
        "bl_inpatient_count",
        "n_conditions",
        "n_medications",
        "hba1c_pct",
        "bmi_value",
    ]

    model_df = df[["any_ed_visit"] + predictors].copy()
    n_before = len(model_df)
    model_df = model_df.dropna()
    n_after = len(model_df)

    if n_before > n_after:
        result.warnings.append(
            f"Complete-case analysis removed {n_before - n_after} patients with missing covariates "
            f"(n remaining: {n_after})."
        )

    if n_after < _MIN_N:
        result.warnings.append(
            f"After removing missing values, n={n_after} — below recommended minimum."
        )

    n_events_cc = int(model_df["any_ed_visit"].sum())
    if n_events_cc < _MIN_EVENTS:
        result.warnings.append(
            f"After complete-case exclusions, only {n_events_cc} outcome events remain."
        )

    if n_events_cc == 0 or n_events_cc == len(model_df):
        result.model_not_fit = True
        result.warnings.append(
            "No outcome variation in the complete-case sample. Model cannot be fitted."
        )
        return result

    # ── Encode categoricals and drop sparse categories ────────────────────────
    cat_cols = ["sex", "race", "ethnicity"]
    for col in cat_cols:
        counts = model_df[col].value_counts()
        sparse = counts[counts < 5].index.tolist()
        if sparse:
            result.warnings.append(
                f"Dropping sparse categories in '{col}': {sparse} (n < 5). "
                "These levels are excluded from the model."
            )
            model_df = model_df[~model_df[col].isin(sparse)]

    if len(model_df) < _MIN_N or model_df["any_ed_visit"].nunique() < 2:
        result.model_not_fit = True
        result.warnings.append("Insufficient data after sparse category removal.")
        return result

    try:
        import statsmodels.formula.api as smf

        formula_parts = [
            "age_at_index",
            "has_hypertension",
            "has_ckd",
            "has_cvd",
            "bl_ed_count",
            "bl_inpatient_count",
            "n_conditions",
            "n_medications",
            "hba1c_pct",
            "bmi_value",
        ]
        if model_df["sex"].nunique() > 1:
            formula_parts.append("C(sex)")
        if model_df["race"].nunique() > 1:
            formula_parts.append("C(race)")
        if model_df["ethnicity"].nunique() > 1:
            formula_parts.append("C(ethnicity)")

        formula = "any_ed_visit ~ " + " + ".join(formula_parts)

        model = smf.logit(formula, data=model_df)
        fit = model.fit(disp=False, maxiter=100)

        if not fit.converged:
            result.warnings.append(
                "Model did not converge. Estimates are unreliable. "
                "Consider reducing the number of predictors."
            )

        result.aic = float(fit.aic)
        result.n_observations = len(model_df)
        result.n_outcomes = int(model_df["any_ed_visit"].sum())
        result.table = _format_results(fit)

    except Exception as exc:
        result.model_not_fit = True
        result.warnings.append(f"Model fitting failed: {exc}")
        logger.exception("Logistic regression failed")

    return result


def _format_results(fit) -> pd.DataFrame:
    """Format statsmodels LogitResults into an OR / CI table."""

    params = fit.params
    conf = fit.conf_int()
    pvalues = fit.pvalues

    rows = []
    for name in params.index:
        if name == "Intercept":
            continue
        beta = params[name]
        lo = conf.loc[name, 0]
        hi = conf.loc[name, 1]
        ci_width = hi - lo
        unstable = ci_width > 10

        rows.append(
            {
                "Variable": name,
                "OR": round(float(_safe_exp(beta)), 3),
                "95% CI lower": round(float(_safe_exp(lo)), 3),
                "95% CI upper": round(float(_safe_exp(hi)), 3),
                "p-value": round(float(pvalues[name]), 4),
                "Unstable CI": "⚠️" if unstable else "",
            }
        )

    return pd.DataFrame(rows)


def _safe_exp(x: float) -> float:
    """Exponentiate, clamping to avoid overflow."""
    import math

    try:
        return math.exp(min(x, 20.0))
    except (OverflowError, ValueError):
        return float("nan")
