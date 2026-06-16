"""Unit and integration tests for the ingestion and data quality layers."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture()
def db_conn(tmp_path: Path):
    """Return a fresh DuckDB connection for each test."""
    from evidence_studio.database import get_connection

    conn = get_connection(tmp_path / "test.duckdb")
    yield conn
    conn.close()


@pytest.fixture()
def ingested_conn(tmp_path: Path):
    """Return a connection with fixtures ingested into raw + standardized."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import build_standardized, ingest

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_audit_schema(conn)
    ingest(conn, FIXTURES)
    build_standardized(conn)
    yield conn
    conn.close()


# ── Ingestion tests ────────────────────────────────────────────────────────────


def test_ingest_returns_row_counts(tmp_path: Path) -> None:
    """ingest() should return a dict with positive row counts for all five tables."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import ingest

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_audit_schema(conn)
    counts = ingest(conn, FIXTURES)

    assert "patients" in counts
    assert "encounters" in counts
    assert "conditions" in counts
    assert "medications" in counts
    assert "observations" in counts
    assert all(v > 0 for v in counts.values())
    conn.close()


def test_ingest_idempotent(tmp_path: Path) -> None:
    """Running ingest twice should not raise and should update row counts."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import ingest

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_audit_schema(conn)
    counts1 = ingest(conn, FIXTURES)
    counts2 = ingest(conn, FIXTURES)
    assert counts1 == counts2
    conn.close()


def test_ingest_missing_required_file_raises(tmp_path: Path) -> None:
    """ingest() should raise IngestionError when a required file is absent."""
    from evidence_studio.ingestion import IngestionError, ingest

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_audit_schema(conn)

    with pytest.raises(IngestionError):
        ingest(conn, empty_dir)
    conn.close()


def test_ingest_missing_directory_raises(tmp_path: Path) -> None:
    """ingest() should raise IngestionError when the data directory is absent."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import IngestionError, ingest

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_audit_schema(conn)

    with pytest.raises(IngestionError):
        ingest(conn, tmp_path / "nonexistent_dir")
    conn.close()


def test_raw_tables_created(tmp_path: Path) -> None:
    """raw schema should have all five required tables after ingestion."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection, table_exists
    from evidence_studio.ingestion import ingest

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_audit_schema(conn)
    ingest(conn, FIXTURES)

    for table in ("patients", "encounters", "conditions", "medications", "observations"):
        assert table_exists(conn, "raw", table), f"raw.{table} not found"
    conn.close()


def test_manifest_recorded(ingested_conn) -> None:
    """audit.data_manifest should have one entry per loaded file."""
    from evidence_studio.database import run_query

    df = run_query(ingested_conn, "SELECT file_name FROM audit.data_manifest")
    assert len(df) >= 5


# ── Standardized-layer tests ───────────────────────────────────────────────────


def test_standardized_patients_row_count(ingested_conn) -> None:
    """standardized.patients should have the same count as raw.patients."""
    from evidence_studio.database import row_count

    assert row_count(ingested_conn, "standardized", "patients") == row_count(
        ingested_conn, "raw", "patients"
    )


def test_standardized_patients_has_birth_date(ingested_conn) -> None:
    """standardized.patients birth_date must be a DATE column with no nulls."""
    from evidence_studio.database import run_query

    df = run_query(
        ingested_conn,
        "SELECT count(*) AS n FROM standardized.patients WHERE birth_date IS NULL",
    )
    assert int(df["n"].iloc[0]) == 0


def test_standardized_encounters_class_lowercase(ingested_conn) -> None:
    """encounter_class values must all be lowercase."""
    from evidence_studio.database import run_query

    df = run_query(
        ingested_conn,
        "SELECT DISTINCT encounter_class FROM standardized.encounters",
    )
    for cls in df["encounter_class"].dropna():
        assert cls == cls.lower(), f"encounter_class not lowercase: {cls!r}"


def test_standardized_conditions_description_lowercase(ingested_conn) -> None:
    """condition_description values must all be lowercase."""
    from evidence_studio.database import run_query

    df = run_query(
        ingested_conn,
        "SELECT DISTINCT condition_description FROM standardized.conditions",
    )
    for desc in df["condition_description"].dropna():
        assert desc == desc.lower()


def test_standardized_medications_description_lowercase(ingested_conn) -> None:
    """medication_description values must all be lowercase."""
    from evidence_studio.database import run_query

    df = run_query(
        ingested_conn,
        "SELECT DISTINCT medication_description FROM standardized.medications",
    )
    for desc in df["medication_description"].dropna():
        assert desc == desc.lower()


# ── Data quality tests ─────────────────────────────────────────────────────────


def test_dq_passes_on_fixture_data(ingested_conn) -> None:
    """All critical DQ rules should pass on the clean fixture data."""
    from evidence_studio.data_quality import run_dq_checks

    report = run_dq_checks(ingested_conn)
    failed = [r for r in report.results if r.status == "FAIL"]
    assert failed == [], f"DQ failures: {[r.rule_name for r in failed]}"


def test_dq_detects_orphan_encounter(tmp_path: Path) -> None:
    """An encounter pointing to a non-existent patient should produce a WARN."""

    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.data_quality import run_dq_checks
    from evidence_studio.database import execute_sql, get_connection
    from evidence_studio.ingestion import build_standardized, ingest

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_audit_schema(conn)
    ingest(conn, FIXTURES)
    build_standardized(conn)

    # Inject a foreign-key violation
    execute_sql(
        conn,
        "INSERT INTO standardized.encounters "
        "(encounter_id, encounter_start, patient_id, encounter_class) "
        "VALUES ('orphan-enc', '2020-01-01'::TIMESTAMP, 'GHOST-PATIENT', 'ambulatory')",
    )

    report = run_dq_checks(conn)
    orphan = next((r for r in report.results if r.rule_name == "orphan_encounters"), None)
    assert orphan is not None
    assert orphan.status == "WARN"
    assert orphan.affected_rows >= 1
    conn.close()
