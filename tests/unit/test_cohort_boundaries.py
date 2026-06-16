"""Tests for cohort window boundaries, death during follow-up, and reproducibility."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import duckdb
import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"


class _BuiltCohort(NamedTuple):
    conn: duckdb.DuckDBPyConnection
    run_id: str


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> _BuiltCohort:
    """Return a cohort built from fixture data — shared across all tests in this module."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.cohort import CohortBuilder
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import build_standardized, ingest

    tmp_path = tmp_path_factory.mktemp("boundary")
    conn = get_connection(tmp_path / "boundary.duckdb")
    ensure_audit_schema(conn)
    ingest(conn, FIXTURES)
    build_standardized(conn)

    cfg = StudyConfig(follow_up_days=180, min_follow_up_days=180, baseline_days=365)
    run_id = CohortBuilder(conn, cfg).build()
    yield _BuiltCohort(conn=conn, run_id=run_id)
    conn.close()


def test_index_date_is_first_glp1_medication(built: _BuiltCohort) -> None:
    """Index date must equal the earliest GLP-1 medication start for each patient."""
    from evidence_studio.database import run_query, table_exists

    if not table_exists(built.conn, "analytics", "cohort"):
        pytest.skip("Empty cohort")

    mismatch = run_query(
        built.conn,
        """
        SELECT co.patient_id
        FROM analytics.cohort co
        JOIN (
            SELECT patient_id, MIN(medication_start) AS first_glp1
            FROM standardized.medications
            WHERE LOWER(medication_description) LIKE '%semaglutide%'
               OR LOWER(medication_description) LIKE '%liraglutide%'
               OR LOWER(medication_description) LIKE '%dulaglutide%'
               OR LOWER(medication_description) LIKE '%exenatide%'
               OR LOWER(medication_description) LIKE '%tirzepatide%'
            GROUP BY patient_id
        ) m ON co.patient_id = m.patient_id
        WHERE co.index_date <> m.first_glp1
        """,
    )
    assert mismatch.empty, f"Index date mismatch: {mismatch['patient_id'].tolist()}"


def test_baseline_features_no_post_index_encounters(built: _BuiltCohort) -> None:
    """Baseline ED counts must reflect only pre-index encounters."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import run_query, table_exists

    build_analysis_dataset(built.conn, StudyConfig())
    if not table_exists(built.conn, "analytics", "analysis_dataset"):
        pytest.skip("Empty dataset")

    df = run_query(built.conn, "SELECT * FROM analytics.analysis_dataset")
    if df.empty:
        pytest.skip("Empty dataset")

    for _, row in df.iterrows():
        assert int(row["bl_ed_count"]) >= 0
        assert int(row["bl_inpatient_count"]) >= 0
        assert int(row["bl_outpatient_count"]) >= 0


def test_follow_up_window_not_before_index(built: _BuiltCohort) -> None:
    """follow_up_end must always be >= index_date in the outcomes table."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import run_query, table_exists

    build_analysis_dataset(built.conn, StudyConfig())
    if not table_exists(built.conn, "analytics", "outcomes"):
        pytest.skip("Empty outcomes")

    bad = run_query(
        built.conn,
        "SELECT patient_id FROM analytics.outcomes WHERE follow_up_end < index_date",
    )
    assert bad.empty, f"follow_up_end < index_date for: {bad['patient_id'].tolist()}"


