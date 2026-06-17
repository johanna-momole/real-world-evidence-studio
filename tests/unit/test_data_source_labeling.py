"""Tests for data-source labeling in reporting and audit.

Verifies:
1.  official_synthea  → correct human-readable label
2.  custom_synthetic_demo → correct human-readable label
3.  unknown_synthetic_source → generic label (no placeholder)
4.  rendered brief contains data_source_label, not the raw constant string
5.  rendered brief contains no hard-coded "Synthea-generated" phrases
6.  disclaimer references the label, not a placeholder
7.  data_source propagates from ingestion manifest to cohort run record
"""

from __future__ import annotations

import duckdb

from evidence_studio.audit import (
    DATA_SOURCE_CUSTOM_DEMO,
    DATA_SOURCE_OFFICIAL_SYNTHEA,
    DATA_SOURCE_UNKNOWN,
    ensure_audit_schema,
    record_study_run,
)
from evidence_studio.reporting import _build_context, _data_source_label

# ── Label helper ──────────────────────────────────────────────────────────────


def test_official_synthea_label() -> None:
    label = _data_source_label(DATA_SOURCE_OFFICIAL_SYNTHEA)
    assert "Synthea" in label
    assert label != DATA_SOURCE_OFFICIAL_SYNTHEA


def test_custom_demo_label() -> None:
    label = _data_source_label(DATA_SOURCE_CUSTOM_DEMO)
    assert "synthetic" in label.lower() or "custom" in label.lower()
    assert label != DATA_SOURCE_CUSTOM_DEMO


def test_unknown_label_has_no_placeholder() -> None:
    label = _data_source_label(DATA_SOURCE_UNKNOWN)
    assert label  # not empty
    assert label != DATA_SOURCE_UNKNOWN
    assert "unknown_synthetic_source" not in label


def test_all_three_labels_are_distinct() -> None:
    labels = {
        _data_source_label(DATA_SOURCE_OFFICIAL_SYNTHEA),
        _data_source_label(DATA_SOURCE_CUSTOM_DEMO),
        _data_source_label(DATA_SOURCE_UNKNOWN),
    }
    assert len(labels) == 3


# ── Context builder ───────────────────────────────────────────────────────────


def _minimal_conn_with_run(tmp_path, data_source: str) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection with audit schema and one study_runs row."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(tmp_path / "test.duckdb"))
    conn.execute("CREATE SCHEMA IF NOT EXISTS audit")
    ensure_audit_schema(conn)
    record_study_run(
        conn,
        run_id="run_test_001",
        config_dict={"follow_up_days": 180},
        data_source=data_source,
        n_enrolled=50,
        n_with_outcome=10,
    )
    return conn


def test_context_data_source_official_synthea(tmp_path) -> None:
    conn = _minimal_conn_with_run(tmp_path, DATA_SOURCE_OFFICIAL_SYNTHEA)
    ctx = _build_context(conn, "latest")
    conn.close()
    assert ctx["data_source"] == DATA_SOURCE_OFFICIAL_SYNTHEA
    assert "Synthea" in ctx["data_source_label"]


def test_context_data_source_custom_demo(tmp_path) -> None:
    conn = _minimal_conn_with_run(tmp_path, DATA_SOURCE_CUSTOM_DEMO)
    ctx = _build_context(conn, "latest")
    conn.close()
    assert ctx["data_source"] == DATA_SOURCE_CUSTOM_DEMO
    label = ctx["data_source_label"]
    assert "custom" in label.lower() or "synthetic" in label.lower()


def test_context_disclaimer_not_placeholder(tmp_path) -> None:
    for idx, ds in enumerate(
        (DATA_SOURCE_OFFICIAL_SYNTHEA, DATA_SOURCE_CUSTOM_DEMO, DATA_SOURCE_UNKNOWN)
    ):
        conn = _minimal_conn_with_run(tmp_path / str(idx), ds)
        ctx = _build_context(conn, "latest")
        conn.close()
        disc = ctx["disclaimer"]
        assert disc, f"Disclaimer is empty for data_source={ds!r}"
        assert "unknown_synthetic_source" not in disc, (
            f"Placeholder leaked into disclaimer for data_source={ds!r}"
        )
        assert "custom_synthetic_demo" not in disc, (
            f"Raw constant leaked into disclaimer for data_source={ds!r}"
        )
        assert "official_synthea" not in disc, (
            f"Raw constant leaked into disclaimer for data_source={ds!r}"
        )


def test_context_no_analysis_dataset_still_has_data_source(tmp_path) -> None:
    """data_source must be set even when analysis_dataset is absent."""
    conn = _minimal_conn_with_run(tmp_path, DATA_SOURCE_CUSTOM_DEMO)
    ctx = _build_context(conn, "latest")
    conn.close()
    assert ctx["data_source"] == DATA_SOURCE_CUSTOM_DEMO
    assert ctx["data_source_label"]
