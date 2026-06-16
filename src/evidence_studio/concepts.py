"""Concept-set matching against loaded Synthea data."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from evidence_studio.database import run_query, table_exists

logger = logging.getLogger(__name__)

_CONCEPT_FILE = Path(__file__).resolve().parents[2] / "config" / "concept_sets.yml"


def _load_concept_sets() -> dict:
    """Load concept set definitions from the YAML config file."""
    if not _CONCEPT_FILE.exists():
        logger.warning("Concept set file not found: %s", _CONCEPT_FILE)
        return {}
    with _CONCEPT_FILE.open() as fh:
        return yaml.safe_load(fh) or {}


class ConceptMatcher:
    """Matches concept-set definitions against standardized clinical tables."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn
        self._defs = _load_concept_sets()

    def match_glp1_medications(self) -> pd.DataFrame:
        """Return distinct medication descriptions matching any GLP-1 search term."""
        if not table_exists(self._conn, "standardized", "medications"):
            return pd.DataFrame()

        cs = self._defs.get("glp1_medications", {})
        terms = cs.get("text_search", [])
        if not terms:
            return pd.DataFrame()

        condition = " OR ".join(f"medication_description LIKE '%{t.lower()}%'" for t in terms)
        sql = (
            f"SELECT "
            f"  medication_description AS source_description, "
            f"  medication_code AS source_code, "
            f"  'glp1_medications' AS concept_set, "
            f"  'text_search' AS match_method, "
            f"  count(DISTINCT patient_id) AS n_patients, "
            f"  count(*) AS n_records "
            f"FROM standardized.medications "
            f"WHERE {condition} "
            f"GROUP BY medication_description, medication_code "
            f"ORDER BY n_patients DESC"
        )
        df = run_query(self._conn, sql)
        logger.info("GLP-1 concept match: %d distinct descriptions", len(df))
        return df

    def match_conditions(self, concept_key: str) -> pd.DataFrame:
        """Return distinct condition descriptions matching the given concept set."""
        if not table_exists(self._conn, "standardized", "conditions"):
            return pd.DataFrame()

        cs = self._defs.get(concept_key, {})
        terms = cs.get("text_search", [])
        codes = cs.get("code_search", [])

        if not terms and not codes:
            return pd.DataFrame()

        clauses = []
        if terms:
            for t in terms:
                clauses.append(f"condition_description LIKE '%{t.lower()}%'")
        if codes:
            code_list = ", ".join(f"'{c}'" for c in codes)
            clauses.append(f"condition_code IN ({code_list})")

        condition = " OR ".join(clauses)
        sql = (
            f"SELECT "
            f"  condition_description AS source_description, "
            f"  condition_code AS source_code, "
            f"  '{concept_key}' AS concept_set, "
            f"  'text_or_code_search' AS match_method, "
            f"  count(DISTINCT patient_id) AS n_patients, "
            f"  count(*) AS n_records "
            f"FROM standardized.conditions "
            f"WHERE {condition} "
            f"GROUP BY condition_description, condition_code "
            f"ORDER BY n_patients DESC"
        )
        df = run_query(self._conn, sql)
        logger.info("Concept match [%s]: %d distinct descriptions", concept_key, len(df))
        return df

    def match_observations(self, concept_key: str) -> pd.DataFrame:
        """Return distinct observation descriptions matching the given concept set."""
        if not table_exists(self._conn, "standardized", "observations"):
            return pd.DataFrame()

        cs = self._defs.get(concept_key, {})
        terms = cs.get("text_search", [])
        codes = cs.get("code_search", [])

        if not terms and not codes:
            return pd.DataFrame()

        clauses = []
        if terms:
            for t in terms:
                clauses.append(f"observation_description LIKE '%{t.lower()}%'")
        if codes:
            code_list = ", ".join(f"'{c}'" for c in codes)
            clauses.append(f"observation_code IN ({code_list})")

        condition = " OR ".join(clauses)
        sql = (
            f"SELECT "
            f"  observation_description AS source_description, "
            f"  observation_code AS source_code, "
            f"  '{concept_key}' AS concept_set, "
            f"  'text_or_code_search' AS match_method, "
            f"  count(DISTINCT patient_id) AS n_patients, "
            f"  count(*) AS n_records "
            f"FROM standardized.observations "
            f"WHERE {condition} "
            f"GROUP BY observation_description, observation_code "
            f"ORDER BY n_patients DESC"
        )
        return run_query(self._conn, sql)

    def glp1_patient_ids(self) -> list:
        """Return list of patient_ids with at least one GLP-1 medication record."""
        df = self.match_glp1_medications()
        if df.empty:
            return []
        cs = self._defs.get("glp1_medications", {})
        terms = cs.get("text_search", [])
        if not terms:
            return []
        condition = " OR ".join(f"medication_description LIKE '%{t.lower()}%'" for t in terms)
        sql = f"SELECT DISTINCT patient_id FROM standardized.medications WHERE {condition}"
        result = run_query(self._conn, sql)
        return result["patient_id"].tolist()
