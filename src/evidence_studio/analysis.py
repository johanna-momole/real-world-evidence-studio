"""Baseline feature engineering, outcome ascertainment, and descriptive statistics."""

from __future__ import annotations

import logging
from typing import Optional

import duckdb
import pandas as pd

from evidence_studio.audit import log_assumption
from evidence_studio.config import StudyConfig
from evidence_studio.database import execute_sql, run_query, table_exists

logger = logging.getLogger(__name__)


def build_analysis_dataset(
    conn: duckdb.DuckDBPyConnection,
    config: Optional[StudyConfig] = None,
) -> int:
    """Build analytics.analysis_dataset from the enrolled cohort.

    Returns the number of rows in the final analysis table.
    """
    if not table_exists(conn, "analytics", "cohort"):
        logger.warning("analytics.cohort not found — run build-cohort first.")
        return 0

    cfg = config or StudyConfig()
    follow_up_days = cfg.follow_up_days

    _build_baseline_features(conn, cfg)
    _build_outcomes(conn, follow_up_days)
    _join_analysis_dataset(conn)

    n = int(run_query(conn, "SELECT count(*) AS n FROM analytics.analysis_dataset")["n"].iloc[0])
    logger.info("analysis_dataset built: %d rows", n)
    log_assumption(
        conn,
        f"analysis_dataset built with follow_up_days={follow_up_days}. n={n}.",
        context="analysis",
    )
    return n


