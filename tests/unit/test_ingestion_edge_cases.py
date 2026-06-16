"""Edge-case tests for ingestion: malformed files, duplicates, orphans."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture(scope="module")
def clean_conn(tmp_path_factory: pytest.TempPathFactory):
    """Return a fresh DuckDB connection with audit schema — shared across module."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection

    tmp_path = tmp_path_factory.mktemp("edge")
    conn = get_connection(tmp_path / "test_edge.duckdb")
    ensure_audit_schema(conn)
    yield conn
    conn.close()


def test_missing_required_file_raises(tmp_path: Path, clean_conn):
    """ingest() must raise when a required file is absent."""
    from evidence_studio.ingestion import IngestionError, ingest

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises((FileNotFoundError, IngestionError)):
        ingest(clean_conn, empty_dir)


def test_missing_directory_raises(clean_conn):
    """ingest() must raise when the data directory does not exist."""
    from evidence_studio.ingestion import IngestionError, ingest

    with pytest.raises((FileNotFoundError, IngestionError)):
        ingest(clean_conn, Path("/nonexistent/synthea/data"))


def test_ingest_records_sha256_hash(tmp_path: Path, clean_conn):
    """Manifest rows must have a non-empty SHA-256 hash."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import ingest

    ingest(clean_conn, FIXTURES)
    df = run_query(clean_conn, "SELECT sha256_hash FROM audit.data_manifest")
    assert not df.empty
    for h in df["sha256_hash"]:
        assert h and len(h) == 64, f"Expected 64-char hex hash, got: {h}"


def test_ingest_records_row_count(tmp_path: Path, clean_conn):
    """Manifest row counts must be positive integers."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import ingest

    ingest(clean_conn, FIXTURES)
    df = run_query(clean_conn, "SELECT row_count FROM audit.data_manifest")
    assert not df.empty
    assert all(int(r) > 0 for r in df["row_count"])


def test_standardized_patients_no_duplicate_ids(tmp_path: Path, clean_conn):
    """standardized.patients must have unique patient_id values."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import build_standardized, ingest

    ingest(clean_conn, FIXTURES)
    build_standardized(clean_conn)
    df = run_query(
        clean_conn,
        "SELECT patient_id, count(*) AS n FROM standardized.patients "
        "GROUP BY patient_id HAVING n > 1",
    )
    assert df.empty, f"Duplicate patient IDs: {df['patient_id'].tolist()}"


def test_standardized_encounters_fk_valid(tmp_path: Path, clean_conn):
    """All encounter patient_ids must exist in standardized.patients."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import build_standardized, ingest

    ingest(clean_conn, FIXTURES)
    build_standardized(clean_conn)
    orphans = run_query(
        clean_conn,
        "SELECT e.encounter_id FROM standardized.encounters e "
        "LEFT JOIN standardized.patients p ON e.patient_id = p.patient_id "
        "WHERE p.patient_id IS NULL",
    )
    assert orphans.empty, f"Orphan encounters: {orphans['encounter_id'].tolist()}"


def test_standardized_conditions_fk_valid(tmp_path: Path, clean_conn):
    """All condition patient_ids must exist in standardized.patients."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import build_standardized, ingest

    ingest(clean_conn, FIXTURES)
    build_standardized(clean_conn)
    orphans = run_query(
        clean_conn,
        "SELECT c.patient_id FROM standardized.conditions c "
        "LEFT JOIN standardized.patients p ON c.patient_id = p.patient_id "
        "WHERE p.patient_id IS NULL",
    )
    assert orphans.empty, f"Orphan conditions: {orphans['patient_id'].tolist()}"


def test_standardized_medications_fk_valid(tmp_path: Path, clean_conn):
    """All medication patient_ids must exist in standardized.patients."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import build_standardized, ingest

    ingest(clean_conn, FIXTURES)
    build_standardized(clean_conn)
    orphans = run_query(
        clean_conn,
        "SELECT m.patient_id FROM standardized.medications m "
        "LEFT JOIN standardized.patients p ON m.patient_id = p.patient_id "
        "WHERE p.patient_id IS NULL",
    )
    assert orphans.empty, f"Orphan medications: {orphans['patient_id'].tolist()}"


def test_standardized_dates_parsed_correctly(tmp_path: Path, clean_conn):
    """Birth dates must be parseable DATE values (not strings)."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import build_standardized, ingest

    ingest(clean_conn, FIXTURES)
    build_standardized(clean_conn)
    df = run_query(
        clean_conn,
        "SELECT patient_id, birth_date FROM standardized.patients WHERE birth_date IS NULL",
    )
    assert df.empty, f"Patients with NULL birth_date: {df['patient_id'].tolist()}"


def test_standardized_encounter_start_before_stop(tmp_path: Path, clean_conn):
    """encounter_stop must not be earlier than encounter_start when both are present."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import build_standardized, ingest

    ingest(clean_conn, FIXTURES)
    build_standardized(clean_conn)
    bad = run_query(
        clean_conn,
        "SELECT encounter_id FROM standardized.encounters "
        "WHERE encounter_stop IS NOT NULL AND encounter_stop < encounter_start",
    )
    assert bad.empty, f"Encounters with stop < start: {bad['encounter_id'].tolist()}"


def test_idempotent_ingest(tmp_path: Path, clean_conn):
    """Running ingest twice must not raise and must not double-count rows."""
    from evidence_studio.database import run_query
    from evidence_studio.ingestion import ingest

    ingest(clean_conn, FIXTURES)
    count1 = int(run_query(clean_conn, "SELECT count(*) AS n FROM raw.patients")["n"].iloc[0])
    ingest(clean_conn, FIXTURES)
    count2 = int(run_query(clean_conn, "SELECT count(*) AS n FROM raw.patients")["n"].iloc[0])
    assert count2 == count1, "Idempotent ingest changed raw.patients row count"
