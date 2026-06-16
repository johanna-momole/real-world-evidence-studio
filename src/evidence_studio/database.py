"""DuckDB connection management and SQL execution utilities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

_SCHEMAS = ("raw", "standardized", "analytics", "omop", "audit")


def get_connection(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Open a file-backed DuckDB connection and initialise required schemas."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    _ensure_schemas(conn)
    return conn


def _ensure_schemas(conn: duckdb.DuckDBPyConnection) -> None:
    """Create application schemas if they do not already exist."""
    for schema in _SCHEMAS:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def run_query(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: Optional[dict[str, Any]] = None,
) -> pd.DataFrame:
    """Execute a SELECT query and return a DataFrame."""
    try:
        if params:
            return conn.execute(sql, list(params.values())).df()
        return conn.execute(sql).df()
    except duckdb.Error as exc:
        logger.error("Query failed: %s\nSQL: %.500s", exc, sql)
        raise


def execute_sql(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: Optional[dict[str, Any]] = None,
) -> None:
    """Execute a non-SELECT statement (DDL, INSERT, CREATE TABLE AS, etc.)."""
    try:
        if params:
            conn.execute(sql, list(params.values()))
        else:
            conn.execute(sql)
    except duckdb.Error as exc:
        logger.error("Statement failed: %s\nSQL: %.500s", exc, sql)
        raise


def execute_sql_file(
    conn: duckdb.DuckDBPyConnection,
    path: Path,
    params: Optional[dict[str, Any]] = None,
) -> None:
    """Read a .sql file and execute it as a single statement block."""
    sql = path.read_text(encoding="utf-8")
    logger.debug("Executing SQL file: %s", path.name)
    execute_sql(conn, sql, params)


def table_exists(conn: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    """Return True if the given schema.table exists in the database."""
    result = run_query(
        conn,
        "SELECT count(*) AS n FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?",
        {"schema": schema, "table": table},
    )
    return int(result["n"].iloc[0]) > 0


def row_count(conn: duckdb.DuckDBPyConnection, schema: str, table: str) -> int:
    """Return the row count of a table, or -1 if the table does not exist."""
    if not table_exists(conn, schema, table):
        return -1
    result = run_query(conn, f"SELECT count(*) AS n FROM {schema}.{table}")
    return int(result["n"].iloc[0])
