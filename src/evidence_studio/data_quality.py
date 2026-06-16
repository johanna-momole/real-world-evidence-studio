"""Data quality rules for Synthea source data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import duckdb

from evidence_studio.audit import ensure_audit_schema
from evidence_studio.database import run_query, table_exists

logger = logging.getLogger(__name__)

VALID_ENCOUNTER_CLASSES = {
    "ambulatory",
    "emergency",
    "inpatient",
    "outpatient",
    "urgentcare",
    "wellness",
    "home",
    "virtual",
    "snf",
    "hospice",
}


@dataclass
class DQResult:
    """Result of a single data quality rule evaluation."""

    rule_name: str
    status: str  # PASS | FAIL | WARN
    affected_rows: int
    message: str


@dataclass
class DQReport:
    """Collection of DQ results for a data load."""

    results: list[DQResult] = field(default_factory=list)

    @property
    def n_failed(self) -> int:
        """Count of FAIL results."""
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def n_warned(self) -> int:
        """Count of WARN results."""
        return sum(1 for r in self.results if r.status == "WARN")

    @property
    def passed(self) -> bool:
        """True when no rules failed."""
        return self.n_failed == 0


def run_dq_checks(conn: duckdb.DuckDBPyConnection) -> DQReport:
    """Execute all DQ rules and persist results to audit.dq_results."""
    ensure_audit_schema(conn)
    report = DQReport()

    rules = [
        _check_patients_present,
        _check_encounters_present,
        _check_conditions_present,
        _check_medications_present,
        _check_observations_present,
        _check_patient_id_unique,
        _check_orphan_encounters,
        _check_orphan_conditions,
        _check_orphan_medications,
        _check_encounter_stop_after_start,
        _check_medication_stop_after_start,
        _check_events_before_birth,
        _check_events_after_death,
        _check_missing_patient_sex,
        _check_missing_patient_race,
        _check_missing_patient_birthdate,
        _check_unrecognized_encounter_classes,
        _check_duplicate_condition_rows,
    ]

    for rule_fn in rules:
        try:
            result = rule_fn(conn)
            report.results.append(result)
            _persist_result(conn, result)
            log_level = logging.WARNING if result.status != "PASS" else logging.DEBUG
            logger.log(
                log_level, "DQ [%s] %s — %s", result.status, result.rule_name, result.message
            )
        except Exception as exc:
            error_result = DQResult(
                rule_name=getattr(rule_fn, "__name__", "unknown"),
                status="WARN",
                affected_rows=0,
                message=f"Rule check raised an exception: {exc}",
            )
            report.results.append(error_result)

    return report


def _persist_result(conn: duckdb.DuckDBPyConnection, result: DQResult) -> None:
    """Write a DQ result to the audit table."""
    conn.execute(
        "INSERT INTO audit.dq_results (dq_id, rule_name, status, affected_rows, message) "
        "VALUES (nextval('audit.dq_seq'), ?, ?, ?, ?)",
        [result.rule_name, result.status, result.affected_rows, result.message],
    )


def _require_table(
    conn: duckdb.DuckDBPyConnection, schema: str, table: str, rule_name: str
) -> DQResult | None:
    """Return a FAIL result if a table is absent, else None."""
    if not table_exists(conn, schema, table):
        return DQResult(
            rule_name=rule_name,
            status="FAIL",
            affected_rows=0,
            message=f"{schema}.{table} not found",
        )
    return None


# ── Individual rules ──────────────────────────────────────────────────────────


def _check_patients_present(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Check that standardized.patients has at least one row."""
    miss = _require_table(conn, "standardized", "patients", "patients_table_exists")
    if miss:
        return miss
    n = int(run_query(conn, "SELECT count(*) AS n FROM standardized.patients")["n"].iloc[0])
    return DQResult("patients_table_exists", "PASS" if n > 0 else "FAIL", n, f"{n} patients loaded")


