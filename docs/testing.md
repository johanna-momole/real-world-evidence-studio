# Testing Strategy

This document describes the test suite for the Real-World Evidence Studio.

---

## Overview

All tests live in `tests/`. Unit tests use `pytest` with tiny synthetic CSV fixtures
committed under `tests/fixtures/`. No full Synthea datasets or DuckDB files are
committed to the repository.

The test suite is designed to verify:
1. Data ingestion correctness and idempotency
2. Cohort construction rule integrity
3. Analysis function behavior on empty and populated data
4. Evidence-brief rendering completeness and fallback safety
5. UI helper function contracts
6. SQL injection safety via parameterized queries

---

## Test files

| File | Category | What it covers |
|------|----------|----------------|
| `tests/unit/test_config.py` | Unit | AppConfig / StudyConfig validation, YAML loading |
| `tests/unit/test_ingestion.py` | Unit | Happy-path ingest: manifest rows, SHA-256, row counts |
| `tests/unit/test_ingestion_edge_cases.py` | Unit | Missing files, missing directory, duplicate IDs, orphan FK, date parsing, encounter start ≤ stop, idempotent ingest |
| `tests/unit/test_cohort.py` | Unit | CohortBuilder happy path, run ID recorded in audit |
| `tests/unit/test_cohort_boundaries.py` | Unit | Index date = first GLP-1 med, no post-index baseline leakage, follow-up window ≥ index, non-negative counts, any_ed_visit consistency, one row per patient, reproducible run ID, T2DM required, positive person-time |
| `tests/unit/test_analysis.py` | Unit | characteristics_table, outcome_summary, subgroup_summary, missingness_summary on fixture data |
| `tests/unit/test_analysis_edge_cases.py` | Unit | Empty-DB graceful returns, attrition arithmetic, idempotent build, concept-set case-insensitivity, regression returns RegressionResult, SQL injection safety |
| `tests/unit/test_concepts.py` | Unit | Concept-set YAML loading, GLP-1 term list completeness |
| `tests/unit/test_reporting.py` | Unit | render_brief returns string, contains disclaimer and run ID, HTML format, empty-DB fallback, no fabricated numbers, _fallback_brief |
| `tests/unit/test_ui_components.py` | Unit | status_badge, DISCLAIMER constant, metric_row, subgroup column name mapping |

---

## Fixtures

`tests/fixtures/` contains minimal synthetic CSV files that mimic the Synthea output
schema. They are hand-crafted to include:

- At least one patient with T2DM + a GLP-1 medication
- At least one ED encounter in the follow-up window
- Enough observation history to clear the 365-day baseline requirement
- Edge cases: duplicate IDs are deliberately absent (tests verify uniqueness)

Fixture files: `patients.csv`, `encounters.csv`, `conditions.csv`,
`medications.csv`, `observations.csv`.

---

## Running tests

```bash
# All tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# Single file
pytest tests/unit/test_cohort_boundaries.py -v

# With coverage (if pytest-cov is installed)
pytest tests/ --cov=evidence_studio --cov-report=term-missing
```

---

## CI pipeline

`.github/workflows/ci.yml` runs on every push and pull request to `main`:

1. **Lint** — `ruff check .`
2. **Format** — `ruff format --check .`
3. **Tests** — `pytest tests/ -v --tb=short`
4. **Type hints** *(non-blocking)* — `pyright src/`

The `test` job uses only `tests/fixtures/` data. No Synthea downloads occur during CI.

---

## Design principles

**No mocking of DuckDB.** Tests use real in-memory or `tmp_path` DuckDB connections
built from fixture CSVs. This catches SQL dialect issues that mocks would hide.

**Empty-DB tests are mandatory.** Every analysis function must be tested against a
database that has schemas but no cohort rows. The app must never crash when a user
visits a page before running a study.

**Parameterized SQL only.** `test_sql_parameter_handling_no_injection` verifies that
passing SQL-metacharacter strings as query parameters is handled safely.

**No fabricated assertions.** Tests assert on values derived from the fixture data
itself (e.g., row counts queried from DuckDB), not on hardcoded expected numbers
that could drift out of sync with the fixtures.

**Idempotency.** Both `ingest` and `build_analysis_dataset` are tested for
idempotency — running twice must not change the output.

---

## Adding tests

When adding a new feature:

1. Add fixture rows if the feature needs data not already represented.
2. Add a test that exercises the feature with data present.
3. Add a test that exercises the feature with an empty database (if applicable).
4. Run `ruff check .` and `ruff format --check .` before committing.

---

## Known gaps and future work

- Integration tests that run the full CLI pipeline end-to-end (`evidence-studio ingest → analyze → brief`)
- Property-based tests with `hypothesis` for date arithmetic in cohort windows
- Snapshot tests for the evidence-brief template output
- Performance benchmarks on large fixture sets (10 k+ patients)
