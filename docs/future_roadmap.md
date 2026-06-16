# Future Roadmap

Planned enhancements for versions beyond V1. Items are roughly ordered by
analytical value and implementation effort.

Nothing here is committed, scheduled, or implied by the current codebase.

---

## Analytical enhancements

### 1. Propensity score methods
Replace or supplement the adjusted regression with propensity score matching
(PSM) or inverse probability of treatment weighting (IPTW) to better address
confounding. Requires `scikit-learn` or `causalml` for score estimation and
`tableone` for standardized mean differences.

### 2. Cox proportional-hazards model
Add a time-to-event analysis for the primary outcome to handle variable
follow-up and censoring properly. Use `lifelines` or `statsmodels.duration`.

### 3. Active comparator design
Compare GLP-1 initiators against initiators of another diabetes drug class
(e.g., DPP-4 inhibitors, SGLT-2 inhibitors) to reduce channeling bias.

### 4. Sensitivity analyses
- 30/90/365-day follow-up windows (selectable in Study Designer — already
  partially implemented)
- Alternative T2DM definitions (code-only vs. code + medication)
- On-treatment analysis vs. intent-to-treat

### 5. Multiple outcomes
Add secondary outcomes: inpatient admission, 30-day readmission, all-cause
mortality, A1c reduction (if available in Synthea observations).

---

## Data and infrastructure

### 6. Full OMOP CDM mapping
Map all source codes to standard OMOP concept IDs using the Athena vocabulary.
Validate with `PyOMOP` or `OHDSI WebAPI`. Document all unmapped codes.

### 7. FHIR R4 ingestion
Accept FHIR R4 bundles (JSON) as an alternative to Synthea CSV, using
`fhirpy` or direct DuckDB JSON path extraction.

### 8. PostgreSQL backend
Replace or supplement DuckDB with PostgreSQL for multi-user shared
deployments. Abstract the connection layer so both backends are supported.

### 9. Docker container
Provide a `Dockerfile` and `docker-compose.yml` so the full app (DuckDB,
Streamlit, Synthea data volume) runs with `docker compose up`.

### 10. Automated Synthea data generation
Add a `scripts/generate_synthea.sh` wrapper that downloads the Synthea JAR,
runs a configurable patient generation, and places output in `data/raw/`.

---

## Platform and operations

### 11. Scheduled re-runs
Use APScheduler or a simple cron wrapper to re-run the pipeline nightly
against a continuously updated data source (relevant for real EHR environments).

### 12. Role-based access
Add Streamlit authentication (StreamlitAuthenticator or OAuth) and view-level
permissions if the app is ever deployed to a shared environment with PHI.

---

## Deferred per CLAUDE.md (prohibited in V1)

These are explicitly out of scope for V1 and must not be silently added:

- Airflow / dbt / Spark
- Cloud storage (S3, GCS, Azure Blob)
- REST API
- Authentication
- dbt models
- Any connection to real patient data without IRB and institutional approval
