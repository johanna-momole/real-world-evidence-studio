# Release Checklist

Work through this list before tagging a release.

---

## Code quality

- [ ] `ruff check .` — zero errors
- [ ] `ruff format --check .` — zero differences
- [ ] `pytest tests/ -v` — all tests pass
- [ ] No `.duckdb` files, Synthea CSVs, or secrets in the commit tree
  ```bash
  git ls-files | grep -E '\.(duckdb|csv|env)$'  # should return nothing tracked
  ```

## Documentation

- [ ] `README.md` implementation status table updated
- [ ] `docs/future_roadmap.md` reflects completed items (move them to a
  "Completed" section or remove)
- [ ] `CLAUDE.md` still accurate for the new state of the codebase

## Version bump

- [ ] `src/evidence_studio/__init__.py` — `__version__` updated
- [ ] `pyproject.toml` — `version` updated to match

## Final review

- [ ] `app.py` — sidebar shows correct version
- [ ] Evidence brief shows correct version in reproducibility section
- [ ] All 8 Streamlit pages load without errors on an empty database
- [ ] All 8 Streamlit pages load and show data after a full pipeline run

## Tagging

```bash
git tag -a v<version> -m "Release v<version>"
git push origin v<version>
```

Replace `<version>` with the new version number (e.g., `1.1.0`).

---

> Do not push to the remote or create a GitHub release until all items above
> are checked.
