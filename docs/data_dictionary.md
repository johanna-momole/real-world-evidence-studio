# Data Dictionary — Real-World Evidence Studio

> **Synthetic data disclaimer.** All tables contain Synthea-generated synthetic
> records. They do not represent real patients, clinical outcomes, treatment
> effectiveness, drug safety, or incidence rates.

---

## raw schema — exact Synthea source (column names as-is)

### raw.patients
| Column | Type | Description |
|--------|------|-------------|
| Id | VARCHAR | Synthea patient UUID |
| BIRTHDATE | VARCHAR | Date of birth (YYYY-MM-DD string) |
| DEATHDATE | VARCHAR | Date of death; empty if alive |
| SSN | VARCHAR | Synthetic social security number |
| RACE | VARCHAR | Synthea race label |
| ETHNICITY | VARCHAR | Synthea ethnicity label |
| GENDER | VARCHAR | M / F as recorded in Synthea |
| CITY, STATE, ZIP | VARCHAR | Synthetic address fields |
| FIRST, LAST | VARCHAR | Synthetic name fields |
| HEALTHCARE_EXPENSES, HEALTHCARE_COVERAGE, INCOME | VARCHAR | Synthetic financial fields |

### raw.encounters
| Column | Type | Description |
|--------|------|-------------|
| Id | VARCHAR | Encounter UUID |
| START, STOP | VARCHAR | Encounter datetime (ISO 8601 string) |
| PATIENT | VARCHAR | Foreign key → patients.Id |
| ENCOUNTERCLASS | VARCHAR | ambulatory / emergency / inpatient / outpatient / wellness / urgentcare |
| CODE | VARCHAR | SNOMED encounter code |
| DESCRIPTION | VARCHAR | Human-readable encounter type |
| BASE_ENCOUNTER_COST, TOTAL_CLAIM_COST | VARCHAR | Synthetic cost fields |

### raw.conditions
| Column | Type | Description |
|--------|------|-------------|
| START | VARCHAR | Condition onset date (YYYY-MM-DD) |
| STOP | VARCHAR | Condition resolution date; empty if active |
| PATIENT | VARCHAR | Foreign key → patients.Id |
| ENCOUNTER | VARCHAR | Foreign key → encounters.Id |
| CODE | VARCHAR | SNOMED condition code |
| DESCRIPTION | VARCHAR | Condition name |

### raw.medications
| Column | Type | Description |
|--------|------|-------------|
| START | VARCHAR | Medication start date (YYYY-MM-DD) |
| STOP | VARCHAR | Medication stop date; empty if active |
| PATIENT | VARCHAR | Foreign key → patients.Id |
| ENCOUNTER | VARCHAR | Foreign key → encounters.Id |
| CODE | VARCHAR | RxNorm drug code |
| DESCRIPTION | VARCHAR | Full drug name including strength and form |
| DISPENSES | VARCHAR | Number of dispenses |
| BASE_COST | VARCHAR | Synthetic cost |

### raw.observations
| Column | Type | Description |
|--------|------|-------------|
| DATE | VARCHAR | Observation date (YYYY-MM-DD) |
| PATIENT | VARCHAR | Foreign key → patients.Id |
| ENCOUNTER | VARCHAR | Foreign key → encounters.Id |
| CODE | VARCHAR | LOINC observation code |
| DESCRIPTION | VARCHAR | Observation name |
| VALUE | VARCHAR | Observation value (numeric or text) |
| UNITS | VARCHAR | Unit of measure |
| TYPE | VARCHAR | numeric / text / date / etc. |

---

## standardized schema — cleaned, typed, normalized

