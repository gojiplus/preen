# Available Checks

Every issue a check reports carries an impact level:

- **critical** — blocks release (`preen release` refuses to proceed)
- **important** — should be fixed, but can be overridden with informed consent
- **info** — advisory

## Fleet conformance

### `template`

Copier adoption and drift. Critical if the repo has no
`.copier-answers.yml`; important if the recorded `_commit` differs from the
latest py-canon `v*` tag (queried via `git ls-remote`, skipped gracefully
offline).

### `ci-matrix`

Passes if `.github/workflows/ci.yml` is a canon shim (calls
`gojiplus/py-canon/.github/workflows/reusable-ci.yml`). Otherwise the
workflow's test matrix must cover the `requires-python` floor.

### `citation`

`CITATION.cff` exists, parses as YAML, and has the core CFF keys.

### `structure`

Project layout: `tests/` and `examples/` at the repo root, `src/` layout,
no committed `__pycache__` or `.pyc` files.

### `version`

No hardcoded version strings: the git tag is the version, so literal
`__version__ = "..."` assignments (and copies of a static `project.version`)
are flagged.

## Code quality

### `ruff`

Lint and format with ruff — the standard's only linter/formatter.

### `pyright`

Type checking in `standard` mode.

### `pydoclint`

Docstring–signature consistency (google style).

### `codespell`

Common misspellings in code and docs.

## Tests and dependencies

### `tests`

Runs the pytest suite.

### `deps`

Dependency hygiene via deptry (unused/missing/transitive dependencies).

### `deptree`

Circular imports within the package.

## Documentation

### `links`

Dead links in README and docs.

## Running subsets

```bash
preen check --only template --only ci-matrix
preen check --skip links
```
