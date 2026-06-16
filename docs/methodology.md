# Methodology — Real-World Evidence Studio

> **Synthetic data disclaimer.** All findings in this application are derived
> from Synthea-generated synthetic records. They do not represent real patients,
> clinical outcomes, treatment effectiveness, drug safety, or incidence rates.
> This document describes a study design applied to synthetic data for
> portfolio and educational purposes only.

---

## 1. Clinical question

Among **synthetic adult patients with type 2 diabetes** who initiate a GLP-1
receptor agonist therapy, what patient characteristics are associated with
**emergency department (ED) utilization** during the following 180 days?

This is an **associational question**. The analysis describes covariate patterns
linked to ED visits in a synthetic cohort. It does not establish causal
relationships between GLP-1 therapy and ED outcomes.

---

## 2. Study design

**Design:** Retrospective new-user cohort study applied to synthetic EHR data.

**Data source:** Synthea open-source synthetic patient generator output (CSV
format). Synthea simulates longitudinal EHR records including demographics,
conditions, medications, encounters, observations, and procedures.

**Observation period:** Defined by the earliest and latest dates present in the
loaded Synthea files. No data outside the available Synthea time range is used
or imputed.

---

## 3. Exposure

### 3.1 Drug class

GLP-1 receptor agonists (glucagon-like peptide-1 receptor agonists).

### 3.2 Concept set

The application inspects the actual medication descriptions and source codes
present in the loaded Synthea files. The following drug names are used as
case-insensitive substring search terms:

| Search term | Notes |
|-------------|-------|
| `semaglutide` | Ozempic, Wegovy, Rybelsus; oral and injectable forms |
| `liraglutide` | Victoza, Saxenda |
| `dulaglutide` | Trulicity |
| `exenatide` | Byetta, Bydureon |
| `tirzepatide` | Mounjaro, Zepbound; dual GIP/GLP-1 agonist, included by convention |

If none of these terms match any medication description in the loaded files, the
application reports zero matches and halts cohort construction with an
informative message. Results are never fabricated.

### 3.3 Index date

The **index date** is the earliest `start_date` of a medication record matching
the GLP-1 concept set for each eligible patient. Only the first observed
initiation is used (new-user design).

---

## 4. Study population

### 4.1 Inclusion criteria

All criteria are evaluated as of the index date.

| Criterion | Definition |
|-----------|-----------|
| **T2DM diagnosis** | At least one condition record with a SNOMED code or description matching type 2 diabetes on or before the index date. Concept strings include: `"diabetes mellitus type 2"`, `"type 2 diabetes mellitus"`, `"type 2 diabetes"`. |
| **Adult age** | Age ≥ 18 years on the index date. Derived from `birthdate` in the patients table. |
| **Baseline observation** | At least 365 days between the patient's earliest available record date and the index date. |
| **Follow-up observation** | At least 180 days between the index date and the patient's last available record date, or until death, whichever comes first. The minimum follow-up window is shortened to the day of death when death precedes day 180. |
| **New-user requirement** | No prior GLP-1 medication record before the index date. |

### 4.2 Exclusion criteria (configurable in the Study Designer)

Each exclusion can be toggled independently. All are applied after inclusion
criteria are satisfied.

| Criterion | Definition | Default |
|-----------|-----------|---------|
| **Type 1 diabetes** | Any condition record matching T1DM concepts on or before the index date | Excluded |
| **Gestational diabetes** | Any condition record matching gestational diabetes concepts on or before the index date | Excluded |
| **Pregnancy at index** | Any pregnancy-related condition or procedure record overlapping the index date (± 30 days) | Excluded |
| **Missing required demographics** | Patient is missing `sex`, `race`, or `ethnicity` when those fields are required by the selected analysis | Excluded |

---

## 5. Baseline window and features

### 5.1 Baseline window

The **baseline window** spans the 365 days ending the day before the index date
(i.e., `[index_date − 365, index_date − 1]` inclusive). No data on or after
the index date enters baseline feature construction.

### 5.2 Baseline characteristics

#### Demographics

| Feature | Source field | Notes |
|---------|-------------|-------|
| Age | `patients.birthdate` | Calculated at index date |
| Age group | Derived | 18–34, 35–49, 50–64, 65–74, 75+ |
| Sex | `patients.gender` | Recorded value in Synthea; not imputed |
| Race | `patients.race` | Recorded value; missingness flagged |
| Ethnicity | `patients.ethnicity` | Recorded value; missingness flagged |

#### Comorbidities (ever on or before index date)

| Feature | Definition |
|---------|-----------|
| Hypertension | Condition record matching hypertension concepts |
| Chronic kidney disease (CKD) | Condition record matching CKD concepts |
| Cardiovascular disease (CVD) | Condition record matching CVD concepts (coronary artery disease, heart failure, stroke, MI) |
| Number of chronic conditions | Count of distinct active condition records on or before index date |

#### Utilization in baseline window

| Feature | Definition |
|---------|-----------|
| Baseline ED count | Count of encounter records with `encounterclass = 'emergency'` in baseline window |
| Baseline inpatient count | Count of encounter records with `encounterclass = 'inpatient'` in baseline window |
| Baseline outpatient count | Count of encounter records with `encounterclass = 'outpatient'` or `'ambulatory'` in baseline window |