### standardized.patients
| Column | Type | Description |
|--------|------|-------------|
| patient_id | VARCHAR | UUID from raw.patients.Id |
| birth_date | DATE | Parsed from BIRTHDATE |
| death_date | DATE | Parsed from DEATHDATE; NULL if alive |
| race | VARCHAR | Lowercased RACE |
| ethnicity | VARCHAR | Lowercased ETHNICITY |
| sex | VARCHAR | Lowercased GENDER |
| city, state, zip_code | VARCHAR | Address fields |
| first_name, last_name | VARCHAR | Trimmed name fields |
| source_patient_id | VARCHAR | Copy of patient_id for traceability |

### standardized.encounters
| Column | Type | Description |
|--------|------|-------------|
| encounter_id | VARCHAR | UUID |
| encounter_start | TIMESTAMP | Parsed from START |
| encounter_stop | TIMESTAMP | Parsed from STOP; NULL if absent |
| patient_id | VARCHAR | FK → standardized.patients |
| encounter_class | VARCHAR | Lowercased encounter class |
| encounter_code | VARCHAR | SNOMED code |
| encounter_description | VARCHAR | Encounter type |
| reason_code | VARCHAR | SNOMED reason code |
| reason_description | VARCHAR | Reason description |
| base_cost, total_cost | DOUBLE | Parsed cost fields |

### standardized.conditions
| Column | Type | Description |
|--------|------|-------------|
| patient_id | VARCHAR | FK → standardized.patients |
| encounter_id | VARCHAR | FK → standardized.encounters |
| condition_start | DATE | Parsed onset date |
| condition_stop | DATE | Parsed resolution date; NULL if active |
| condition_code | VARCHAR | SNOMED code |
| condition_description | VARCHAR | Lowercased condition name |

### standardized.medications
| Column | Type | Description |
|--------|------|-------------|
| patient_id | VARCHAR | FK → standardized.patients |
| encounter_id | VARCHAR | FK → standardized.encounters |
| medication_start | DATE | Parsed start date |
| medication_stop | DATE | Parsed stop date; NULL if active |
| medication_code | VARCHAR | RxNorm code |
| medication_description | VARCHAR | Lowercased full drug name |
| reason_code | VARCHAR | SNOMED reason code |
| reason_description | VARCHAR | Lowercased reason |
| dispenses | INTEGER | Parsed dispense count |
| base_cost | DOUBLE | Parsed cost |

### standardized.observations
| Column | Type | Description |
|--------|------|-------------|
| patient_id | VARCHAR | FK → standardized.patients |
| encounter_id | VARCHAR | FK → standardized.encounters |
| observation_date | DATE | Parsed observation date |
| observation_code | VARCHAR | LOINC code |
| observation_description | VARCHAR | Lowercased observation name |
| value_as_string | VARCHAR | Raw VALUE field |
| value_as_number | DOUBLE | Parsed numeric value; NULL if non-numeric |
| unit | VARCHAR | Unit of measure |
| observation_type | VARCHAR | Lowercased observation type |

---

## analytics schema — study-level tables

### analytics.glp1_index_events
| Column | Type | Description |
|--------|------|-------------|
| patient_id | VARCHAR | Patient identifier |
| index_date | DATE | First observed GLP-1 medication start |
| glp1_drug | VARCHAR | Drug description at index |
| glp1_code | VARCHAR | RxNorm code at index |

### analytics.cohort
One row per enrolled patient after all inclusion and exclusion criteria applied.

| Column | Type | Description |
|--------|------|-------------|
| patient_id | VARCHAR | Patient identifier |
| index_date | DATE | GLP-1 index date |
| glp1_drug | VARCHAR | Initiated GLP-1 drug |
| birth_date | DATE | Patient birth date |
| death_date | DATE | Patient death date; NULL if alive |
| sex, race, ethnicity | VARCHAR | From standardized.patients |

### analytics.baseline_features
One row per cohort patient. All covariates derived from data strictly before index_date.

