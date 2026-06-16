# Architecture — Real-World Evidence Studio

## Overview

The RWE Studio is a single-machine, file-backed application. DuckDB acts as
both the ETL target and the analytical engine. Streamlit renders the
interactive interface. All data transformations are expressed in SQL and
executed inside DuckDB; Python is used only for orchestration, statistical
modelling, and rendering.

---

## High-level data flow

```
Synthea CSV files
      │
      ▼
 ┌──────────────────────────────────────────────────────┐
 │  src/evidence_studio/ingestion.py                    │
 │  • Validate file presence and column schemas         │
 │  • Load CSVs into DuckDB raw schema (read_csv_auto)  │
 │  • Write manifest and row-count records to audit     │
 └──────────────────────────────────────────────────────┘
      │
      ▼
 ┌──────────────────────────────────────────────────────┐
 │  sql/standardized/  (executed by database.py)        │
 │  • Clean and cast date columns                       │
 │  • Normalize field names to snake_case               │
 │  • Validate patient/encounter foreign keys           │
 │  • Build reusable clinical helper tables             │
 └──────────────────────────────────────────────────────┘
      │
      ▼
 ┌──────────────────────────────────────────────────────┐
 │  sql/cohorts/  (orchestrated by cohort.py)           │
 │  • Concept-set matching (GLP-1 drugs, T2DM codes)    │
 │  • Index date derivation                             │
 │  • Inclusion / exclusion filter cascade              │
 │  • Baseline feature construction (no look-ahead)     │
 │  • Outcome ascertainment                             │
 │  • Cohort attrition recording in audit schema        │
 └──────────────────────────────────────────────────────┘
      │
      ▼
 ┌──────────────────────────────────────────────────────┐
 │  sql/analysis/  (called by analysis.py / stats.py)  │
 │  • Characteristics table aggregation                 │
 │  • Outcome rate calculations                         │
 │  • Subgroup summaries                                │
 │  • Missingness summary                               │
 └──────────────────────────────────────────────────────┘
      │
      ▼
 ┌──────────────────────────────────────────────────────┐
 │  src/evidence_studio/statistics.py                   │
 │  • Logistic regression (statsmodels)                 │
 │  • Odds ratios with 95% CIs                          │
 │  • Convergence and small-sample warnings             │
 └──────────────────────────────────────────────────────┘
      │
      ▼
 ┌──────────────────────────────────────────────────────┐
 │  Streamlit app  (app.py + src/evidence_studio/ui/)   │
 │  • 8 pages via st.Page / st.navigation               │
 │  • Plotly charts                                     │
 │  • Downloadable tables (CSV)                         │
 │  • Evidence brief (Jinja2 → Markdown / HTML)         │
 └──────────────────────────────────────────────────────┘
```

---

## DuckDB schema layout

```
evidence_studio.duckdb
├── raw                     ← Synthea CSVs loaded verbatim
│   ├── patients
│   ├── encounters
│   ├── medications
│   ├── conditions
│   ├── observations
│   ├── procedures
│   └── ... (other Synthea tables as available)
│
├── standardized            ← Cleaned, typed, key-validated
│   ├── patients
│   ├── encounters
│   ├── medications
│   ├── conditions
│   ├── observations
│   └── measurement_values  ← Parsed from observations
│
├── analytics               ← Study-level tables
│   ├── glp1_index_events   ← First GLP-1 start per patient
│   ├── cohort              ← Enrolled patients + attrition flags
│   ├── baseline_features   ← All covariates, one row per patient
│   ├── outcomes            ← ED/inpatient encounters, survival time
│   └── analysis_dataset    ← Final model-ready flat table
│
├── omop                    ← Demonstration OMOP-aligned layer
│   ├── person
│   ├── observation_period
│   ├── visit_occurrence
│   ├── condition_occurrence
│   ├── drug_exposure
│   └── measurement
│
└── audit                   ← Provenance and quality
    ├── data_manifest       ← File names, row counts, load timestamps
    ├── dq_results          ← Per-rule pass/fail with counts
    ├── study_runs          ← Each cohort build: params + timestamp
    ├── cohort_attrition    ← Step-by-step patient counts
    ├── generated_sql       ← SQL text executed per run
    └── assumption_log      ← Free-text assumption records
```

