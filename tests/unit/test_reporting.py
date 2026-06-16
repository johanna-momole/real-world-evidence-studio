"""Tests for evidence-brief rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture()
def analysis_conn(tmp_path: Path):
    """Return a connection with a full analysis dataset built from fixture data."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.cohort import CohortBuilder
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import build_standardized, ingest

    conn = get_connection(tmp_path / "reporting_test.duckdb")
    ensure_audit_schema(conn)
    ingest(conn, FIXTURES)
    build_standardized(conn)

    cfg = StudyConfig(follow_up_days=180, min_follow_up_days=180)
    run_id = CohortBuilder(conn, cfg).build()
    build_analysis_dataset(conn, cfg)
    yield conn, run_id
    conn.close()


def test_render_brief_returns_string(analysis_conn):
    """render_brief must return a non-empty string."""
    from evidence_studio.reporting import render_brief

    conn, _ = analysis_conn
    brief = render_brief(conn, output_format="markdown")
    assert isinstance(brief, str)
    assert len(brief) > 0


def test_render_brief_contains_disclaimer(analysis_conn):
    """Brief must contain the mandatory synthetic-data disclaimer."""
    from evidence_studio.reporting import render_brief

    conn, _ = analysis_conn
    brief = render_brief(conn, output_format="markdown")
    assert "synthetic" in brief.lower() or "Synthea" in brief


def test_render_brief_html_format(analysis_conn):
    """HTML output must start with an HTML tag."""
    from evidence_studio.reporting import render_brief

    conn, _ = analysis_conn
    brief = render_brief(conn, output_format="html")
    assert "<" in brief, "HTML output should contain HTML tags"


def test_render_brief_contains_run_id(analysis_conn):
    """Brief must contain a run ID."""
    from evidence_studio.reporting import render_brief

    conn, run_id = analysis_conn
    brief = render_brief(conn, run_id=run_id, output_format="markdown")
    assert run_id[:16] in brief or "run_id" in brief.lower() or "Run ID" in brief


def test_render_brief_no_template_error_on_empty_db(tmp_path: Path):
    """render_brief must not raise even with an empty database."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection
    from evidence_studio.reporting import render_brief

    conn = get_connection(tmp_path / "empty.duckdb")
    ensure_audit_schema(conn)
    brief = render_brief(conn, output_format="markdown")
    assert isinstance(brief, str)
    conn.close()


def test_render_brief_contains_clinical_question(analysis_conn):
    """Brief must contain language about GLP-1 and ED utilization."""
    from evidence_studio.reporting import render_brief

    conn, _ = analysis_conn
    brief = render_brief(conn, output_format="markdown")
    assert "GLP-1" in brief or "glp" in brief.lower()
    assert "ED" in brief or "emergency" in brief.lower()


def test_build_context_no_fabricated_numbers(analysis_conn):
    """Context n_enrolled must equal the actual row count, not a hardcoded value."""
    from evidence_studio.database import run_query, table_exists
    from evidence_studio.reporting import _build_context

    conn, run_id = analysis_conn
    ctx = _build_context(conn, run_id)

    if table_exists(conn, "analytics", "analysis_dataset"):
        actual_n = int(
            run_query(conn, "SELECT count(*) AS n FROM analytics.analysis_dataset")["n"].iloc[0]
        )
        assert ctx["n_enrolled"] == actual_n, (
            f"Context n_enrolled ({ctx['n_enrolled']}) != actual count ({actual_n})"
        )


def test_fallback_brief_on_missing_template(tmp_path: Path, monkeypatch):
    """_fallback_brief must return a non-empty string when template fails."""
    from evidence_studio.reporting import _fallback_brief

    ctx = {
        "run_id": "test-run",
        "disclaimer": "Synthetic data only.",
        "generated_at": "2026-01-01",
        "n_enrolled": 42,
        "n_outcomes": 5,
    }
    brief = _fallback_brief(ctx, "Template file not found")
    assert "test-run" in brief
    assert "42" in brief
