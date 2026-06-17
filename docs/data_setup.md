# Data Setup — Source CSV Files

## Overview

The RWE Studio ingests synthetic EHR data in CSV format and supports two data
modes. No real patient data is used or required.

| Mode | Description | Java required? |
|------|-------------|---------------|
| **Option A — Official Synthea** (preferred) | Output from the Synthea open-source patient simulator (MITRE Corporation). Uses validated disease modules. | Yes (Java 11+) |
| **Option B — Custom demo generator** | Output from `scripts/generate_demo_data.py`, a Python script bundled with this project. Uses simplified demonstration logic only. | No |

> **Important:** The custom demo generator does **not** reproduce Synthea's
> disease modules, clinical logic, prevalence rates, prescribing patterns, or
> outcome distributions. It exists to exercise application code paths without
> requiring Java. Data-quality checks confirm structural consistency only —
> they do **not** validate clinical realism. Demo metrics (cohort sizes, ED
> rates, subgroup findings, regression coefficients) are not scientific
> findings and must not be presented as expected or representative results.

---

---

## Option A — Official Synthea (preferred)

### Step 1 — Download and build Synthea

Synthea requires Java 11 or later.

```bash
# Clone the Synthea repository
git clone https://github.com/synthetichealth/synthea.git
cd synthea

# Build the JAR
./gradlew build check -x test
```

---

### Step 2 — Generate a patient population

The following command generates approximately 500 synthetic patients with
the default disease modules (including diabetes and cardiovascular disease)
and exports CSV files to the output directory.

```bash
java -jar build/libs/synthea-with-dependencies.jar \
  -p 500 \
  --exporter.csv.export=true \
  --exporter.hospital.fhir.export=false \
  --exporter.fhir.export=false
```

For a larger population (recommended for the logistic regression to have
adequate outcome events), use `-p 2000` or higher.

**Important parameters for this study:**
- Use `-p 1000` or more to ensure enough GLP-1 initiators.
- The diabetes module is enabled by default and generates type 1 and
  type 2 diabetes patients as well as GLP-1 prescriptions.

---

### Step 3 — Locate the output files

By default, Synthea writes CSV files to:

```
synthea/output/csv/
```

You will see files such as:

```
patients.csv
encounters.csv
conditions.csv
medications.csv
observations.csv
procedures.csv
allergies.csv
immunizations.csv
careplans.csv
devices.csv
supplies.csv
payers.csv
payer_transitions.csv
organizations.csv
providers.csv
```

---

### Step 4 — Place CSV files in the project

Copy (do not move) the CSV files into the project data directory:

```bash
cp synthea/output/csv/*.csv /path/to/rwe-studio/data/raw/
```

On Windows:

```powershell
Copy-Item "synthea\output\csv\*.csv" "data\raw\"
```

The five required files are:

| File | Contents |
|------|---------|
| `patients.csv` | Demographics and vital status |
| `encounters.csv` | All clinical visits and encounter classes |
| `conditions.csv` | Diagnoses and problem-list entries |
| `medications.csv` | Prescription records with start and stop dates |
| `observations.csv` | Lab results, vitals, and measurements |

The remaining files are optional. The application will discover and load any
CSV file present in the directory.

---

### Step 5 — Ingest into DuckDB

```bash
# Activate the project virtual environment first
.venv/Scripts/activate    # Windows
source .venv/bin/activate # macOS / Linux

# Install the package if not already done
pip install -e ".[dev]"

# Run ingestion — mark source as official Synthea
evidence-studio ingest --data-dir data/raw --data-source official_synthea
```

Ingestion is idempotent. Running it again on the same files replaces the
existing tables and records a new entry in the data manifest.

---

### Step 6 — Verify data quality

```bash
# Show DQ results
evidence-studio dq-report
```

Or open the **Data Quality** page in the Streamlit app.

---

### Notes

- All data is synthetic and contains no real patient information.
  Do not treat any output as real clinical evidence.
- The population size affects the probability of finding GLP-1 initiators.
  The default 100-patient population is usually too small; use at least 500.
- Synthea's GLP-1 prescriptions are controlled by the diabetes management
  module. With a large enough population the studio will find semaglutide,
  liraglutide, dulaglutide, and exenatide records; tirzepatide may not
  appear in older Synthea versions.
- Generated data files and the DuckDB database are excluded from Git via
  `.gitignore`. Never commit them.

---

## Option B — Custom demo generator (no Java required)

The project ships a Python generator at `scripts/generate_demo_data.py` that
produces CSV files in the same column format as Synthea. Use this when you
want to run the full application pipeline without installing Java.

### What it is

- A standalone Python script that generates deterministic synthetic patient
  records using simplified, hard-coded demonstration probabilities.
- Produces only the five required CSV files: `patients`, `encounters`,
  `conditions`, `medications`, `observations`.
- Uses `random.seed(42)` by default for reproducibility.

### What it is NOT

- It is **not** Synthea. It does not use Synthea's Java engine, disease
  modules, or population modelling.
- It does **not** reproduce Synthea's disease prevalence, incidence,
  prescribing sequences, clinical transitions, or outcome distributions.
- Data-quality checks passing confirms CSV structure only, not clinical realism.

### Usage

```bash
# Basic usage — writes to data/raw/ by default
python scripts/generate_demo_data.py --output-dir data/raw

# Specify seed, population size, and force-overwrite
python scripts/generate_demo_data.py --output-dir data/raw --seed 42 \
    --population 2000 --force

# Ingest — always use custom_synthetic_demo for this data source
evidence-studio ingest --data-dir data/raw --data-source custom_synthetic_demo
```

### Important warnings

- Do not present demo metrics (cohort sizes, ED rates, regression
  coefficients) as expected, representative, or scientifically valid results.
- The generator's outcome probabilities (~35% follow-up ED rate) are
  arbitrary demonstration targets, not epidemiological estimates.
- Do not compare results from this generator directly to results from
  official Synthea output; the populations are generated by different logic.

---