| Column | Type | Description |
|--------|------|-------------|
| patient_id | VARCHAR | Patient identifier |
| index_date | DATE | GLP-1 index date |
| age_at_index | INTEGER | Age in years at index date |
| age_group | VARCHAR | 18-34 / 35-49 / 50-64 / 65-74 / 75+ |
| sex, race, ethnicity | VARCHAR | Patient demographics |
| glp1_drug | VARCHAR | Initiated GLP-1 drug |
| bl_ed_count | INTEGER | ED encounters in 365-day baseline window |
| bl_inpatient_count | INTEGER | Inpatient encounters in baseline window |
| bl_outpatient_count | INTEGER | Outpatient/ambulatory encounters in baseline window |
| n_conditions | INTEGER | Distinct chronic conditions on or before index |
| n_medications | INTEGER | Active non-GLP-1 medications in baseline window |
| has_hypertension | INTEGER | 1 = hypertension diagnosed on/before index |
| has_ckd | INTEGER | 1 = CKD diagnosed on/before index |
| has_cvd | INTEGER | 1 = CVD diagnosed on/before index |
| hba1c_pct | DOUBLE | Latest HbA1c (%) in baseline window; NULL if missing |
| bmi_value | DOUBLE | Latest BMI (kg/m²) in baseline window; NULL if missing |

### analytics.outcomes
| Column | Type | Description |
|--------|------|-------------|
| patient_id | VARCHAR | Patient identifier |
| index_date | DATE | Index date |
| follow_up_end | DATE | Earlier of: index + window, death, last encounter |
| follow_up_days_observed | INTEGER | Actual observed follow-up days |
| follow_up_months | DOUBLE | follow_up_days_observed / 30.4375 |
| fu_ed_count | INTEGER | ED encounters during follow-up |
| any_ed_visit | INTEGER | 1 = at least one ED encounter during follow-up |
| days_to_first_ed | INTEGER | Days from index to first ED visit; NULL if no ED |
| fu_ip_count | INTEGER | Inpatient encounters during follow-up |
| any_ip_visit | INTEGER | 1 = at least one inpatient encounter during follow-up |

### analytics.analysis_dataset
Joined baseline_features + outcomes. One row per enrolled patient.
Includes all columns from both tables above.

---

## audit schema — provenance and quality

### audit.data_manifest
| Column | Type | Description |
|--------|------|-------------|
| manifest_id | INTEGER | Auto-incrementing key |
| file_name | VARCHAR | CSV filename (e.g., patients.csv) |
| file_path | VARCHAR | Absolute path at load time |
| file_size_bytes | BIGINT | File size at load time |
| row_count | BIGINT | Row count as loaded |
| column_count | INTEGER | Column count |
| sha256_hash | VARCHAR | SHA-256 hex digest |
| load_timestamp | TIMESTAMP | UTC timestamp of load |

### audit.dq_results
| Column | Description |
|--------|-------------|
| dq_id | Auto-incrementing key |
| rule_name | DQ rule identifier |
| status | PASS / FAIL / WARN |
| affected_rows | Count of rows triggering the rule |
| message | Human-readable summary |
| checked_at | UTC timestamp of check |

### audit.study_runs
| Column | Description |
|--------|-------------|
| run_id | Deterministic hash-based run identifier |
| run_timestamp | UTC timestamp |
| config_json | JSON-serialised StudyConfig |
| n_enrolled | Number of patients in final cohort |
| n_with_outcome | Number with primary outcome |

### audit.cohort_attrition
| Column | Description |
|--------|-------------|
| run_id | FK → study_runs.run_id |
| step_number | Attrition step order |
| rule_label | Description of the rule applied |
| patients_remaining | N after applying this rule |
| patients_removed | N removed by this rule |
| pct_retained | % retained relative to prior step |

### audit.generated_sql
| Column | Description |
|--------|-------------|
| label | Statement label |
| sql_text | Full SQL text executed |
| created_at | UTC timestamp |

### audit.assumption_log
| Column | Description |
|--------|-------------|
| context | Module or process that logged the assumption |
| assumption_text | Plain-text assumption description |
| created_at | UTC timestamp |