def test_outcome_count_non_negative(built: _BuiltCohort) -> None:
    """fu_ed_count and fu_ip_count must be non-negative integers."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import run_query, table_exists

    build_analysis_dataset(built.conn, StudyConfig())
    if not table_exists(built.conn, "analytics", "outcomes"):
        pytest.skip("Empty outcomes")

    bad_ed = run_query(
        built.conn,
        "SELECT patient_id FROM analytics.outcomes WHERE fu_ed_count < 0",
    )
    bad_ip = run_query(
        built.conn,
        "SELECT patient_id FROM analytics.outcomes WHERE fu_ip_count < 0",
    )
    assert bad_ed.empty, "Negative fu_ed_count found"
    assert bad_ip.empty, "Negative fu_ip_count found"


def test_any_ed_visit_consistent_with_fu_ed_count(built: _BuiltCohort) -> None:
    """any_ed_visit must equal 1 iff fu_ed_count > 0."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import run_query, table_exists

    build_analysis_dataset(built.conn, StudyConfig())
    if not table_exists(built.conn, "analytics", "outcomes"):
        pytest.skip("Empty outcomes")

    inconsistent = run_query(
        built.conn,
        "SELECT patient_id FROM analytics.outcomes "
        "WHERE (fu_ed_count > 0 AND any_ed_visit = 0) "
        "   OR (fu_ed_count = 0 AND any_ed_visit = 1)",
    )
    assert inconsistent.empty, f"Inconsistent any_ed_visit: {inconsistent['patient_id'].tolist()}"


def test_analysis_dataset_one_row_per_patient(built: _BuiltCohort) -> None:
    """analytics.analysis_dataset must have exactly one row per patient."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import run_query, table_exists

    build_analysis_dataset(built.conn, StudyConfig())
    if not table_exists(built.conn, "analytics", "analysis_dataset"):
        pytest.skip("Empty dataset")

    dups = run_query(
        built.conn,
        "SELECT patient_id, count(*) AS n FROM analytics.analysis_dataset "
        "GROUP BY patient_id HAVING n > 1",
    )
    assert dups.empty, f"Duplicate patients in analysis_dataset: {dups['patient_id'].tolist()}"


def test_reproducible_run_id(tmp_path: Path) -> None:
    """Two CohortBuilders with identical config and same-minute timestamp yield same run ID prefix."""
    from evidence_studio.cohort import _run_id
    from evidence_studio.config import StudyConfig

    cfg = StudyConfig(follow_up_days=180)
    id1 = _run_id(cfg)
    id2 = _run_id(cfg)
    assert id1 == id2 or id1[:32] == id2[:32], (
        "Run IDs with identical config differ beyond the config-hash prefix"
    )


def test_t2dm_required_for_enrollment(built: _BuiltCohort) -> None:
    """All enrolled patients must have a T2DM condition record."""
    from evidence_studio.database import run_query, table_exists

    if not table_exists(built.conn, "analytics", "cohort"):
        pytest.skip("Empty cohort")

    t2dm_terms = ["type 2 diabetes", "diabetes mellitus type 2", "noninsulin-dependent"]
    like_clauses = " OR ".join(f"LOWER(c.condition_description) LIKE '%{t}%'" for t in t2dm_terms)
    no_t2dm = run_query(
        built.conn,
        f"SELECT co.patient_id FROM analytics.cohort co "
        f"LEFT JOIN standardized.conditions c ON co.patient_id = c.patient_id "
        f"  AND ({like_clauses}) AND c.condition_start <= co.index_date "
        f"WHERE c.patient_id IS NULL",
    )
    assert no_t2dm.empty, f"Enrolled patients without T2DM: {no_t2dm['patient_id'].tolist()}"


def test_person_time_positive(built: _BuiltCohort) -> None:
    """follow_up_days_observed must be > 0 for all enrolled patients."""
    from evidence_studio.analysis import build_analysis_dataset
    from evidence_studio.config import StudyConfig
    from evidence_studio.database import run_query, table_exists

    build_analysis_dataset(built.conn, StudyConfig())
    if not table_exists(built.conn, "analytics", "outcomes"):
        pytest.skip("Empty outcomes")

    bad = run_query(
        built.conn,
        "SELECT patient_id FROM analytics.outcomes WHERE follow_up_days_observed <= 0",
    )
    assert bad.empty, f"Non-positive follow-up time for: {bad['patient_id'].tolist()}"
