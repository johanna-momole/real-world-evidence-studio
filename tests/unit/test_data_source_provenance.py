"""Integration tests for data-source provenance end-to-end.

Verifies that the data_source value flows correctly through:
  ingestion manifest → cohort builder → study_runs record → evidence brief context

Scenarios:
1.  official_synthea manifest → CohortBuilder._data_source() returns official_synthea
2.  custom_synthetic_demo manifest → _data_source() returns custom_synthetic_demo
3.  unknown_synthetic_source manifest → _data_source() returns unknown value
4.  Legacy database missing data_source column → migration adds it correctly
5.  Re-ingestion with different source → cohort build picks up the new source
6.  Multiple manifest rows → most-recent source used at cohort-build time
7.  Historical evidence brief → old run shows its own data_source, not the current manifest
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from evidence_studio.audit import (
    DATA_SOURCE_CUSTOM_DEMO,
    DATA_SOURCE_OFFICIAL_SYNTHEA,
    DATA_SOURCE_UNKNOWN,
    ensure_audit_schema,
    record_study_run,
)
from evidence_studio.cohort import CohortBuilder
from evidence_studio.config import StudyConfig
from evidence_studio.reporting import _load_run_config

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fresh_conn(tmp_path: Path, suffix: str = "prov.duckdb") -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(tmp_path / suffix))
    conn.execute("CREATE SCHEMA IF NOT EXISTS audit")
    ensure_audit_schema(conn)
    return conn


def _insert_manifest_row(
    conn: duckdb.DuckDBPyConnection,
    data_source: str,
    ts_offset_seconds: int = 0,
) -> None:
    """Insert a manifest row; ts_offset_seconds nudges the timestamp for ordering tests."""
    conn.execute(
        "INSERT INTO audit.data_manifest "
        "(manifest_id, file_name, file_path, file_size_bytes, row_count, "
        " column_count, sha256_hash, data_source, load_timestamp) "
        "VALUES (nextval('audit.manifest_seq'), 'patients.csv', '/tmp', "
        "       1024, 100, 5, 'abc123', ?, "
        f"       now() + INTERVAL '{ts_offset_seconds} seconds')",
        [data_source],
    )


def _builder(conn: duckdb.DuckDBPyConnection) -> CohortBuilder:
    return CohortBuilder(conn, StudyConfig())


# ── Test 1 ─────────────────────────────────────────────────────────────────────


def test_official_synthea_manifest_propagates_to_data_source(tmp_path: Path) -> None:
    """Manifest row with official_synthea → CohortBuilder._data_source() returns it."""
    conn = _fresh_conn(tmp_path, "t1.duckdb")
    _insert_manifest_row(conn, DATA_SOURCE_OFFICIAL_SYNTHEA)

    result = _builder(conn)._data_source()
    conn.close()

    assert result == DATA_SOURCE_OFFICIAL_SYNTHEA, (
        f"Expected '{DATA_SOURCE_OFFICIAL_SYNTHEA}', got '{result}'"
    )


# ── Test 2 ─────────────────────────────────────────────────────────────────────


def test_custom_demo_manifest_propagates_to_data_source(tmp_path: Path) -> None:
    """Manifest row with custom_synthetic_demo → _data_source() returns it."""
    conn = _fresh_conn(tmp_path, "t2.duckdb")
    _insert_manifest_row(conn, DATA_SOURCE_CUSTOM_DEMO)

    result = _builder(conn)._data_source()
    conn.close()

    assert result == DATA_SOURCE_CUSTOM_DEMO, (
        f"Expected '{DATA_SOURCE_CUSTOM_DEMO}', got '{result}'"
    )


# ── Test 3 ─────────────────────────────────────────────────────────────────────


def test_unknown_manifest_propagates_to_data_source(tmp_path: Path) -> None:
    """Manifest row with unknown_synthetic_source → _data_source() returns it."""
    conn = _fresh_conn(tmp_path, "t3.duckdb")
    _insert_manifest_row(conn, DATA_SOURCE_UNKNOWN)

    result = _builder(conn)._data_source()
    conn.close()

    assert result == DATA_SOURCE_UNKNOWN, f"Expected '{DATA_SOURCE_UNKNOWN}', got '{result}'"


# ── Test 4 ─────────────────────────────────────────────────────────────────────


def test_legacy_database_migration_adds_data_source_column(tmp_path: Path) -> None:
    """A DB created without data_source gains the column when ensure_audit_schema is called."""
    conn = duckdb.connect(str(tmp_path / "t4_legacy.duckdb"))
    conn.execute("CREATE SCHEMA IF NOT EXISTS audit")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS audit.manifest_seq START 1")
    # Create the old manifest table without data_source
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit.data_manifest ("
        "    manifest_id     INTEGER PRIMARY KEY,"
        "    file_name       VARCHAR NOT NULL,"
        "    file_path       VARCHAR NOT NULL,"
        "    file_size_bytes BIGINT,"
        "    row_count       BIGINT,"
        "    column_count    INTEGER,"
        "    sha256_hash     VARCHAR,"
        "    load_timestamp  TIMESTAMP NOT NULL DEFAULT now()"
        ")"
    )

    # Migration must add data_source when ensure_audit_schema runs
    ensure_audit_schema(conn)

    col_exists = conn.execute(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'audit' AND table_name = 'data_manifest' "
        "AND column_name = 'data_source'"
    ).fetchone()[0]
    conn.close()

    assert col_exists == 1, "Migration failed: 'data_source' column not found in data_manifest"


# ── Test 5 ─────────────────────────────────────────────────────────────────────


def test_re_ingestion_with_new_source_updates_data_source(tmp_path: Path) -> None:
    """After a second manifest row with a different source, _data_source() reflects the new one."""
    conn = _fresh_conn(tmp_path, "t5.duckdb")
    _insert_manifest_row(conn, DATA_SOURCE_OFFICIAL_SYNTHEA, ts_offset_seconds=0)
    _insert_manifest_row(conn, DATA_SOURCE_CUSTOM_DEMO, ts_offset_seconds=10)

    result = _builder(conn)._data_source()
    conn.close()

    assert result == DATA_SOURCE_CUSTOM_DEMO, (
        f"Expected most-recent source '{DATA_SOURCE_CUSTOM_DEMO}', got '{result}'"
    )


# ── Test 6 ─────────────────────────────────────────────────────────────────────


def test_multiple_manifest_rows_most_recent_used(tmp_path: Path) -> None:
    """When many manifest rows exist, the latest load_timestamp wins."""
    conn = _fresh_conn(tmp_path, "t6.duckdb")
    _insert_manifest_row(conn, DATA_SOURCE_CUSTOM_DEMO, ts_offset_seconds=0)
    _insert_manifest_row(conn, DATA_SOURCE_UNKNOWN, ts_offset_seconds=5)
    _insert_manifest_row(conn, DATA_SOURCE_OFFICIAL_SYNTHEA, ts_offset_seconds=10)

    result = _builder(conn)._data_source()
    conn.close()

    assert result == DATA_SOURCE_OFFICIAL_SYNTHEA, (
        f"Expected latest manifest source '{DATA_SOURCE_OFFICIAL_SYNTHEA}', got '{result}'"
    )


# ── Test 7 ─────────────────────────────────────────────────────────────────────


def test_historical_run_shows_its_own_data_source_not_latest_manifest(tmp_path: Path) -> None:
    """_load_run_config reads data_source from the run record, not the current manifest."""
    conn = _fresh_conn(tmp_path, "t7.duckdb")

    # Record two runs with different data_sources
    run_id_a = "run_aaaaaaaaaaaaa"
    run_id_b = "run_bbbbbbbbbbbbb"
    record_study_run(conn, run_id_a, {}, data_source=DATA_SOURCE_OFFICIAL_SYNTHEA)
    record_study_run(conn, run_id_b, {}, data_source=DATA_SOURCE_CUSTOM_DEMO)

    # Simulate later re-ingestion with unknown source (manifest now says unknown)
    _insert_manifest_row(conn, DATA_SOURCE_UNKNOWN)

    # Each historical run must still show its own recorded data_source
    ctx_a: dict = {}
    _load_run_config(conn, run_id_a, ctx_a)

    ctx_b: dict = {}
    _load_run_config(conn, run_id_b, ctx_b)

    conn.close()

    assert ctx_a.get("data_source") == DATA_SOURCE_OFFICIAL_SYNTHEA, (
        f"Run A should show '{DATA_SOURCE_OFFICIAL_SYNTHEA}', got '{ctx_a.get('data_source')}'"
    )
    assert ctx_b.get("data_source") == DATA_SOURCE_CUSTOM_DEMO, (
        f"Run B should show '{DATA_SOURCE_CUSTOM_DEMO}', got '{ctx_b.get('data_source')}'"
    )