def _build_baseline_features(conn: duckdb.DuckDBPyConnection, cfg: StudyConfig) -> None:
    """Create analytics.baseline_features — one row per cohort patient."""
    import yaml

    from evidence_studio.config import _CONCEPT_FILE

    with _CONCEPT_FILE.open() as fh:
        defs = yaml.safe_load(fh) or {}

    baseline_days = cfg.baseline_days

    def _like_clauses(concept_key: str, col: str) -> str:
        cs = defs.get(concept_key, {})
        terms = cs.get("text_search", [])
        codes = cs.get("code_search", [])
        clauses = [f"LOWER({col}) LIKE '%{t.lower()}%'" for t in terms]
        if codes:
            code_col = col.replace("description", "code")
            clauses.append(f"{code_col} IN ({', '.join(repr(c) for c in codes)})")
        return " OR ".join(clauses) if clauses else "1=0"

    sql = f"""
    CREATE OR REPLACE TABLE analytics.baseline_features AS
    WITH co AS (SELECT * FROM analytics.cohort),

    -- Baseline encounter counts (strictly before index)
    enc_counts AS (
        SELECT
            e.patient_id,
            COUNT(*) FILTER (WHERE e.encounter_class = 'emergency')   AS bl_ed_count,
            COUNT(*) FILTER (WHERE e.encounter_class = 'inpatient')   AS bl_inpatient_count,
            COUNT(*) FILTER (
                WHERE e.encounter_class IN ('outpatient','ambulatory','wellness')
            )                                                          AS bl_outpatient_count
        FROM standardized.encounters e
        JOIN co ON e.patient_id = co.patient_id
        WHERE CAST(e.encounter_start AS DATE) < co.index_date
          AND CAST(e.encounter_start AS DATE) >= co.index_date - INTERVAL '{baseline_days} days'
        GROUP BY e.patient_id
    ),

    -- Distinct chronic conditions (ever on or before index)
    cond_counts AS (
        SELECT
            c.patient_id,
            COUNT(DISTINCT c.condition_code) AS n_conditions,
            MAX(CASE WHEN ({_like_clauses("hypertension", "c.condition_description")}) THEN 1 ELSE 0 END) AS has_hypertension,
            MAX(CASE WHEN ({_like_clauses("chronic_kidney_disease", "c.condition_description")}) THEN 1 ELSE 0 END) AS has_ckd,
            MAX(CASE WHEN ({_like_clauses("cardiovascular_disease", "c.condition_description")}) THEN 1 ELSE 0 END) AS has_cvd
        FROM standardized.conditions c
        JOIN co ON c.patient_id = co.patient_id
        WHERE c.condition_start <= co.index_date
        GROUP BY c.patient_id
    ),

    -- Active medication count in baseline window (excluding GLP-1)
    med_counts AS (
        SELECT
            m.patient_id,
            COUNT(DISTINCT m.medication_code) AS n_medications
        FROM standardized.medications m
        JOIN co ON m.patient_id = co.patient_id
        WHERE m.medication_start <= co.index_date
          AND (m.medication_stop IS NULL OR m.medication_stop >= co.index_date - INTERVAL '{baseline_days} days')
          AND NOT (
              LOWER(m.medication_description) LIKE '%semaglutide%' OR
              LOWER(m.medication_description) LIKE '%liraglutide%' OR
              LOWER(m.medication_description) LIKE '%dulaglutide%' OR
              LOWER(m.medication_description) LIKE '%exenatide%' OR
              LOWER(m.medication_description) LIKE '%tirzepatide%'
          )
        GROUP BY m.patient_id
    ),

    -- Latest baseline HbA1c
    hba1c AS (
        SELECT
            o.patient_id,
            o.value_as_number AS hba1c_pct,
            ROW_NUMBER() OVER (PARTITION BY o.patient_id ORDER BY o.observation_date DESC) AS rn
        FROM standardized.observations o
        JOIN co ON o.patient_id = co.patient_id
        WHERE o.observation_date < co.index_date
          AND o.observation_date >= co.index_date - INTERVAL '{baseline_days} days'
          AND (LOWER(o.observation_description) LIKE '%hemoglobin a1c%'
               OR LOWER(o.observation_description) LIKE '%hba1c%'
               OR o.observation_code IN ('4548-4','17856-6'))
          AND o.value_as_number IS NOT NULL
    ),

    -- Latest baseline BMI
    bmi AS (
        SELECT
            o.patient_id,
            o.value_as_number AS bmi_value,
            ROW_NUMBER() OVER (PARTITION BY o.patient_id ORDER BY o.observation_date DESC) AS rn
        FROM standardized.observations o
        JOIN co ON o.patient_id = co.patient_id
        WHERE o.observation_date < co.index_date
          AND o.observation_date >= co.index_date - INTERVAL '{baseline_days} days'
          AND (LOWER(o.observation_description) LIKE '%body mass index%'
               OR LOWER(o.observation_description) LIKE '%bmi%'
               OR o.observation_code = '39156-5')
          AND o.value_as_number IS NOT NULL
    )

    SELECT
        co.patient_id,
        co.index_date,
        co.glp1_drug,
        co.sex,
        co.race,
        co.ethnicity,
        DATEDIFF('year', co.birth_date, co.index_date)                       AS age_at_index,
        CASE
            WHEN DATEDIFF('year', co.birth_date, co.index_date) < 35 THEN '18-34'
            WHEN DATEDIFF('year', co.birth_date, co.index_date) < 50 THEN '35-49'
            WHEN DATEDIFF('year', co.birth_date, co.index_date) < 65 THEN '50-64'
            WHEN DATEDIFF('year', co.birth_date, co.index_date) < 75 THEN '65-74'
            ELSE '75+'
        END                                                                   AS age_group,
        COALESCE(enc.bl_ed_count, 0)                                          AS bl_ed_count,
        COALESCE(enc.bl_inpatient_count, 0)                                   AS bl_inpatient_count,
        COALESCE(enc.bl_outpatient_count, 0)                                  AS bl_outpatient_count,
        COALESCE(cond.n_conditions, 0)                                        AS n_conditions,
        COALESCE(med.n_medications, 0)                                        AS n_medications,
        COALESCE(cond.has_hypertension, 0)                                    AS has_hypertension,
        COALESCE(cond.has_ckd, 0)                                             AS has_ckd,
        COALESCE(cond.has_cvd, 0)                                             AS has_cvd,
        h.hba1c_pct,
        b.bmi_value
    FROM co
    LEFT JOIN enc_counts enc ON co.patient_id = enc.patient_id
    LEFT JOIN cond_counts cond ON co.patient_id = cond.patient_id
    LEFT JOIN med_counts med ON co.patient_id = med.patient_id
    LEFT JOIN (SELECT * FROM hba1c WHERE rn = 1) h ON co.patient_id = h.patient_id
    LEFT JOIN (SELECT * FROM bmi WHERE rn = 1) b ON co.patient_id = b.patient_id
    """
    execute_sql(conn, sql)
    n = int(run_query(conn, "SELECT count(*) AS n FROM analytics.baseline_features")["n"].iloc[0])
    logger.info("baseline_features: %d rows", n)