---

## Repository layout

```
real-world-evidence-studio/        ← repo root
│
├── app.py                        ← Streamlit entry point (st.navigation)
├── pyproject.toml                ← Build config, deps, ruff, pytest settings
├── CLAUDE.md                     ← Project rules for Claude Code
├── README.md                     ← Human-readable project overview
├── LICENSE
├── .env.example                  ← SYNTHEA_DATA_DIR, DB_PATH placeholders
├── .gitignore
│
├── config/
│   ├── study_defaults.yml        ← Default follow-up window, exclusions, etc.
│   └── concept_sets.yml          ← GLP-1 drug strings, T2DM SNOMED codes, etc.
│
├── data/
│   ├── raw/                      ← Synthea CSVs (git-ignored except .gitkeep)
│   └── processed/                ← Intermediate outputs (git-ignored)
│
├── docs/
│   ├── architecture.md           ← This file
│   ├── methodology.md            ← Study design and clinical definitions
│   ├── data_dictionary.md        ← Column-level descriptions per schema
│   ├── omop_mapping.md           ← OMOP layer decisions and limitations
│   ├── limitations.md            ← Data and analytic limitations
│   └── data_setup.md             ← Synthea download and placement instructions
│
├── sql/
│   ├── ingestion/                ← DDL for raw schema tables
│   ├── standardized/             ← Transformation SQL for standardized schema
│   ├── cohorts/                  ← Index event, attrition, baseline, outcomes
│   └── analysis/                 ← Characteristics, rates, missingness
│
├── src/evidence_studio/
│   ├── __init__.py
│   ├── config.py                 ← Pydantic StudyConfig and ConceptSet models
│   ├── database.py               ← DuckDB connection factory, SQL runner
│   ├── ingestion.py              ← CSV → raw schema; manifest recording
│   ├── data_quality.py           ← DQ rules, results, reporting
│   ├── concepts.py               ← Concept-set matching against loaded data
│   ├── cohort.py                 ← Cohort build orchestrator
│   ├── analysis.py               ← Descriptive statistics, outcome rates
│   ├── statistics.py             ← Logistic regression, CIs, warnings
│   ├── audit.py                  ← Assumption logging, run history
│   ├── reporting.py              ← Jinja2 evidence-brief renderer
│   ├── cli.py                    ← Click CLI for non-UI operations
│   └── ui/
│       ├── __init__.py
│       ├── components.py         ← Shared Streamlit widget helpers
│       └── pages/
│           ├── overview.py
│           ├── data_quality.py
│           ├── study_designer.py
│           ├── cohort_attrition.py
│           ├── results.py
│           ├── sql_audit.py
│           ├── evidence_brief.py
│           └── methodology.py
│
└── tests/
    ├── fixtures/                 ← Tiny synthetic CSV files for unit tests
    ├── unit/
    │   ├── test_config.py
    │   ├── test_concepts.py
    │   ├── test_cohort.py
    │   ├── test_statistics.py
    │   └── test_reporting.py
    └── integration/
        ├── test_ingestion.py
        └── test_cohort_pipeline.py
```

---

## Module responsibilities

### `config.py`
Defines `StudyConfig` (Pydantic BaseModel or dataclass) and `ConceptSet`. Loads
`config/study_defaults.yml` and `config/concept_sets.yml`. Provides a
`StudyConfig.from_yaml()` constructor and a `StudyConfig.to_dict()` serialiser
used by the audit layer.

