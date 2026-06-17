"""Evidence-brief rendering via Jinja2 templates."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

from evidence_studio.audit import (
    DATA_SOURCE_CUSTOM_DEMO,
    DATA_SOURCE_OFFICIAL_SYNTHEA,
    DATA_SOURCE_UNKNOWN,
)
from evidence_studio.database import run_query, table_exists

logger = logging.getLogger(__name__)


def _data_source_label(data_source: str) -> str:
    if data_source == DATA_SOURCE_OFFICIAL_SYNTHEA:
        return "Official Synthea synthetic EHR data"
    if data_source == DATA_SOURCE_CUSTOM_DEMO:
        return "Custom synthetic demo data (locally generated)"
    return "Synthetic data (source unverified)"


_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

_SUBGROUP_COLS = ["age_group", "sex", "has_hypertension", "has_ckd", "glp1_drug"]


def render_brief(
    conn: duckdb.DuckDBPyConnection,
    run_id: str = "latest",
    output_format: str = "markdown",
) -> str:
    """Render an evidence brief from the current analysis state.

    Returns Markdown or HTML text. Never raises — returns an error notice
    if data is unavailable.
    """
    context = _build_context(conn, run_id)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )

    template_name = "evidence_brief.md.j2"
    try:
        template = env.get_template(template_name)
        text = template.render(**context)
    except Exception as exc:
        logger.error("Template rendering failed: %s", exc)
        text = _fallback_brief(context, str(exc))

    if output_format == "html":
        return md.markdown(text, extensions=["tables", "fenced_code"])
    return text


def _build_context(conn: duckdb.DuckDBPyConnection, run_id: str) -> dict:
    """Collect all data needed by the brief template."""
    import evidence_studio
    from evidence_studio.analysis import (
        characteristics_table,
        missingness_summary,
        outcome_summary,
        subgroup_summary,
    )
    from evidence_studio.statistics import fit_ed_logistic_regression

    ctx: dict = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "app_version": evidence_studio.__version__,
        "data_source": DATA_SOURCE_UNKNOWN,
        "data_source_label": _data_source_label(DATA_SOURCE_UNKNOWN),
        "disclaimer": "",  # set after data_source is resolved
        "n_enrolled": 0,
        "n_outcomes": 0,
        "outcome_rate": "0.0",
        "characteristics": [],
        "outcomes": [],
        "subgroups": {},
        "missingness": [],
        "regression": None,
        "warnings": [],
        "config": {},
        "manifest": [],
        "attrition": [],
    }

    _load_run_config(conn, run_id, ctx)
    _load_manifest(conn, ctx)

    # Build disclaimer from resolved data source
    ctx["disclaimer"] = (
        f"All results are derived from {ctx['data_source_label'].lower()} records. "
        "They do not represent real patients, clinical outcomes, treatment "
        "effectiveness, drug safety, or incidence rates. This document must not "
        "be used for clinical decisions, regulatory submissions, or public health reporting."
    )

    if not table_exists(conn, "analytics", "analysis_dataset"):
        ctx["warnings"].append(
            "Analysis dataset not found. Run `evidence-studio analyze` before generating a brief."
        )
        return ctx

    n_df = run_query(
        conn,
        "SELECT count(*) AS n, sum(any_ed_visit) AS ev FROM analytics.analysis_dataset",
    )
    n_enrolled = int(n_df["n"].iloc[0])
    n_outcomes = int(n_df["ev"].iloc[0] or 0)
    ctx["n_enrolled"] = n_enrolled
    ctx["n_outcomes"] = n_outcomes
    ctx["outcome_rate"] = f"{n_outcomes / n_enrolled * 100:.1f}" if n_enrolled else "0.0"

    char_df = characteristics_table(conn)
    if not char_df.empty:
        ctx["characteristics"] = char_df.to_dict(orient="records")

    out_df = outcome_summary(conn)
    if not out_df.empty:
        ctx["outcomes"] = out_df.to_dict(orient="records")

    for col in _SUBGROUP_COLS:
        try:
            sg_df = subgroup_summary(conn, by=col)
            if not sg_df.empty:
                ctx["subgroups"][col] = sg_df.to_dict(orient="records")
        except Exception:
            pass

    miss_df = missingness_summary(conn)
    if not miss_df.empty:
        ctx["missingness"] = miss_df.to_dict(orient="records")

    regression = fit_ed_logistic_regression(conn)
    ctx["warnings"].extend(regression.warnings)
    if not regression.model_not_fit and not regression.table.empty:
        ctx["regression"] = {
            "n": regression.n_observations,
            "events": regression.n_outcomes,
            "aic": regression.aic,
            "table": regression.table.to_dict(orient="records"),
        }

    _load_attrition(conn, run_id, ctx)

    return ctx


def _load_run_config(conn: duckdb.DuckDBPyConnection, run_id: str, ctx: dict) -> None:
    """Load study configuration from the audit schema."""
    import json

    if not table_exists(conn, "audit", "study_runs"):
        return
    if run_id == "latest":
        df = run_query(conn, "SELECT * FROM audit.study_runs ORDER BY run_timestamp DESC LIMIT 1")
    else:
        df = run_query(
            conn,
            "SELECT * FROM audit.study_runs WHERE run_id = ? LIMIT 1",
            {"run_id": run_id},
        )
    if df.empty:
        return
    row = df.iloc[0]
    ctx["run_id"] = str(row["run_id"])
    if row.get("config_json"):
        try:
            ctx["config"] = json.loads(row["config_json"])
        except Exception:
            ctx["config"] = {}
    if row.get("n_enrolled") is not None:
        ctx["n_enrolled"] = int(row["n_enrolled"])
    if row.get("n_with_outcome") is not None:
        ctx["n_outcomes"] = int(row["n_with_outcome"])
    ds = str(row.get("data_source") or DATA_SOURCE_UNKNOWN)
    ctx["data_source"] = ds
    ctx["data_source_label"] = _data_source_label(ds)


def _load_manifest(conn: duckdb.DuckDBPyConnection, ctx: dict) -> None:
    """Load source-file manifest."""
    if not table_exists(conn, "audit", "data_manifest"):
        return
    df = run_query(
        conn,
        "SELECT file_name, row_count, sha256_hash, data_source FROM audit.data_manifest "
        "ORDER BY load_timestamp DESC",
    )
    if not df.empty:
        ctx["manifest"] = df.to_dict(orient="records")


def _load_attrition(conn: duckdb.DuckDBPyConnection, run_id: str, ctx: dict) -> None:
    """Load cohort attrition steps."""
    if not table_exists(conn, "audit", "cohort_attrition"):
        return
    actual_run_id = ctx.get("run_id", run_id)
    df = run_query(
        conn,
        "SELECT step_number, rule_label, patients_remaining, patients_removed "
        "FROM audit.cohort_attrition WHERE run_id = ? ORDER BY step_number",
        {"run_id": actual_run_id},
    )
    if not df.empty:
        ctx["attrition"] = df.to_dict(orient="records")


def _fallback_brief(context: dict, error: str) -> str:
    """Return a minimal plain-text brief when the template is unavailable."""
    return (
        f"# Evidence Brief — {context.get('run_id', 'unknown')}\n\n"
        f"> {context.get('disclaimer', '')}\n\n"
        f"**Generated:** {context.get('generated_at', '')}\n\n"
        f"**Enrolled:** {context.get('n_enrolled', 0)}  |  "
        f"**ED outcomes:** {context.get('n_outcomes', 0)}\n\n"
        f"*Template rendering error: {error}. "
        "Ensure templates/evidence_brief.md.j2 is present.*\n"
    )
