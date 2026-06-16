"""Tests for concept-set matching."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture()
def matched_conn(tmp_path: Path):
    """Ingest fixture data and return an open connection."""
    from evidence_studio.audit import ensure_audit_schema
    from evidence_studio.database import get_connection
    from evidence_studio.ingestion import build_standardized, ingest

    conn = get_connection(tmp_path / "test.duckdb")
    ensure_audit_schema(conn)
    ingest(conn, FIXTURES)
    build_standardized(conn)
    yield conn
    conn.close()


def test_glp1_match_finds_semaglutide(matched_conn) -> None:
    """GLP-1 matcher should find semaglutide in fixture medications."""
    from evidence_studio.concepts import ConceptMatcher

    matcher = ConceptMatcher(matched_conn)
    df = matcher.match_glp1_medications()
    assert not df.empty
    descs = " ".join(df["source_description"].str.lower())
    assert "semaglutide" in descs


def test_glp1_match_finds_dulaglutide(matched_conn) -> None:
    """GLP-1 matcher should find dulaglutide in fixture medications."""
    from evidence_studio.concepts import ConceptMatcher

    matcher = ConceptMatcher(matched_conn)
    df = matcher.match_glp1_medications()
    descs = " ".join(df["source_description"].str.lower())
    assert "dulaglutide" in descs


def test_glp1_match_patient_count(matched_conn) -> None:
    """GLP-1 match should show ≥1 patient per matched drug."""
    from evidence_studio.concepts import ConceptMatcher

    matcher = ConceptMatcher(matched_conn)
    df = matcher.match_glp1_medications()
    assert (df["n_patients"] >= 1).all()


def test_t2dm_match_finds_conditions(matched_conn) -> None:
    """Type 2 diabetes matcher should find conditions in fixture data."""
    from evidence_studio.concepts import ConceptMatcher

    matcher = ConceptMatcher(matched_conn)
    df = matcher.match_conditions("type2_diabetes")
    assert not df.empty
    assert df["n_patients"].sum() >= 1


def test_t1dm_exclusion_match(matched_conn) -> None:
    """Type 1 diabetes matcher should find pt-0005 in fixture data."""
    from evidence_studio.concepts import ConceptMatcher

    matcher = ConceptMatcher(matched_conn)
    df = matcher.match_conditions("type1_diabetes")
    assert not df.empty
    assert df["n_patients"].sum() >= 1


def test_empty_concept_key_returns_empty(matched_conn) -> None:
    """Requesting a non-existent concept key should return an empty DataFrame."""
    from evidence_studio.concepts import ConceptMatcher

    matcher = ConceptMatcher(matched_conn)
    df = matcher.match_conditions("nonexistent_concept_key_xyz")
    assert df.empty


def test_glp1_patient_ids_non_empty(matched_conn) -> None:
    """glp1_patient_ids() should return at least one patient ID."""
    from evidence_studio.concepts import ConceptMatcher

    matcher = ConceptMatcher(matched_conn)
    ids = matcher.glp1_patient_ids()
    assert len(ids) >= 1


def test_no_data_returns_empty(tmp_path: Path) -> None:
    """ConceptMatcher should return empty DataFrames when standardized tables are absent."""
    from evidence_studio.concepts import ConceptMatcher
    from evidence_studio.database import get_connection

    conn = get_connection(tmp_path / "empty.duckdb")
    matcher = ConceptMatcher(conn)
    assert matcher.match_glp1_medications().empty
    assert matcher.match_conditions("type2_diabetes").empty
    conn.close()
