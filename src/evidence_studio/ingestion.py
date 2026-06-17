"""CSV ingestion — load source files into the raw DuckDB schema."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import duckdb

from evidence_studio.audit import DATA_SOURCE_UNKNOWN, ensure_audit_schema, log_assumption
from evidence_studio.database import execute_sql, run_query

logger = logging.getLogger(__name__)

REQUIRED_FILES = ["patients", "encounters", "conditions", "medications", "observations"]
OPTIONAL_FILES = [
    "procedures",
    "allergies",
    "immunizations",
    "careplans",
    "devices",
    "supplies",
    "payers",
    "payer_transitions",
    "organizations",
    "providers",
]


class IngestionError(Exception):
    """Raised when a required source file is missing or unreadable."""


def ingest(
    conn: duckdb.DuckDBPyConnection,
    data_dir: Path,
    *,
    required_only: bool = False,
    data_source: str = DATA_SOURCE_UNKNOWN,
) -> dict[str, int]:
    """Load all discovered CSV files into the raw schema.

    ``data_source`` is stored in the audit manifest for every loaded file.
    Use one of the constants from :mod:`evidence_studio.audit`:
    ``DATA_SOURCE_OFFICIAL_SYNTHEA``, ``DATA_SOURCE_CUSTOM_DEMO``, or
    ``DATA_SOURCE_UNKNOWN`` (default).

    Returns a mapping of table name to row count for every file loaded.
    """
    ensure_audit_schema(conn)
    data_dir = data_dir.resolve()

    if not data_dir.is_dir():
        raise IngestionError(f"Data directory not found: {data_dir}")

    _check_required_files(data_dir)

    targets = REQUIRED_FILES if required_only else REQUIRED_FILES + OPTIONAL_FILES
    row_counts: dict[str, int] = {}

    with conn.cursor() as cursor:
        cursor.execute("BEGIN")
        try:
            for name in targets:
                csv_path = data_dir / f"{name}.csv"
                if not csv_path.exists():
                    if name in REQUIRED_FILES:
                        raise IngestionError(f"Required file missing: {csv_path}")
                    logger.debug("Optional file absent, skipping: %s", csv_path.name)
                    continue
                n_rows = _load_table(conn, name, csv_path)
                row_counts[name] = n_rows
                _record_manifest(conn, name, csv_path, n_rows, data_source)
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise

    log_assumption(
        conn,
        f"Loaded {len(row_counts)} tables from {data_dir}. "
        f"data_source={data_source!r}. "
        "Source files were not modified; raw schema reflects exact CSV contents.",
        context="ingestion",
    )
    return row_counts


def _check_required_files(data_dir: Path) -> None:
    """Raise IngestionError if any required file is absent."""
    missing = [f for f in REQUIRED_FILES if not (data_dir / f"{f}.csv").exists()]
    if missing:
        raise IngestionError(
            f"Missing required CSV files: {', '.join(missing)}. Expected them in: {data_dir}"
        )


def _load_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    csv_path: Path,
) -> int:
    """Load one CSV into raw schema, replacing any existing table."""
    logger.info("Loading %s → raw.%s", csv_path.name, table_name)

    # DuckDB's read_csv_auto preserves all columns and infers types.
    # We do no transformations here — that belongs to the standardized layer.
    sql = (
        f"CREATE OR REPLACE TABLE raw.{table_name} AS "
        f"SELECT * FROM read_csv_auto('{csv_path.as_posix()}', all_varchar=true)"
    )
    execute_sql(conn, sql)

    count_df = run_query(conn, f"SELECT count(*) AS n FROM raw.{table_name}")
    n_rows = int(count_df["n"].iloc[0])
    logger.info("  Loaded %d rows into raw.%s", n_rows, table_name)
    return n_rows


def _sha256(path: Path) -> str:
    """Compute a SHA-256 hex digest for a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _record_manifest(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    csv_path: Path,
    row_count: int,
    data_source: str = DATA_SOURCE_UNKNOWN,
) -> None:
    """Upsert a manifest entry for a loaded file."""
    col_df = run_query(conn, f"DESCRIBE raw.{table_name}")
    n_cols = len(col_df)
    file_size = csv_path.stat().st_size
    sha = _sha256(csv_path)

    conn.execute(
        "INSERT INTO audit.data_manifest "
        "(manifest_id, file_name, file_path, file_size_bytes, row_count, column_count, sha256_hash, data_source) "
        "VALUES (nextval('audit.manifest_seq'), ?, ?, ?, ?, ?, ?, ?)",
        [csv_path.name, str(csv_path), file_size, row_count, n_cols, sha, data_source],
    )


def build_standardized(conn: duckdb.DuckDBPyConnection) -> None:
    """Run all standardized-layer SQL transformations in dependency order."""
    _std_patients(conn)
    _std_encounters(conn)
    _std_conditions(conn)
    _std_medications(conn)
    _std_observations(conn)
    logger.info("Standardized layer complete.")


