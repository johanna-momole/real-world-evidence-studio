"""CLI entry point for the Real-World Evidence Studio."""

from __future__ import annotations

from pathlib import Path

import click

from evidence_studio.config import AppConfig, StudyConfig, configure_logging


@click.group()
@click.option("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
def cli(log_level: str) -> None:
    """Real-World Evidence Studio CLI."""
    configure_logging(log_level)


@cli.command()
@click.option(
    "--data-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Directory containing source CSV files (overrides SYNTHEA_DATA_DIR).",
)
@click.option(
    "--db-path",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to DuckDB file (overrides DB_PATH).",
)
@click.option(
    "--data-source",
    "data_source",
    default="unknown_synthetic_source",
    type=click.Choice(
        ["official_synthea", "custom_synthetic_demo", "unknown_synthetic_source"],
        case_sensitive=True,
    ),
    help=(
        "Origin of the CSV files stored in the audit manifest. "
        "Use 'official_synthea' for files from the Synthea Java tool, "
        "'custom_synthetic_demo' for locally-generated synthetic data, "
        "or leave as 'unknown_synthetic_source' (default)."
    ),
)
def ingest(data_dir: Path | None, db_path: Path | None, data_source: str) -> None:
    """Load CSV files into the raw and standardized DuckDB schemas."""
    cfg = AppConfig()
    data_dir = (data_dir or cfg.resolved_synthea_dir).resolve()
    db_path = (db_path or cfg.resolved_db_path).resolve()

    click.echo(f"Data directory : {data_dir}")
    click.echo(f"Database       : {db_path}")
    click.echo(f"Data source    : {data_source}")

    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import build_standardized
    from evidence_studio.ingestion import ingest as _ingest

    conn = get_connection(db_path)
    ensure_audit_schema(conn)

    click.echo("Loading source files into raw schema…")
    row_counts = _ingest(conn, data_dir, data_source=data_source)
    for name, n in row_counts.items():
        click.echo(f"  {name}: {n:,} rows")

    click.echo("Building standardized tables…")
    build_standardized(conn)
    click.echo("Ingestion complete.")


@cli.command("dq-report")
@click.option("--db-path", default=None, type=click.Path(path_type=Path))
def dq_report(db_path: Path | None) -> None:
    """Run data quality checks and print a summary."""
    cfg = AppConfig()
    db_path = (db_path or cfg.resolved_db_path).resolve()

    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}. Run 'ingest' first.")

    from evidence_studio.data_quality import run_dq_checks
    from evidence_studio.database import get_connection

    conn = get_connection(db_path)
    report = run_dq_checks(conn)

    for r in report.results:
        symbol = "✅" if r.status == "PASS" else ("❌" if r.status == "FAIL" else "⚠️")
        click.echo(f"{symbol} {r.rule_name}: {r.message}")

    click.echo(
        f"\n{len(report.results)} checks — {report.n_failed} failed, {report.n_warned} warnings."
    )
    if not report.passed:
        raise SystemExit(1)


@cli.command("build-cohort")
@click.option("--config-file", default=None, type=click.Path(path_type=Path))
@click.option("--db-path", default=None, type=click.Path(path_type=Path))
def build_cohort(config_file: Path | None, db_path: Path | None) -> None:
    """Build the GLP-1 cohort from standardized data."""
    cfg = AppConfig()
    db_path = (db_path or cfg.resolved_db_path).resolve()

    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}. Run 'ingest' first.")

    study_cfg = StudyConfig.from_yaml(config_file)

    from evidence_studio.cohort import CohortBuilder
    from evidence_studio.database import get_connection

    conn = get_connection(db_path)
    builder = CohortBuilder(conn, study_cfg)
    run_id = builder.build()
    click.echo(f"Cohort built. Run ID: {run_id}")


@cli.command()
@click.option("--db-path", default=None, type=click.Path(path_type=Path))
def analyze(db_path: Path | None) -> None:
    """Compute baseline features, outcomes, and run the logistic regression."""
    cfg = AppConfig()
    db_path = (db_path or cfg.resolved_db_path).resolve()

    if not db_path.exists():
        raise click.ClickException(
            f"Database not found: {db_path}. Run 'ingest' and 'build-cohort' first."
        )

    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.database import get_connection
    from evidence_studio.statistics import fit_ed_logistic_regression

    conn = get_connection(db_path)
    build_analysis_dataset(conn)

    result = fit_ed_logistic_regression(conn)
    for w in result.warnings:
        click.echo(f"WARNING: {w}")

    if result.model_not_fit:
        click.echo("Model was not fitted. See warnings above.")
    else:
        click.echo(
            f"\nLogistic regression complete. n={result.n_observations}, events={result.n_outcomes}"
        )
        click.echo(result.table.to_string(index=False))


@cli.command("export-brief")
@click.option("--output", default="brief.md", type=click.Path(path_type=Path))
@click.option("--format", "fmt", default="markdown", type=click.Choice(["markdown", "html"]))
@click.option("--db-path", default=None, type=click.Path(path_type=Path))
def export_brief(output: Path, fmt: str, db_path: Path | None) -> None:
    """Render and save an evidence brief."""
    cfg = AppConfig()
    db_path = (db_path or cfg.resolved_db_path).resolve()

    if not db_path.exists():
        raise click.ClickException(f"Database not found: {db_path}.")

    from evidence_studio.database import get_connection
    from evidence_studio.reporting import render_brief

    conn = get_connection(db_path)
    text = render_brief(conn, output_format=fmt)
    Path(output).write_text(text, encoding="utf-8")
    click.echo(f"Evidence brief saved to: {output}")
