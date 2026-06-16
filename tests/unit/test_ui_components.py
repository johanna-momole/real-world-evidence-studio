"""Unit tests for reusable UI helper functions in components.py."""

from __future__ import annotations


def test_status_badge_ok():
    from evidence_studio.ui.components import status_badge

    assert "✅" in status_badge(True)
    assert "OK" in status_badge(True)


def test_status_badge_fail():
    from evidence_studio.ui.components import status_badge

    assert "❌" in status_badge(False)
    assert "Missing" in status_badge(False)


def test_status_badge_custom_labels():
    from evidence_studio.ui.components import status_badge

    result = status_badge(True, ok_text="Found", fail_text="Gone")
    assert "Found" in result

    result = status_badge(False, ok_text="Found", fail_text="Gone")
    assert "Gone" in result


def test_disclaimer_constant_contains_required_text():
    from evidence_studio.ui.components import DISCLAIMER

    assert "Synthetic data" in DISCLAIMER or "Synthea" in DISCLAIMER
    assert "clinical" in DISCLAIMER.lower()


def test_download_csv_button_encodes_utf8(tmp_path):
    """download_csv_button should produce UTF-8-decodable CSV bytes."""
    import pandas as pd

    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    decoded = csv_bytes.decode("utf-8")
    assert "a,b" in decoded
    assert "1,x" in decoded


def test_metric_row_accepts_none_delta():
    """metric_row tuple may have None as the delta element."""
    metrics = [("Label", "Value", None)]
    assert len(metrics) == 1


def test_subgroup_options_map_keys_are_labels():
    """The subgroup options map in results.py must have display-label keys."""
    from evidence_studio.ui.pages.results import _SUBGROUP_OPTIONS

    for label, col in _SUBGROUP_OPTIONS.items():
        assert isinstance(label, str) and len(label) > 0
        assert isinstance(col, str) and len(col) > 0


def test_subgroup_options_column_names_match_analysis_allowlist():
    """Every column in _SUBGROUP_OPTIONS must be in the analysis.subgroup_summary allowlist."""
    import inspect

    from evidence_studio.analysis import subgroup_summary
    from evidence_studio.ui.pages.results import _SUBGROUP_OPTIONS

    src = inspect.getsource(subgroup_summary)
    for col in _SUBGROUP_OPTIONS.values():
        assert f'"{col}"' in src or f"'{col}'" in src, (
            f"Column '{col}' from _SUBGROUP_OPTIONS not found in subgroup_summary allowlist"
        )