def _std_patients(conn: duckdb.DuckDBPyConnection) -> None:
    """Build standardized.patients from raw.patients."""
    sql = """
    CREATE OR REPLACE TABLE standardized.patients AS
    SELECT
        Id                                   AS patient_id,
        TRY_CAST(BIRTHDATE AS DATE)          AS birth_date,
        TRY_CAST(DEATHDATE AS DATE)          AS death_date,
        LOWER(TRIM(RACE))                    AS race,
        LOWER(TRIM(ETHNICITY))               AS ethnicity,
        LOWER(TRIM(GENDER))                  AS sex,
        TRIM(CITY)                           AS city,
        TRIM(STATE)                          AS state,
        TRIM(ZIP)                            AS zip_code,
        TRIM(FIRST)                          AS first_name,
        TRIM(LAST)                           AS last_name,
        Id                                   AS source_patient_id
    FROM raw.patients
    WHERE Id IS NOT NULL
    """
    execute_sql(conn, sql)
    n = run_query(conn, "SELECT count(*) AS n FROM standardized.patients")["n"].iloc[0]
    logger.info("standardized.patients: %d rows", n)


def _std_encounters(conn: duckdb.DuckDBPyConnection) -> None:
    """Build standardized.encounters from raw.encounters."""
    sql = """
    CREATE OR REPLACE TABLE standardized.encounters AS
    SELECT
        Id                                         AS encounter_id,
        TRY_CAST(START AS TIMESTAMP)               AS encounter_start,
        TRY_CAST(STOP AS TIMESTAMP)                AS encounter_stop,
        PATIENT                                    AS patient_id,
        LOWER(TRIM(ENCOUNTERCLASS))                AS encounter_class,
        TRIM(CODE)                                 AS encounter_code,
        TRIM(DESCRIPTION)                          AS encounter_description,
        TRIM(REASONCODE)                           AS reason_code,
        TRIM(REASONDESCRIPTION)                    AS reason_description,
        ORGANIZATION                               AS organization_id,
        PROVIDER                                   AS provider_id,
        TRY_CAST(BASE_ENCOUNTER_COST AS DOUBLE)    AS base_cost,
        TRY_CAST(TOTAL_CLAIM_COST AS DOUBLE)       AS total_cost
    FROM raw.encounters
    WHERE Id IS NOT NULL AND PATIENT IS NOT NULL
    """
    execute_sql(conn, sql)
    n = run_query(conn, "SELECT count(*) AS n FROM standardized.encounters")["n"].iloc[0]
    logger.info("standardized.encounters: %d rows", n)


def _std_conditions(conn: duckdb.DuckDBPyConnection) -> None:
    """Build standardized.conditions from raw.conditions."""
    sql = """
    CREATE OR REPLACE TABLE standardized.conditions AS
    SELECT
        PATIENT                              AS patient_id,
        ENCOUNTER                            AS encounter_id,
        TRY_CAST(START AS DATE)              AS condition_start,
        TRY_CAST(STOP AS DATE)               AS condition_stop,
        TRIM(CODE)                           AS condition_code,
        LOWER(TRIM(DESCRIPTION))             AS condition_description
    FROM raw.conditions
    WHERE PATIENT IS NOT NULL
    """
    execute_sql(conn, sql)
    n = run_query(conn, "SELECT count(*) AS n FROM standardized.conditions")["n"].iloc[0]
    logger.info("standardized.conditions: %d rows", n)


def _std_medications(conn: duckdb.DuckDBPyConnection) -> None:
    """Build standardized.medications from raw.medications."""
    sql = """
    CREATE OR REPLACE TABLE standardized.medications AS
    SELECT
        PATIENT                              AS patient_id,
        ENCOUNTER                            AS encounter_id,
        TRY_CAST(START AS DATE)              AS medication_start,
        TRY_CAST(STOP AS DATE)               AS medication_stop,
        TRIM(CODE)                           AS medication_code,
        LOWER(TRIM(DESCRIPTION))             AS medication_description,
        TRIM(REASONCODE)                     AS reason_code,
        LOWER(TRIM(REASONDESCRIPTION))       AS reason_description,
        TRY_CAST(DISPENSES AS INTEGER)       AS dispenses,
        TRY_CAST(BASE_COST AS DOUBLE)        AS base_cost
    FROM raw.medications
    WHERE PATIENT IS NOT NULL
    """
    execute_sql(conn, sql)
    n = run_query(conn, "SELECT count(*) AS n FROM standardized.medications")["n"].iloc[0]
    logger.info("standardized.medications: %d rows", n)


def _std_observations(conn: duckdb.DuckDBPyConnection) -> None:
    """Build standardized.observations from raw.observations."""
    sql = """
    CREATE OR REPLACE TABLE standardized.observations AS
    SELECT
        PATIENT                              AS patient_id,
        ENCOUNTER                            AS encounter_id,
        TRY_CAST(DATE AS DATE)               AS observation_date,
        TRIM(CODE)                           AS observation_code,
        LOWER(TRIM(DESCRIPTION))             AS observation_description,
        TRIM(VALUE)                          AS value_as_string,
        TRY_CAST(VALUE AS DOUBLE)            AS value_as_number,
        TRIM(UNITS)                          AS unit,
        LOWER(TRIM(TYPE))                    AS observation_type
    FROM raw.observations
    WHERE PATIENT IS NOT NULL
    """
    execute_sql(conn, sql)
    n = run_query(conn, "SELECT count(*) AS n FROM standardized.observations")["n"].iloc[0]
    logger.info("standardized.observations: %d rows", n)
