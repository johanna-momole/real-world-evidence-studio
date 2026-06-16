# CLAUDE.md — Real-World Evidence Studio

This file governs how Claude Code assists with this project. Read it before modifying any file.

---

## Project identity

**Real-World Evidence Studio** is a local Streamlit application that demonstrates
transparent real-world evidence (RWE) generation using synthetic Synthea EHR data.

Primary clinical question:

> Among synthetic adult patients with type 2 diabetes who initiate a GLP-1
> therapy, what patient characteristics are associated with emergency department
> (ED) utilization during the following 180 days?

This is a **portfolio and educational project**. It must never claim that
synthetic results represent real clinical evidence, treatment effectiveness,
safety, incidence, or causality. All pages and outputs must carry an appropriate
disclaimer.

---

## Technical stack (V1 — mandatory)

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 or newer |
| Analytical DB | DuckDB (in-process, file-backed) |
| Source data | Synthea CSV files |
| Query language | SQL (primary logic layer) |
| Dataframes | Pandas or Polars only where SQL is not appropriate |
| App framework | Streamlit with `st.Page` and `st.navigation` |
| Charts | Plotly |
| Statistics | Statsmodels (interpretable models only for V1) |
| Configuration | Pydantic v2 or dataclasses; YAML config files |
| Templating | Jinja2 (evidence-brief rendering) |
| Testing | Pytest |
| Linting/format | Ruff |
| Project config | pyproject.toml |

**Prohibited in V1 (mark as future enhancements if discussed):**
PostgreSQL, Spark, Airflow, dbt, cloud infrastructure, authentication, REST API.

---

## Data layers

Use DuckDB schemas with these exact names:

| Schema | Purpose |
|--------|---------|
| `raw` | Exact source CSVs loaded into DuckDB with no transformation |
| `standardized` | Cleaned dates, normalized field names, validated identifiers, reusable clinical tables |
| `analytics` | Index events, cohort membership, baseline features, outcomes, analysis-ready tables |
| `audit` | Data manifests, DQ results, study runs, cohort attrition, generated SQL, assumptions, timestamps |

---

## OMOP component

Create a small, explicitly labeled OMOP-aligned demonstration layer:
- `person`, `observation_period`, `visit_occurrence`, `condition_occurrence`,
  `drug_exposure`, `measurement`

Rules:
- Preserve source codes and source values in every table.
- When a proper OMOP concept ID has not been mapped via an official vocabulary,
  use `concept_id = 0` and document it.
- Never describe this layer as a validated or fully compliant OMOP CDM.
- Document all limitations in `docs/omop_mapping.md`.

---

## Study design constants

### Exposure (GLP-1 class)
Inspect actual medication descriptions in the loaded Synthea files. Do not assume
any drug is present. Do not fabricate matches.

Concept set members:
- semaglutide
- liraglutide
- dulaglutide
- exenatide
- tirzepatide

### Index date
First observed GLP-1 medication start date for each patient.

### Inclusion criteria (core)
- Age ≥ 18 on the index date
- Evidence of type 2 diabetes on or before index date
- ≥ 365 days of observable history before index (based on Synthea data)
- ≥ 180 days of observable follow-up after index (or until death)
- First GLP-1 initiation during the observation period

### Exclusion criteria (configurable)
- Type 1 diabetes
- Gestational diabetes
- Pregnancy overlapping the index date
- Missing demographics required by the selected analysis

### Windows
- Baseline: 365 days before index date (excluding index date)
- Follow-up: 180 days default; user-selectable 30 / 90 / 180 / 365 days

### Primary outcome
Any ED encounter during follow-up.

---

## Engineering rules

### SQL
- Use parameterized SQL everywhere user-controlled or runtime values are passed.
- Never interpolate unsanitized strings into SQL.
- Do not use future information when constructing baseline features (no look-ahead).
- Keep business logic in `src/evidence_studio/` modules, not in Streamlit page files.

### Python
- All functions and public methods must have type hints and a concise one-line docstring.
- Handle empty cohorts, missing Synthea files, and schema mismatches gracefully.
- Log assumptions and important processing decisions (Python `logging`, not `print`).
- Do not fabricate data, results, concept IDs, mappings, or sample sizes.

### Comments
- Write no comments by default.
- Add a comment only when the WHY is non-obvious: a hidden constraint, a subtle
  invariant, a known upstream data quirk, or a workaround for a specific bug.
- Never explain what the code does (the code does that). Never reference the
  current task or issue number in comments.

### Testing
- Run `ruff check` and `ruff format --check` after every meaningful phase.
- Run `pytest` after every meaningful phase.
- Tiny synthetic fixtures may be committed under `tests/fixtures/`.
- Full generated datasets and `.duckdb` files must be excluded from Git.

### Cross-platform
- Keep the application usable on Windows, macOS, and Linux.
- Use `pathlib.Path` throughout; never hard-code path separators.

### Commits
- Do not commit or push changes unless I explicitly request it.

---

## Streamlit app pages

| Page | Purpose |
|------|---------|
| Overview | Project summary, data source status, disclaimer |
| Data Quality | Manifest, row counts, missingness, DQ rule results |
| Study Designer | Concept-set inspection, inclusion/exclusion toggles, follow-up window |
| Cohort Attrition | Waterfall diagram, attrition table, run metadata |
| Results | Characteristics table, outcome summary, subgroup comparisons, regression |
| SQL & Audit Trail | Generated SQL viewer, assumption log, study-run history |
| Evidence Brief | Downloadable Markdown/HTML brief via Jinja2 template |
| Methodology & Limitations | Study design narrative and all disclaimers |

---

## Working method for Claude Code

Before modifying files:
1. Read the current file(s) that will change.
2. Identify existing content that should be preserved.
3. Explain what will change and why.
4. Implement the change.
5. Run `ruff check` and `pytest` and report results.

Do not skip step 1. Do not fabricate file contents from memory.

---

## Disclaimer (must appear on every generated output)

> **Synthetic data only.** All results in this application are derived from
> Synthea-generated synthetic records. They do not represent real patients,
> clinical outcomes, treatment effectiveness, drug safety, or incidence rates.
> This project must not be used for clinical decisions, regulatory submissions,
> or public health reporting.