#### Medications in baseline window

| Feature | Definition |
|---------|-----------|
| Active medication count | Count of distinct medication records active or started in the baseline window (excluding GLP-1) |

#### Clinical measurements

| Feature | Definition |
|---------|-----------|
| Latest baseline BMI | Most recent BMI observation code in baseline window; missing if no record |
| Latest baseline HbA1c | Most recent HbA1c observation in baseline window; missing if no record |

#### Exposure detail

| Feature | Definition |
|---------|-----------|
| GLP-1 drug initiated | Matched drug description from the concept set |

---

## 6. Follow-up window and outcomes

### 6.1 Follow-up window

Default: **180 days** after the index date (`[index_date + 1, index_date + 180]`).

User-selectable alternatives: 30, 90, 180, 365 days. Changing the window
triggers a full cohort rebuild because the minimum follow-up eligibility
criterion references the selected window length.

Follow-up is censored at the earlier of: the end of the window, death, or the
last available record date in the Synthea data.

### 6.2 Primary outcome

**Any ED encounter during follow-up** — at least one encounter record with
`encounterclass = 'emergency'` whose start date falls within the follow-up
window.

### 6.3 Secondary outcomes

| Outcome | Definition |
|---------|-----------|
| Number of ED encounters | Count of qualifying ED encounters in the follow-up window |
| ED visits per 100 person-months | (ED encounter count / person-time in months) × 100 |
| Any inpatient encounter | At least one encounter with `encounterclass = 'inpatient'` in follow-up |
| Time to first ED encounter | Days from index date to first ED encounter; right-censored at follow-up end |

---

## 7. Analysis

### 7.1 Cohort characteristics table

Descriptive statistics for all baseline features in the enrolled cohort.

- Continuous variables: mean (SD), median (IQR).
- Binary and categorical variables: count (%), with the denominator being all
  enrolled patients.
- Missingness is reported separately in the missingness summary, not imputed.

### 7.2 Outcome summary

Count and proportion of patients meeting each outcome definition. ED rate per
100 person-months is computed using actual observed follow-up time, not the
nominal window length.

### 7.3 Subgroup comparisons

Unadjusted outcome rates stratified by: age group, sex, race, ethnicity,
hypertension status, CKD status, CVD status, baseline ED count category
(0, 1, 2+), and initiated GLP-1 drug.

### 7.4 Missingness summary

Percent missing for each covariate in the analysis dataset. Variables with
>20% missingness are highlighted. No imputation is performed in V1.

### 7.5 Multivariable logistic regression

Outcome: binary indicator for any ED encounter during follow-up.

Candidate predictors (complete-case analysis in V1):

- Age (continuous)
- Sex
- Race
- Ethnicity
- Hypertension indicator
- CKD indicator
- CVD indicator
- Baseline ED encounter count (0, 1, 2+)
- Baseline inpatient count (continuous or categorised)
- Number of chronic conditions (continuous)
- Active medication count (continuous)
- Latest baseline HbA1c (continuous; subjects with missing HbA1c excluded)
- Latest baseline BMI (continuous; subjects with missing BMI excluded)

Variables are dropped from the model if they produce perfect separation or
if the cell count in any category is fewer than 5. This decision is logged
to the assumption log.

**Output:** Odds ratios, 95% confidence intervals, p-values, and model-fit
statistics (log-likelihood, AIC, BIC, pseudo-R²).

**Warnings emitted automatically when:**
- Enrolled cohort has fewer than 50 patients
- Fewer than 10 outcome events (or outcome rate < 5%)
- Model fails to converge
- Any OR confidence interval is wider than 10 log-odds units (instability)
- Any predictor is dropped due to separation

### 7.6 Language constraints

No output produced by this application may use causal language. Prohibited
phrases include: "reduces," "prevents," "causes," "leads to," "results in,"
"due to," "because of." Permitted language: "associated with," "linked to,"
"observed difference," "higher/lower rate in."

---

## 8. Reproducibility

Each cohort build records to `audit.study_runs`:
- Timestamp
- Study configuration (JSON-serialised `StudyConfig`)
- DuckDB file path and schema version
- Synthea file manifest (names, row counts, load timestamps)
- All assumption log entries for the run

A saved run configuration can be reloaded via the Study Designer to reproduce
the exact cohort from the same Synthea data.

---

## 9. Limitations specific to this study design

See [limitations.md](limitations.md) for the full discussion. Key points:

1. **Synthea data** does not reflect real clinical populations; all associations
   are artefacts of the simulation model.
2. **New-user design** assumes the first GLP-1 record in Synthea is truly a
   new initiation; prior exposure before the Synthea observation window cannot
   be detected.
3. **Complete-case analysis** excludes patients with missing covariates;
   missingness in Synthea is not missing at random in the same way as real EHR data.
4. **No confounding adjustment beyond regression**; unmeasured confounders
   (patient preferences, provider prescribing patterns) are not modelled.
5. **Encounter-class classification** in Synthea may not perfectly align with
   CMS site-of-service definitions used in real RWE studies.
6. **No competing risks** analysis; death is treated as administrative censoring.
7. **OMOP layer** uses concept ID 0 for unmapped codes; it is illustrative only.

---

*Study design version 1.0 — Real-World Evidence Studio*
