"""Audit trail — assumptions, SQL log, run history, schema DDL."""

from __future__ import annotations

import json
import logging
from typing import Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_AUDIT_DDL = """
CREATE SEQUENCE IF NOT EXISTS audit.manifest_seq START 1;
CREATE SEQUENCE IF NOT EXISTS audit.dq_seq START 1;

CREATE TABLE IF NOT EXISTS audit.data_manifest (
    manifest_id     INTEGER PRIMARY KEY,
    file_name       VARCHAR NOT NULL,
    file_path       VARCHAR NOT NULL,
    file_size_bytes BIGINT,
    row_count       BIGINT,
    column_count    INTEGER,
    sha256_hash     VARCHAR,
    load_timestamp  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit.dq_results (
    dq_id         INTEGER PRIMARY KEY,
    rule_name     VARCHAR NOT NULL,
    status        VARCHAR NOT NULL,  -- PASS | FAIL | WARN
    affected_rows BIGINT,
    message       VARCHAR,
    checked_at    TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit.study_runs (
    run_id          VARCHAR PRIMARY KEY,
    run_timestamp   TIMESTAMP NOT NULL DEFAULT now(),
    config_json     VARCHAR,
    synthea_dir     VARCHAR,
    db_path         VARCHAR,
    n_enrolled      INTEGER,
    n_with_outcome  INTEGER
);

CREATE TABLE IF NOT EXISTS audit.cohort_attrition (
    attrition_id        INTEGER PRIMARY KEY,
    run_id              VARCHAR NOT NULL,
    step_number         INTEGER NOT NULL,
    rule_label          VARCHAR NOT NULL,
    patients_remaining  INTEGER NOT NULL,
    patients_removed    INTEGER NOT NULL,
    pct_retained        DOUBLE
);

CREATE SEQUENCE IF NOT EXISTS audit.attrition_seq START 1;

CREATE TABLE IF NOT EXISTS audit.generated_sql (
    sql_id      INTEGER PRIMARY KEY,
    label       VARCHAR NOT NULL,
    sql_text    VARCHAR NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS audit.sql_seq START 1;

CREATE TABLE IF NOT EXISTS audit.assumption_log (
    assumption_id  INTEGER PRIMARY KEY,
    context        VARCHAR,
    assumption_text VARCHAR NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS audit.assumption_seq START 1;
"""


def ensure_audit_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all audit tables and sequences if they do not exist."""
    conn.execute(_AUDIT_DDL)


def log_assumption(
    conn: duckdb.DuckDBPyConnection,
    text: str,
    context: Optional[str] = None,
) -> None:
    """Append an assumption entry to audit.assumption_log."""
    conn.execute(
        "INSERT INTO audit.assumption_log (assumption_id, context, assumption_text) "
        "VALUES (nextval('audit.assumption_seq'), ?, ?)",
        [context, text],
    )
    logger.info("ASSUMPTION [%s]: %s", context or "general", text)


def log_sql(
    conn: duckdb.DuckDBPyConnection,
    label: str,
    sql_text: str,
) -> None:
    """Append a SQL statement to audit.generated_sql."""
    conn.execute(
        "INSERT INTO audit.generated_sql (sql_id, label, sql_text) "
        "VALUES (nextval('audit.sql_seq'), ?, ?)",
        [label, sql_text],
    )


def record_study_run(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    config_dict: dict,
    synthea_dir: str,
    db_path: str,
    n_enrolled: int = 0,
    n_with_outcome: int = 0,
) -> None:
    """Insert or replace a study run record."""
    conn.execute(
        "INSERT OR REPLACE INTO audit.study_runs "
        "(run_id, run_timestamp, config_json, synthea_dir, db_path, n_enrolled, n_with_outcome) "
        "VALUES (?, now(), ?, ?, ?, ?, ?)",
        [run_id, json.dumps(config_dict), synthea_dir, db_path, n_enrolled, n_with_outcome],
    )


def record_attrition_step(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    step_number: int,
    rule_label: str,
    patients_remaining: int,
    patients_removed: int,
) -> None:
    """Append one attrition step for a given run."""
    pct = (
        round(patients_remaining / (patients_remaining + patients_removed) * 100, 1)
        if (patients_remaining + patients_removed) > 0
        else None
    )
    conn.execute(
        "INSERT INTO audit.cohort_attrition "
        "(attrition_id, run_id, step_number, rule_label, patients_remaining, patients_removed, pct_retained) "
        "VALUES (nextval('audit.attrition_seq'), ?, ?, ?, ?, ?, ?)",
        [run_id, step_number, rule_label, patients_remaining, patients_removed, pct],
    )


def get_run_history(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return recent study runs as a DataFrame."""
    from evidence_studio.database import run_query, table_exists

    if not table_exists(conn, "audit", "study_runs"):
        return pd.DataFrame()
    return run_query(
        conn,
        "SELECT run_id, run_timestamp, n_enrolled, n_with_outcome "
        "FROM audit.study_runs ORDER BY run_timestamp DESC LIMIT 20",
    )
