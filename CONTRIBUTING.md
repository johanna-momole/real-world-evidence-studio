# Contributing

Thank you for your interest in improving the Real-World Evidence Studio.

---

## What this project is

A portfolio and educational project. Contributions that add realistic complexity,
improve transparency, or demonstrate clinical informatics best practices are
most welcome. Contributions that simplify away important nuance (e.g., removing
the disclaimer, hardcoding expected results) are not.

---

## Before you open a pull request

1. **Read [CLAUDE.md](CLAUDE.md)** — it contains the project's engineering rules
   and prohibitions (no cloud infra, no dbt, no REST API in V1, etc.).
2. **Check [docs/future_roadmap.md](docs/future_roadmap.md)** — your idea may
   already be tracked.
3. **Open an issue first** for anything non-trivial, so we can align on scope
   before you invest time coding.

---

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

---

## Code style

All Python must pass `ruff check .` and `ruff format --check .` with no errors.
Run before committing:

```bash
ruff format .
ruff check . --fix
```

Key style rules enforced by ruff:

- `from __future__ import annotations` in every module
- `pathlib.Path` for all file paths (no hardcoded separators)
- Type hints on all public functions and methods
- One-line docstrings on all public functions
- No comments that explain *what* the code does — only *why* when non-obvious

---

## Tests

Every new feature or bug fix must include tests.

```bash
pytest tests/ -v
```

Rules:
- No mocking of DuckDB — use real connections against `tmp_path` databases.
- Test the empty-database case for every new analysis or UI function.
- Tiny synthetic CSV rows may be added to `tests/fixtures/`.
- Full Synthea datasets and `.duckdb` files must never be committed.

---

## SQL changes

- All SQL that accepts user input must use parameterized queries (`?` placeholders).
- Never interpolate unsanitized values into SQL strings.
- Business logic belongs in `src/evidence_studio/` modules, not in Streamlit page files.
- Keep baseline feature SQL free of post-index information (no look-ahead).

---

## Disclaimers

Any new output surface (page, download, export) must carry the mandatory disclaimer:

> **Synthetic data only.** All results in this application are derived from
> Synthea-generated synthetic records. They do not represent real patients,
> clinical outcomes, treatment effectiveness, drug safety, or incidence rates.
> This project must not be used for clinical decisions, regulatory submissions,
> or public health reporting.

---

## Commit messages

Use the present tense, active voice, one line:

```
Add attrition waterfall hover template
Fix subgroup column name mismatch in results page
Test: add empty-DB case for missingness_summary
```

---

## Pull request checklist

- [ ] `ruff check .` passes
- [ ] `ruff format --check .` passes
- [ ] `pytest tests/ -v` passes
- [ ] New public functions have type hints and a one-line docstring
- [ ] New output surfaces carry the synthetic-data disclaimer
- [ ] No Synthea CSVs, `.duckdb` files, or secrets committed
- [ ] `CONTRIBUTING.md` or `docs/future_roadmap.md` updated if relevant
