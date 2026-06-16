# OMOP Mapping — Real-World Evidence Studio

> This document describes an illustrative, non-validated OMOP-aligned
> demonstration layer. It is **not** a fully compliant OMOP Common Data Model
> implementation. No vocabulary mapping has been performed using official OHDSI
> vocabulary files.

---

## Purpose

The OMOP layer demonstrates how Synthea source data can be organised into an
OMOP-like structure. It is intended for educational use only.

---

## Tables implemented

| OMOP table | Source Synthea table(s) | Status |
|-----------|------------------------|--------|
| `person` | `standardized.patients` | Illustrative |
| `observation_period` | `standardized.encounters` (derived) | Illustrative |
| `visit_occurrence` | `standardized.encounters` | Illustrative |
| `condition_occurrence` | `standardized.conditions` | Illustrative |
| `drug_exposure` | `standardized.medications` | Illustrative |
| `measurement` | `standardized.observations` (numeric) | Illustrative |

---

## Concept mapping decisions

| Field | Value used | Reason |
|-------|-----------|--------|
| All `concept_id` fields | `0` | No official OHDSI vocabulary file was loaded. Concept ID 0 is the OMOP standard for unmapped concepts. |
| `visit_concept_id` | Derived from encounter_class using local mapping (see below) | Synthea encounter classes are not SNOMED codes |
| `condition_type_concept_id` | `0` | Not mapped |
| `drug_type_concept_id` | `0` | Not mapped |

### Encounter class → visit_concept_id mapping (local, not validated)

| Synthea encounter_class | Approximate OMOP concept | local_concept_id used |
|------------------------|-------------------------|-----------------------|
| emergency | Emergency Room Visit | 0 (unmapped) |
| inpatient | Inpatient Visit | 0 (unmapped) |
| ambulatory / outpatient | Outpatient Visit | 0 (unmapped) |
| wellness | Outpatient Visit | 0 (unmapped) |
| urgentcare | Emergency Room and Inpatient Visit | 0 (unmapped) |

---

## Source values preserved

All OMOP tables retain the original Synthea codes and descriptions in
`_source_value` and `_source_concept_id` columns. This allows:
- Audit of the original Synthea content
- Future proper mapping against official OHDSI vocabularies

---

## To produce a validated OMOP extract

A production-grade OMOP CDM implementation would require:

1. Download the OMOP vocabulary files from [Athena](https://athena.ohdsi.org/).
2. Load `CONCEPT.csv`, `CONCEPT_RELATIONSHIP.csv`, and related files into DuckDB.
3. Map Synthea SNOMED condition codes, RxNorm medication codes, and LOINC
   observation codes to standard OMOP concept IDs.
4. Replace all `concept_id = 0` values with the appropriate standard concept IDs.
5. Validate against the OMOP CDM conformance tests.

This is out of scope for V1 of this portfolio project.

---

## Known limitations

- Concept ID 0 is used universally — the layer cannot be used with OHDSI
  analytical tools (ATLAS, HADES) that depend on standard concept mapping.
- `observation_period` is approximated from the first and last encounter dates;
  it does not account for gaps in care or insurance eligibility.
- `person_id` is derived directly from Synthea `Id`; uniqueness is assumed.
- Measurement values are stored as text in Synthea's observation VALUE column;
  numeric parsing may fail for non-numeric values.

---

*See [limitations.md](limitations.md) for the full project limitations discussion.*