def _check_encounters_present(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Check that standardized.encounters has at least one row."""
    miss = _require_table(conn, "standardized", "encounters", "encounters_table_exists")
    if miss:
        return miss
    n = int(run_query(conn, "SELECT count(*) AS n FROM standardized.encounters")["n"].iloc[0])
    return DQResult(
        "encounters_table_exists", "PASS" if n > 0 else "FAIL", n, f"{n} encounters loaded"
    )


def _check_conditions_present(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Check that standardized.conditions has at least one row."""
    miss = _require_table(conn, "standardized", "conditions", "conditions_table_exists")
    if miss:
        return miss
    n = int(run_query(conn, "SELECT count(*) AS n FROM standardized.conditions")["n"].iloc[0])
    return DQResult(
        "conditions_table_exists", "PASS" if n > 0 else "FAIL", n, f"{n} conditions loaded"
    )


def _check_medications_present(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Check that standardized.medications has at least one row."""
    miss = _require_table(conn, "standardized", "medications", "medications_table_exists")
    if miss:
        return miss
    n = int(run_query(conn, "SELECT count(*) AS n FROM standardized.medications")["n"].iloc[0])
    return DQResult(
        "medications_table_exists", "PASS" if n > 0 else "FAIL", n, f"{n} medications loaded"
    )


def _check_observations_present(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Check that standardized.observations has at least one row."""
    miss = _require_table(conn, "standardized", "observations", "observations_table_exists")
    if miss:
        return miss
    n = int(run_query(conn, "SELECT count(*) AS n FROM standardized.observations")["n"].iloc[0])
    return DQResult(
        "observations_table_exists", "PASS" if n > 0 else "FAIL", n, f"{n} observations loaded"
    )


def _check_patient_id_unique(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect duplicate patient_id values in standardized.patients."""
    miss = _require_table(conn, "standardized", "patients", "patient_id_unique")
    if miss:
        return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM (SELECT patient_id FROM standardized.patients GROUP BY patient_id HAVING count(*) > 1)",
    )
    n = int(df["n"].iloc[0])
    status = "FAIL" if n > 0 else "PASS"
    return DQResult("patient_id_unique", status, n, f"{n} duplicate patient IDs")


def _check_orphan_encounters(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect encounters with no matching patient in standardized.patients."""
    for t in ("encounters", "patients"):
        miss = _require_table(conn, "standardized", t, "orphan_encounters")
        if miss:
            return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.encounters e "
        "LEFT JOIN standardized.patients p ON e.patient_id = p.patient_id "
        "WHERE p.patient_id IS NULL",
    )
    n = int(df["n"].iloc[0])
    status = "WARN" if n > 0 else "PASS"
    return DQResult("orphan_encounters", status, n, f"{n} encounters without a matching patient")


def _check_orphan_conditions(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect conditions with no matching patient."""
    for t in ("conditions", "patients"):
        miss = _require_table(conn, "standardized", t, "orphan_conditions")
        if miss:
            return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.conditions c "
        "LEFT JOIN standardized.patients p ON c.patient_id = p.patient_id "
        "WHERE p.patient_id IS NULL",
    )
    n = int(df["n"].iloc[0])
    status = "WARN" if n > 0 else "PASS"
    return DQResult("orphan_conditions", status, n, f"{n} conditions without a matching patient")


def _check_orphan_medications(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect medication records with no matching patient."""
    for t in ("medications", "patients"):
        miss = _require_table(conn, "standardized", t, "orphan_medications")
        if miss:
            return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.medications m "
        "LEFT JOIN standardized.patients p ON m.patient_id = p.patient_id "
        "WHERE p.patient_id IS NULL",
    )
    n = int(df["n"].iloc[0])
    status = "WARN" if n > 0 else "PASS"
    return DQResult("orphan_medications", status, n, f"{n} medications without a matching patient")


def _check_encounter_stop_after_start(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect encounters where stop timestamp precedes start."""
    miss = _require_table(conn, "standardized", "encounters", "encounter_stop_after_start")
    if miss:
        return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.encounters "
        "WHERE encounter_stop IS NOT NULL AND encounter_stop < encounter_start",
    )
    n = int(df["n"].iloc[0])
    status = "FAIL" if n > 0 else "PASS"
    return DQResult(
        "encounter_stop_after_start", status, n, f"{n} encounters with stop before start"
    )


def _check_medication_stop_after_start(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect medications where stop date precedes start date."""
    miss = _require_table(conn, "standardized", "medications", "medication_stop_after_start")
    if miss:
        return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.medications "
        "WHERE medication_stop IS NOT NULL AND medication_stop < medication_start",
    )
    n = int(df["n"].iloc[0])
    status = "WARN" if n > 0 else "PASS"
    return DQResult(
        "medication_stop_after_start", status, n, f"{n} medications with stop before start"
    )


def _check_events_before_birth(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect encounters that start before the patient's birth date."""
    for t in ("encounters", "patients"):
        miss = _require_table(conn, "standardized", t, "events_before_birth")
        if miss:
            return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.encounters e "
        "JOIN standardized.patients p ON e.patient_id = p.patient_id "
        "WHERE CAST(e.encounter_start AS DATE) < p.birth_date",
    )
    n = int(df["n"].iloc[0])
    status = "FAIL" if n > 0 else "PASS"
    return DQResult("events_before_birth", status, n, f"{n} encounters before patient birth date")


def _check_events_after_death(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect encounters that start after the patient's recorded death date."""
    for t in ("encounters", "patients"):
        miss = _require_table(conn, "standardized", t, "events_after_death")
        if miss:
            return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.encounters e "
        "JOIN standardized.patients p ON e.patient_id = p.patient_id "
        "WHERE p.death_date IS NOT NULL "
        "AND CAST(e.encounter_start AS DATE) > p.death_date",
    )
    n = int(df["n"].iloc[0])
    # Synthea may produce a small number; treat as WARN not FAIL
    status = "WARN" if n > 0 else "PASS"
    return DQResult("events_after_death", status, n, f"{n} encounters after patient death date")


def _check_missing_patient_sex(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Count patients with null or blank sex field."""
    miss = _require_table(conn, "standardized", "patients", "missing_patient_sex")
    if miss:
        return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.patients WHERE sex IS NULL OR TRIM(sex) = ''",
    )
    n = int(df["n"].iloc[0])
    status = "WARN" if n > 0 else "PASS"
    return DQResult("missing_patient_sex", status, n, f"{n} patients missing sex")


def _check_missing_patient_race(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Count patients with null or blank race field."""
    miss = _require_table(conn, "standardized", "patients", "missing_patient_race")
    if miss:
        return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM standardized.patients WHERE race IS NULL OR TRIM(race) = ''",
    )
    n = int(df["n"].iloc[0])
    status = "WARN" if n > 0 else "PASS"
    return DQResult("missing_patient_race", status, n, f"{n} patients missing race")


def _check_missing_patient_birthdate(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Count patients with null birth_date (non-parseable BIRTHDATE in source)."""
    miss = _require_table(conn, "standardized", "patients", "missing_patient_birthdate")
    if miss:
        return miss
    df = run_query(conn, "SELECT count(*) AS n FROM standardized.patients WHERE birth_date IS NULL")
    n = int(df["n"].iloc[0])
    status = "FAIL" if n > 0 else "PASS"
    return DQResult("missing_patient_birthdate", status, n, f"{n} patients with null birth date")


def _check_unrecognized_encounter_classes(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect encounter_class values not in the expected vocabulary."""
    miss = _require_table(conn, "standardized", "encounters", "unrecognized_encounter_classes")
    if miss:
        return miss
    class_list = ", ".join(f"'{c}'" for c in sorted(VALID_ENCOUNTER_CLASSES))
    df = run_query(
        conn,
        f"SELECT count(*) AS n FROM standardized.encounters "
        f"WHERE encounter_class IS NOT NULL AND encounter_class NOT IN ({class_list})",
    )
    n = int(df["n"].iloc[0])
    status = "WARN" if n > 0 else "PASS"
    return DQResult(
        "unrecognized_encounter_classes", status, n, f"{n} encounters with unrecognized class"
    )


def _check_duplicate_condition_rows(conn: duckdb.DuckDBPyConnection) -> DQResult:
    """Detect exact duplicate condition rows (same patient, code, start date)."""
    miss = _require_table(conn, "standardized", "conditions", "duplicate_condition_rows")
    if miss:
        return miss
    df = run_query(
        conn,
        "SELECT count(*) AS n FROM ("
        "  SELECT patient_id, condition_code, condition_start, count(*) AS cnt "
        "  FROM standardized.conditions "
        "  GROUP BY patient_id, condition_code, condition_start "
        "  HAVING cnt > 1"
        ")",
    )
    n = int(df["n"].iloc[0])
    status = "WARN" if n > 0 else "PASS"
    return DQResult("duplicate_condition_rows", status, n, f"{n} duplicate condition entries")


# DQ sequence must be added to audit DDL — add it here if missing.
def _ensure_dq_sequence(conn: duckdb.DuckDBPyConnection) -> None:
    """Ensure the DQ sequence exists (called within ensure_audit_schema)."""
    conn.execute("CREATE SEQUENCE IF NOT EXISTS audit.dq_seq START 1")