### `database.py`
Owns the DuckDB connection. Provides:
- `get_connection(db_path)` — returns a `duckdb.DuckDBPyConnection`
- `execute_sql_file(conn, path, params)` — runs a `.sql` file with named params
- `run_query(conn, sql, params)` — returns a `pandas.DataFrame`

All connections are file-backed (no `:memory:` in production).

### `ingestion.py`
- Discovers Synthea CSV files under the configured data directory.
- Loads each file into `raw.<table_name>` using DuckDB's `read_csv_auto`.
- Writes a row to `audit.data_manifest` per file (path, row count, load time,
  column list).
- Raises a typed exception if a required file is missing.

### `data_quality.py`
Runs a fixed set of DQ rules (nullability, referential integrity, date ordering,
plausibility checks) and writes results to `audit.dq_results`. Exposes a
`DQReport` dataclass for the Streamlit page.

### `concepts.py`
- Loads concept definitions from `config/concept_sets.yml`.
- Queries `standardized.medications` for GLP-1 drug string matches (case-
  insensitive substring, not regex injection).
- Returns a `ConceptMatchResult` with matched descriptions, codes, and patient
  counts.
- Never assumes a drug is present; reports zero matches clearly.

### `cohort.py`
Orchestrates the cohort build in sequential SQL steps:
1. Identify GLP-1 index events.
2. Apply inclusion criteria (one step at a time for attrition tracking).
3. Derive baseline features (strict 365-day look-back, no future information).
4. Ascertain primary and secondary outcomes in the follow-up window.
5. Write attrition counts to `audit.cohort_attrition`.
6. Write the run record to `audit.study_runs`.

### `analysis.py`
Produces the following from `analytics.analysis_dataset`:
- `characteristics_table()` — count/percent or mean/SD per covariate
- `outcome_summary()` — rates and counts for each outcome
- `subgroup_summary(by)` — stratified outcome rates
- `missingness_summary()` — percent missing per covariate

### `statistics.py`
- Fits a multivariable logistic regression using `statsmodels.formula.api.logit`.
- Returns `RegressionResult` with ORs, 95% CIs, p-values, and convergence flag.
- Emits structured warnings for: n < 50, outcome < 5 events, non-convergence,
  perfect separation, and unstable estimates.
- Uses no causal language in any output string.

### `audit.py`
- `log_assumption(conn, text, context)` — writes to `audit.assumption_log`.
- `log_sql(conn, label, sql_text)` — writes to `audit.generated_sql`.
- `get_run_history(conn)` — returns recent study runs as a DataFrame.

### `reporting.py`
- Renders a Jinja2 template (`templates/evidence_brief.md.j2`) to Markdown.
- Optionally converts to HTML via `markdown` library.
- Embeds the disclaimer in every output.

### `cli.py`
Click-based CLI for running the pipeline without the UI:
```
python -m evidence_studio ingest --data-dir data/raw/
python -m evidence_studio build-cohort --config config/study_defaults.yml
python -m evidence_studio export-brief --output brief.md
```

---

## Key design decisions

| Decision | Rationale |
|----------|-----------|
| DuckDB over SQLite | Columnar execution, native CSV ingestion, schema namespaces, no server required |
| SQL as primary logic layer | Keeps transformations auditable, reproducible, and inspectable from the UI |
| Statsmodels over sklearn | Produces standard error and CI estimates directly; interpretable summary tables |
| Pydantic for config | Runtime validation of YAML parameters; serialisable to JSON for audit records |
| Separate audit schema | Every cohort build is traceable without modifying the analytical tables |
| `st.Page` / `st.navigation` | Avoids the deprecated multi-page file convention; single entry point `app.py` |

---

## What this architecture does NOT do in V1

- No dbt models, no Airflow DAGs, no cloud storage.
- No authentication or multi-user sessions.
- No REST API; Streamlit accesses DuckDB directly.
- No causal inference methods (propensity score matching, IV estimation).
- OMOP layer is illustrative only; no validated vocabulary mapping.

These are documented as future enhancements and must not be silently implied.
