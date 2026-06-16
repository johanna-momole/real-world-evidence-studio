"""GLP-1 cohort builder — index events, attrition cascade, baseline eligibility."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

import duckdb

from evidence_studio.audit import (
    ensure_audit_schema,
    log_assumption,
    log_sql,
    record_attrition_step,
    record_study_run,
)
from evidence_studio.config import StudyConfig
from evidence_studio.database import execute_sql, run_query

logger = logging.getLogger(__name__)


def _run_id(config: StudyConfig) -> str:
    """Derive a deterministic run ID from config + current UTC timestamp (minute precision)."""
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    payload = json.dumps(config.to_dict(), sort_keys=True) + now
    return "run_" + hashlib.sha256(payload.encode()).hexdigest()[:12]


class CohortBuilder:
    """Builds the GLP-1 new-user cohort and records full provenance."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, config: StudyConfig) -> None:
        self._conn = conn
        self._cfg = config

    def build(self) -> str:
        """Execute the cohort build cascade and return the run ID."""
        ensure_audit_schema(self._conn)
        run_id = _run_id(self._cfg)
        step = 0

        def attrition(label: str, remaining: int, removed: int) -> None:
            nonlocal step
            step += 1
            record_attrition_step(self._conn, run_id, step, label, remaining, removed)
            logger.info(
                "ATTRITION step %d [%s]: %d remaining, %d removed", step, label, remaining, removed
            )

        log_assumption(
            self._conn,
            f"Cohort build started. Config: {json.dumps(self._cfg.to_dict())}",
            context="cohort_build",
        )

        # ── Step 0: All patients with GLP-1 records ──────────────────────────
        n_all_patients = self._count("standardized.patients")
        if n_all_patients == 0:
            log_assumption(
                self._conn,
                "No patients found. Ingestion may be incomplete.",
                context="cohort_build",
            )
            record_study_run(self._conn, run_id, self._cfg.to_dict(), "", "", 0, 0)
            return run_id

        sql_index = self._build_index_events()
        log_sql(self._conn, f"[{run_id}] index_events", sql_index)
        execute_sql(self._conn, sql_index)

        n_with_glp1 = self._count("analytics.glp1_index_events")
        if n_with_glp1 == 0:
            log_assumption(
                self._conn,
                "No GLP-1 medication records matched any concept-set term. "
                "Cohort is empty. Check your Synthea population size and concept_sets.yml.",
                context="cohort_build",
            )
            attrition("GLP-1 medication found", 0, n_all_patients)
            record_study_run(self._conn, run_id, self._cfg.to_dict(), "", "", 0, 0)
            return run_id

        attrition("GLP-1 medication found", n_with_glp1, n_all_patients - n_with_glp1)

        # ── Apply inclusion cascade ───────────────────────────────────────────
        sql_base = self._build_base_cohort()
        log_sql(self._conn, f"[{run_id}] base_cohort", sql_base)
        execute_sql(self._conn, sql_base)

        n_base = self._count("analytics._cohort_work")
        removed = n_with_glp1 - n_base
        attrition("T2DM evidence on or before index date", n_base, removed)

        n_adult = self._apply_age_filter()
        removed = n_base - n_adult
        attrition(f"Age >= {self._cfg.min_age_at_index} at index date", n_adult, removed)

        n_baseline = self._apply_baseline_filter()
        removed = n_adult - n_baseline
        attrition(f">= {self._cfg.baseline_days} days of history before index", n_baseline, removed)

        n_followup = self._apply_followup_filter()
        removed = n_baseline - n_followup
        attrition(
            f">= {self._cfg.min_follow_up_days} days of follow-up after index", n_followup, removed
        )

        # ── Configurable exclusions ───────────────────────────────────────────
        n_after_excl = n_followup

        if self._cfg.exclude_type1_diabetes:
            n_after_excl = self._apply_exclusion("type1_diabetes", n_after_excl)
            attrition("Exclude type 1 diabetes", n_after_excl, n_followup - n_after_excl)
            n_followup = n_after_excl

        if self._cfg.exclude_gestational_diabetes:
            n_prev = n_after_excl
            n_after_excl = self._apply_exclusion("gestational_diabetes", n_after_excl)
            attrition("Exclude gestational diabetes", n_after_excl, n_prev - n_after_excl)
            n_followup = n_after_excl

        if self._cfg.exclude_pregnancy_at_index:
            n_prev = n_after_excl
            n_after_excl = self._apply_exclusion("pregnancy", n_after_excl)
            attrition(
                "Exclude pregnancy overlapping index date", n_after_excl, n_prev - n_after_excl
            )

        n_enrolled = self._count("analytics._cohort_work")

        # ── Finalise cohort ───────────────────────────────────────────────────
        sql_final = (
            "CREATE OR REPLACE TABLE analytics.cohort AS SELECT * FROM analytics._cohort_work"
        )
        execute_sql(self._conn, sql_final)
        log_sql(self._conn, f"[{run_id}] final_cohort", sql_final)

        attrition("Final enrolled cohort", n_enrolled, 0)

        record_study_run(
            self._conn,
            run_id,
            self._cfg.to_dict(),
            synthea_dir="",
            db_path="",
            n_enrolled=n_enrolled,
        )

        logger.info("Cohort build complete. Run ID: %s, Enrolled: %d", run_id, n_enrolled)
        return run_id

    # ── SQL builders ──────────────────────────────────────────────────────────

    def _build_index_events(self) -> str:
        """SQL: first GLP-1 medication start per patient."""
        import yaml

        from evidence_studio.config import _CONCEPT_FILE

        concept_file = _CONCEPT_FILE
        with concept_file.open() as fh:
            defs = yaml.safe_load(fh) or {}

        terms = defs.get("glp1_medications", {}).get("text_search", [])
        if not terms:
            terms = ["semaglutide", "liraglutide", "dulaglutide", "exenatide", "tirzepatide"]

        like_clauses = " OR ".join(
            f"LOWER(medication_description) LIKE '%{t.lower()}%'" for t in terms
        )
        return f"""
        CREATE OR REPLACE TABLE analytics.glp1_index_events AS
        SELECT
            patient_id,
            MIN(medication_start)                                                AS index_date,
            FIRST(medication_description ORDER BY medication_start, medication_description) AS glp1_drug,
            FIRST(medication_code ORDER BY medication_start, medication_code)    AS glp1_code
        FROM standardized.medications
        WHERE ({like_clauses})
          AND medication_start IS NOT NULL
        GROUP BY patient_id
        """

    def _build_base_cohort(self) -> str:
        """SQL: join index events to T2DM-eligible patients."""
        import yaml

        from evidence_studio.config import _CONCEPT_FILE

        with _CONCEPT_FILE.open() as fh:
            defs = yaml.safe_load(fh) or {}

        t2dm = defs.get("type2_diabetes", {})
        terms = t2dm.get("text_search", [])
        codes = t2dm.get("code_search", [])

        clauses = []
        for t in terms:
            clauses.append(f"LOWER(c.condition_description) LIKE '%{t.lower()}%'")
        if codes:
            code_list = ", ".join(f"'{c}'" for c in codes)
            clauses.append(f"c.condition_code IN ({code_list})")

        t2dm_condition = " OR ".join(clauses) if clauses else "1=1"

        return f"""
        CREATE OR REPLACE TABLE analytics._cohort_work AS
        SELECT
            idx.patient_id,
            idx.index_date,
            idx.glp1_drug,
            idx.glp1_code,
            p.birth_date,
            p.death_date,
            p.sex,
            p.race,
            p.ethnicity
        FROM analytics.glp1_index_events idx
        JOIN standardized.patients p ON idx.patient_id = p.patient_id
        WHERE EXISTS (
            SELECT 1 FROM standardized.conditions c
            WHERE c.patient_id = idx.patient_id
              AND c.condition_start <= idx.index_date
              AND ({t2dm_condition})
        )
        """

    def _apply_age_filter(self) -> int:
        """Keep only patients aged >= min_age_at_index on the index date."""
        min_age = self._cfg.min_age_at_index
        sql = (
            f"DELETE FROM analytics._cohort_work "
            f"WHERE datediff('year', birth_date, index_date) < {min_age}"
        )
        execute_sql(self._conn, sql)
        return self._count("analytics._cohort_work")

    def _apply_baseline_filter(self) -> int:
        """Keep only patients with >= baseline_days of history before index."""
        days = self._cfg.baseline_days
        sql = (
            f"DELETE FROM analytics._cohort_work w "
            f"WHERE NOT EXISTS ("
            f"  SELECT 1 FROM standardized.encounters e "
            f"  WHERE e.patient_id = w.patient_id "
            f"    AND CAST(e.encounter_start AS DATE) <= w.index_date - INTERVAL '{days} days'"
            f")"
        )
        execute_sql(self._conn, sql)
        return self._count("analytics._cohort_work")

    def _apply_followup_filter(self) -> int:
        """Keep only patients with >= follow-up days after index (or until death)."""
        min_days = self._cfg.min_follow_up_days
        sql = (
            f"DELETE FROM analytics._cohort_work w "
            f"WHERE NOT EXISTS ("
            f"  SELECT 1 FROM standardized.encounters e "
            f"  WHERE e.patient_id = w.patient_id "
            f"    AND CAST(e.encounter_start AS DATE) >= w.index_date + INTERVAL '{min_days} days'"
            f"  UNION ALL"
            f"  SELECT 1 FROM standardized.patients p "
            f"  WHERE p.patient_id = w.patient_id "
            f"    AND p.death_date IS NOT NULL "
            f"    AND p.death_date >= w.index_date + INTERVAL '{min_days} days'"
            f")"
        )
        execute_sql(self._conn, sql)
        return self._count("analytics._cohort_work")

    def _apply_exclusion(self, concept_key: str, current_n: int) -> int:
        """Remove patients with the given exclusion concept recorded on/before index."""
        import yaml

        from evidence_studio.config import _CONCEPT_FILE

        with _CONCEPT_FILE.open() as fh:
            defs = yaml.safe_load(fh) or {}

        cs = defs.get(concept_key, {})
        terms = cs.get("text_search", [])
        codes = cs.get("code_search", [])

        if not terms and not codes:
            logger.warning("No concept definitions found for exclusion: %s", concept_key)
            return current_n

        clauses = []
        for t in terms:
            clauses.append(f"LOWER(c.condition_description) LIKE '%{t.lower()}%'")
        if codes:
            code_list = ", ".join(f"'{c}'" for c in codes)
            clauses.append(f"c.condition_code IN ({code_list})")

        # For pregnancy, use a ±30-day window around index; for others use on/before
        if concept_key == "pregnancy":
            date_filter = (
                "c.condition_start <= w.index_date + INTERVAL '30 days' "
                "AND (c.condition_stop IS NULL OR c.condition_stop >= w.index_date - INTERVAL '30 days')"
            )
        else:
            date_filter = "c.condition_start <= w.index_date"

        condition = " OR ".join(clauses)
        sql = (
            f"DELETE FROM analytics._cohort_work w "
            f"WHERE EXISTS ("
            f"  SELECT 1 FROM standardized.conditions c "
            f"  WHERE c.patient_id = w.patient_id "
            f"    AND ({condition}) "
            f"    AND {date_filter}"
            f")"
        )
        execute_sql(self._conn, sql)
        return self._count("analytics._cohort_work")

    def _count(self, table: str) -> int:
        """Return row count of a fully-qualified table."""
        df = run_query(self._conn, f"SELECT count(*) AS n FROM {table}")
        return int(df["n"].iloc[0])
