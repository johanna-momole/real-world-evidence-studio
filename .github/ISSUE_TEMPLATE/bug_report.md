---
name: Bug report
about: Something is broken or produces incorrect results
labels: bug
---

## Describe the bug

A clear, concise description of what is wrong.

## Steps to reproduce

1. Run `evidence-studio ingest --data-dir ...` (if applicable)
2. Open page: ...
3. Click / select ...
4. See error / wrong result

## Expected behavior

What should happen.

## Actual behavior

What actually happens. Include the full error traceback if one appears.

## Environment

- OS: (e.g., Windows 11, macOS 14, Ubuntu 22.04)
- Python version: (`python --version`)
- Package version: (`pip show evidence-studio`)
- DuckDB version: (`python -c "import duckdb; print(duckdb.__version__)"`)
- Synthea data size (approximate number of patients):

## Additional context

Paste any relevant log output, screenshots, or the contents of
`audit.assumption_log` or `audit.study_runs` if the bug is in the pipeline.

> **Reminder:** Do not paste real patient data. This project uses Synthea
> synthetic data only.
