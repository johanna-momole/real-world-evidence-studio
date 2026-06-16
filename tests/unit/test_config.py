"""Unit tests for config.py — health checks that validate paths and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

import evidence_studio


def test_package_importable() -> None:
    """Package should be importable after installation."""
    assert evidence_studio.__version__ == "0.1.0"


def test_study_config_defaults() -> None:
    """StudyConfig should load with expected defaults from YAML."""
    from evidence_studio.config import StudyConfig

    cfg = StudyConfig.from_yaml()
    assert cfg.follow_up_days == 180
    assert cfg.baseline_days == 365
    assert cfg.min_age_at_index == 18
    assert cfg.exclude_type1_diabetes is True
    assert cfg.exclude_gestational_diabetes is True
    assert cfg.exclude_pregnancy_at_index is True
    assert cfg.exclude_missing_demographics is False


def test_study_config_follow_up_validation() -> None:
    """StudyConfig should reject invalid follow_up_days values."""
    from pydantic import ValidationError

    from evidence_studio.config import StudyConfig

    with pytest.raises(ValidationError):
        StudyConfig(follow_up_days=60)


def test_study_config_serialisable() -> None:
    """StudyConfig.to_dict() must return a plain dict with no Path objects."""
    from evidence_studio.config import StudyConfig

    cfg = StudyConfig()
    d = cfg.to_dict()
    assert isinstance(d, dict)
    assert "follow_up_days" in d
    assert all(not isinstance(v, Path) for v in d.values())


def test_app_config_paths_resolved() -> None:
    """AppConfig resolved paths must be absolute Path objects."""
    from evidence_studio.config import AppConfig

    cfg = AppConfig()
    assert cfg.resolved_synthea_dir.is_absolute()
    assert cfg.resolved_db_path.is_absolute()


def test_app_config_required_files_dict() -> None:
    """required_files_present must return a dict keyed by the five source table names."""
    from evidence_studio.config import AppConfig

    cfg = AppConfig()
    files = cfg.required_files_present
    assert set(files.keys()) == {
        "patients",
        "encounters",
        "conditions",
        "medications",
        "observations",
    }
    assert all(isinstance(v, bool) for v in files.values())


def test_database_get_connection_creates_db(tmp_path: Path) -> None:
    """get_connection should create the database file and initialise schemas."""
    from evidence_studio.database import get_connection, run_query

    db_path = tmp_path / "test.duckdb"
    conn = get_connection(db_path)
    assert db_path.exists()

    schemas = run_query(conn, "SELECT schema_name FROM information_schema.schemata")
    schema_names = schemas["schema_name"].tolist()
    for expected in ("raw", "standardized", "analytics", "omop", "audit"):
        assert expected in schema_names, f"Schema '{expected}' not found"

    conn.close()


def test_database_run_query_returns_dataframe(tmp_path: Path) -> None:
    """run_query should return a pandas DataFrame."""
    import pandas as pd

    from evidence_studio.database import get_connection, run_query

    conn = get_connection(tmp_path / "test.duckdb")
    df = run_query(conn, "SELECT 1 AS n")
    assert isinstance(df, pd.DataFrame)
    assert df["n"].iloc[0] == 1
    conn.close()


def test_database_table_exists_false(tmp_path: Path) -> None:
    """table_exists should return False for a non-existent table."""
    from evidence_studio.database import get_connection, table_exists

    conn = get_connection(tmp_path / "test.duckdb")
    assert not table_exists(conn, "raw", "nonexistent_table")
    conn.close()
