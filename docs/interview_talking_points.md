# Interview Talking Points

Reference sheet for healthcare informatics, data science, and health tech
interviews. Grouped by topic.

---

## Real-world evidence methodology

**"Walk me through your study design."**
- New-user (incident user) design to avoid prevalent-user bias
- GLP-1 initiation as index event; T2DM diagnosis required before index
- 365-day look-back for baseline features; 180-day follow-up for outcomes
- Stepwise attrition with every exclusion criterion documented separately
- Primary outcome: any ED encounter (binary); secondary: count (Poisson-appropriate)

**"Why logistic regression and not a Cox model?"**
- Binary primary outcome with a fixed follow-up window makes logistic appropriate
- Cox handles variable follow-up and censoring more naturally — documented in
  `docs/future_roadmap.md` as the next modeling step
- Statsmodels was chosen over sklearn because it produces standard errors, CIs,
  and p-values in a single call with interpretable summary tables

**"How do you handle confounding?"**
- V1 adjusts for age, sex, race/ethnicity, BMI group, hypertension, CKD, CVD,
  baseline ED count, and GLP-1 drug class
- Propensity score matching and inverse probability weighting are documented as
  future enhancements
- The app explicitly warns that no causal interpretation is valid

---

## Data engineering

**"Why DuckDB?"**
- In-process: no server, no JDBC, runs on any laptop
- Native CSV ingestion via `read_csv_auto`
- Schema namespaces (`raw`, `standardized`, `analytics`, `audit`) without
  separate databases
- Columnar execution for aggregations over millions of Synthea rows
- Serializes to a single `.duckdb` file for easy portability

**"How do you ensure the pipeline is reproducible?"**
- SHA-256 hashes of every source file in `audit.data_manifest`
- Study run ID = SHA-256(config JSON) + UTC minute timestamp
- All generated SQL stored in `audit.generated_sql`
- Config YAML captured in `audit.study_runs`
- Evidence brief includes the exact run ID and file hashes

**"How do you prevent SQL injection?"**
- All user-controlled values passed as positional `?` parameters
- No string interpolation of user input into SQL
- Tested explicitly in `test_analysis_edge_cases.py`

---

## Software engineering

**"How is the codebase organized?"**
- Business logic in `src/evidence_studio/` modules (no logic in Streamlit pages)
- SQL as the primary logic layer for all data transformations
- Pydantic v2 for config validation with YAML loading
- `pathlib.Path` throughout for cross-platform compatibility
- Type hints on all public functions; docstrings required

**"How does the test suite work?"**
- Unit tests only; no Synthea downloads in CI
- `tests/fixtures/` contains hand-crafted minimal CSVs
- Real DuckDB connections via `tmp_path` — no mocking
- Empty-DB cases mandatory for every analysis function
- GitHub Actions runs ruff, ruff format, and pytest on every push

**"What's the Streamlit architecture?"**
- `st.Page` / `st.navigation` (not the deprecated multi-file pattern)
- `@st.cache_resource` keyed on a string path, not a Pydantic object (unhashable)
- Sidebar rendered from `app.py` before `pg.run()` so it persists across all pages
- `st.session_state` for cohort run ID and study config

---

## OMOP and clinical informatics

**"Do you know OMOP?"**
- The project includes an explicitly labeled OMOP demonstration layer:
  `person`, `observation_period`, `visit_occurrence`, `condition_occurrence`,
  `drug_exposure`, `measurement`
- Source codes and source values preserved in every table
- `concept_id = 0` when no proper OMOP concept ID has been mapped
- Limitations documented in `docs/omop_mapping.md`; not claimed as validated CDM

**"What are the limitations of using Synthea?"**
- Simulated data reflects the simulator's coding patterns, not real-world
  prescribing behavior or coding variability
- No real channeling bias, no real missing data mechanisms
- Drug descriptions are standardized text, not real NDC codes or RxNorm
- Results cannot be used for any regulatory, clinical, or public health purpose
- Full list in `docs/limitations.md`

---

## Career narrative

**"Why this project?"**
- Wanted to demonstrate the full RWE pipeline, not just analysis — from raw
  EHR files to a documented evidence report, with an audit trail
- GLP-1/T2DM/ED is clinically relevant and methodologically interesting
- Portfolio-grade: transparent, tested, reproducible, and honest about limits

**"What would you do differently for production?"**
- PostgreSQL or Snowflake for multi-user and scale
- Proper OMOP vocabulary mapping via Athena
- IRB-compliant data access and de-identification
- Propensity score methods for causal inference
- Docker container for reproducible deployment
- Full FHIR R4 ingestion alongside Synthea CSV
- See `docs/future_roadmap.md` for the full list