def _build_outcomes(conn: duckdb.DuckDBPyConnection, follow_up_days: int) -> None:
    """Create analytics.outcomes — one row per cohort patient with follow-up results."""
    sql = f"""
    CREATE OR REPLACE TABLE analytics.outcomes AS
    WITH co AS (SELECT * FROM analytics.cohort),

    -- Observed follow-up end (earlier of: index+follow_up, death, last encounter)
    fu_ends AS (
        SELECT
            co.patient_id,
            co.index_date,
            LEAST(
                co.index_date + INTERVAL '{follow_up_days} days',
                COALESCE(co.death_date, '9999-12-31'::DATE),
                COALESCE(
                    (SELECT MAX(CAST(e2.encounter_start AS DATE))
                     FROM standardized.encounters e2
                     WHERE e2.patient_id = co.patient_id),
                    co.index_date + INTERVAL '{follow_up_days} days'
                )
            ) AS follow_up_end
        FROM co
    ),

    -- ED encounters in follow-up window
    ed_events AS (
        SELECT
            e.patient_id,
            MIN(CAST(e.encounter_start AS DATE)) AS first_ed_date,
            COUNT(*) AS ed_count
        FROM standardized.encounters e
        JOIN fu_ends f ON e.patient_id = f.patient_id
        WHERE e.encounter_class = 'emergency'
          AND CAST(e.encounter_start AS DATE) > f.index_date
          AND CAST(e.encounter_start AS DATE) <= f.follow_up_end
        GROUP BY e.patient_id
    ),

    -- Inpatient encounters in follow-up window
    ip_events AS (
        SELECT e.patient_id, COUNT(*) AS ip_count
        FROM standardized.encounters e
        JOIN fu_ends f ON e.patient_id = f.patient_id
        WHERE e.encounter_class = 'inpatient'
          AND CAST(e.encounter_start AS DATE) > f.index_date
          AND CAST(e.encounter_start AS DATE) <= f.follow_up_end
        GROUP BY e.patient_id
    )

    SELECT
        f.patient_id,
        f.index_date,
        f.follow_up_end,
        DATEDIFF('day', f.index_date, f.follow_up_end)                     AS follow_up_days_observed,
        DATEDIFF('day', f.index_date, f.follow_up_end) / 30.4375           AS follow_up_months,
        COALESCE(ed.ed_count, 0)                                            AS fu_ed_count,
        CASE WHEN ed.ed_count > 0 THEN 1 ELSE 0 END                        AS any_ed_visit,
        DATEDIFF('day', f.index_date, ed.first_ed_date)                    AS days_to_first_ed,
        COALESCE(ip.ip_count, 0)                                            AS fu_ip_count,
        CASE WHEN ip.ip_count > 0 THEN 1 ELSE 0 END                        AS any_ip_visit
    FROM fu_ends f
    LEFT JOIN ed_events ed ON f.patient_id = ed.patient_id
    LEFT JOIN ip_events ip ON f.patient_id = ip.patient_id
    """
    execute_sql(conn, sql)
    n = int(run_query(conn, "SELECT count(*) AS n FROM analytics.outcomes")["n"].iloc[0])
    logger.info("outcomes: %d rows", n)


def _join_analysis_dataset(conn: duckdb.DuckDBPyConnection) -> None:
    """Join baseline features and outcomes into analytics.analysis_dataset."""
    sql = """
    CREATE OR REPLACE TABLE analytics.analysis_dataset AS
    SELECT bf.*, ou.follow_up_end, ou.follow_up_days_observed, ou.follow_up_months,
           ou.fu_ed_count, ou.any_ed_visit, ou.days_to_first_ed,
           ou.fu_ip_count, ou.any_ip_visit
    FROM analytics.baseline_features bf
    JOIN analytics.outcomes ou ON bf.patient_id = ou.patient_id
    """
    execute_sql(conn, sql)


# ── Descriptive summaries ─────────────────────────────────────────────────────


def characteristics_table(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return Table 1 — count/pct or mean/SD for all baseline covariates."""
    if not table_exists(conn, "analytics", "analysis_dataset"):
        return pd.DataFrame()

    n_total = int(
        run_query(conn, "SELECT count(*) AS n FROM analytics.analysis_dataset")["n"].iloc[0]
    )
    if n_total == 0:
        return pd.DataFrame()

    rows = []

    def _add_cont(label: str, col: str) -> None:
        df = run_query(
            conn,
            f"SELECT avg({col}) AS mean, stddev({col}) AS sd, "
            f"median({col}) AS median, "
            f"percentile_cont(0.25) WITHIN GROUP (ORDER BY {col}) AS q25, "
            f"percentile_cont(0.75) WITHIN GROUP (ORDER BY {col}) AS q75, "
            f"count(*) FILTER (WHERE {col} IS NULL) AS n_missing "
            f"FROM analytics.analysis_dataset",
        )
        row = df.iloc[0]
        rows.append(
            {
                "Characteristic": label,
                "N (%)  or  Mean (SD)": f"{row['mean']:.1f} ({row['sd']:.1f})",
                "Median [IQR]": f"{row['median']:.1f} [{row['q25']:.1f}–{row['q75']:.1f}]",
                "Missing": int(row["n_missing"]),
            }
        )

    def _add_cat(label: str, col: str) -> None:
        df = run_query(
            conn,
            f"SELECT {col} AS value, count(*) AS n FROM analytics.analysis_dataset "
            f"GROUP BY {col} ORDER BY n DESC",
        )
        for _, row in df.iterrows():
            pct = row["n"] / n_total * 100 if n_total > 0 else 0
            rows.append(
                {
                    "Characteristic": f"  {label} — {row['value']}",
                    "N (%)  or  Mean (SD)": f"{int(row['n'])} ({pct:.1f}%)",
                    "Median [IQR]": "",
                    "Missing": 0,
                }
            )

    def _add_bin(label: str, col: str) -> None:
        df = run_query(conn, f"SELECT sum({col}) AS n FROM analytics.analysis_dataset")
        n = int(df["n"].iloc[0] or 0)
        pct = n / n_total * 100
        rows.append(
            {
                "Characteristic": label,
                "N (%)  or  Mean (SD)": f"{n} ({pct:.1f}%)",
                "Median [IQR]": "",
                "Missing": 0,
            }
        )

    rows.append(
        {
            "Characteristic": f"Total enrolled (n = {n_total})",
            "N (%)  or  Mean (SD)": "",
            "Median [IQR]": "",
            "Missing": 0,
        }
    )

    _add_cont("Age at index (years)", "age_at_index")
    _add_cat("Age group", "age_group")
    _add_cat("Sex", "sex")
    _add_cat("Race", "race")
    _add_cat("Ethnicity", "ethnicity")
    _add_cat("GLP-1 drug initiated", "glp1_drug")
    _add_cont("Baseline ED encounters", "bl_ed_count")
    _add_cont("Baseline inpatient encounters", "bl_inpatient_count")
    _add_cont("Baseline outpatient encounters", "bl_outpatient_count")
    _add_cont("Number of distinct conditions", "n_conditions")
    _add_cont("Number of active medications", "n_medications")
    _add_bin("Hypertension", "has_hypertension")
    _add_bin("Chronic kidney disease", "has_ckd")
    _add_bin("Cardiovascular disease", "has_cvd")
    _add_cont("Latest baseline HbA1c (%)", "hba1c_pct")
    _add_cont("Latest baseline BMI (kg/m²)", "bmi_value")

    return pd.DataFrame(rows)


def outcome_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return outcome counts, rates, and person-time."""
    if not table_exists(conn, "analytics", "analysis_dataset"):
        return pd.DataFrame()

    sql = """
    SELECT
        count(*) AS n_patients,
        sum(any_ed_visit) AS n_any_ed,
        round(sum(any_ed_visit) * 100.0 / count(*), 1) AS pct_any_ed,
        sum(fu_ed_count) AS total_ed_encounters,
        round(sum(fu_ed_count) * 100.0 / NULLIF(sum(follow_up_months), 0), 1) AS ed_per_100_person_months,
        sum(any_ip_visit) AS n_any_ip,
        round(sum(any_ip_visit) * 100.0 / count(*), 1) AS pct_any_ip,
        round(avg(follow_up_days_observed), 1) AS mean_follow_up_days
    FROM analytics.analysis_dataset
    """
    return run_query(conn, sql)


def subgroup_summary(conn: duckdb.DuckDBPyConnection, by: str = "age_group") -> pd.DataFrame:
    """Return unadjusted ED rate stratified by a single covariate."""
    allowed = {
        "age_group",
        "sex",
        "race",
        "ethnicity",
        "has_hypertension",
        "has_ckd",
        "has_cvd",
        "glp1_drug",
    }
    if by not in allowed:
        raise ValueError(f"Subgroup column '{by}' is not in the allowed set: {allowed}")

    if not table_exists(conn, "analytics", "analysis_dataset"):
        return pd.DataFrame()

    sql = f"""
    SELECT
        {by} AS subgroup_value,
        count(*) AS n,
        sum(any_ed_visit) AS n_ed,
        round(sum(any_ed_visit) * 100.0 / count(*), 1) AS pct_ed,
        round(sum(fu_ed_count) * 100.0 / NULLIF(sum(follow_up_months), 0), 1) AS ed_per_100_pm
    FROM analytics.analysis_dataset
    GROUP BY {by}
    ORDER BY pct_ed DESC
    """
    return run_query(conn, sql)


def missingness_summary(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return percent missing for each covariate in the analysis dataset."""
    if not table_exists(conn, "analytics", "analysis_dataset"):
        return pd.DataFrame()

    cols = [
        "age_at_index",
        "sex",
        "race",
        "ethnicity",
        "bl_ed_count",
        "bl_inpatient_count",
        "bl_outpatient_count",
        "n_conditions",
        "n_medications",
        "has_hypertension",
        "has_ckd",
        "has_cvd",
        "hba1c_pct",
        "bmi_value",
    ]
    n_total = int(
        run_query(conn, "SELECT count(*) AS n FROM analytics.analysis_dataset")["n"].iloc[0]
    )
    if n_total == 0:
        return pd.DataFrame()

    rows = []
    for col in cols:
        n_miss_df = run_query(
            conn, f"SELECT count(*) AS n FROM analytics.analysis_dataset WHERE {col} IS NULL"
        )
        n_miss = int(n_miss_df["n"].iloc[0])
        pct = round(n_miss / n_total * 100, 1)
        rows.append(
            {
                "Variable": col,
                "N missing": n_miss,
                "% missing": pct,
                "Flag": "HIGH" if pct > 20 else "",
            }
        )
    return pd.DataFrame(rows)
