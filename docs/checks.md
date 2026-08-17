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

### `runtime-assets`

Packaged runtime data must carry a schema. Tabular data uses Parquet;
structured records may use Protobuf. CSV, TSV, compressed variants, and opaque
archives inside import packages are critical failures. Serialized model files
are also critical: publish them on Hugging Face and resolve them at runtime.
Modules that access Hugging Face must declare a revision pinned to the full
40-character commit SHA.

### `version`

`project.version` is authoritative and the matching Git tag identifies a release.
Literal `__version__ = "..."` assignments and other copies are flagged; runtime code
should read installed package metadata.

### `changelog`

`CHANGELOG.md` follows Keep a Changelog structure. Important if the file is
missing, or has neither a `## [Unreleased]` heading nor a version heading.
Info if version headings exist but there's no `[Unreleased]` section.
`preen release` refuses to tag without a changelog entry for the release.

### `license`

`[project.license]` follows PEP 639. Important: no `license` at all; the
deprecated `{ text = ... }` / `{ file = ... }` table form; a string value
that isn't a structurally valid SPDX expression; redundant `License ::`
trove classifiers alongside `license`. Info: an SPDX identifier outside
preen's allowlist (advisory — verify at spdx.org), or a missing
`license-files` when a `LICENSE`/`LICENCE`/`COPYING` file exists at the repo
root. `preen fix license` migrates unambiguous table-form values to an SPDX
string, drops the redundant classifiers, and adds `license-files`.

### `metadata`

Two independent pyproject.toml checks. `requires-python`: important if it
has an upper bound (`<`, `<=`, `==`, `===`, `~=`), which caps installs on
future Pythons for no benefit (sp-repo-review PP004); info if it's absent
entirely. `py.typed`: important if `[tool.pyright]` or `[tool.mypy]` is
configured but the package directory has no PEP 561 `py.typed` marker. No
auto-fix for either.

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

### `depgroups`

PEP 735 `[dependency-groups]` usage. Important: no `[dependency-groups]`
section; one with no `dev` group; a dev-type extra (`test`, `docs`, `lint`,
etc.) left in `[project.optional-dependencies]` instead of
`[dependency-groups]`. Info: a name defined in both sections. No auto-fix —
move entries manually or with `uv add --group`.

### `audit`

Known vulnerabilities in locked dependencies, via `pip-audit` over a `uv
export --all-groups` of the project. Important: a locked package has a
known vulnerability (reports the CVE/GHSA ids and a fix version when
pip-audit has one). Info: a dependency pinned via a direct git/file/URL
reference, which `pip-audit --disable-pip` can't hash-verify and so is
skipped rather than scanned. Skips entirely (info, non-blocking) if there's
no `uv.lock`, `uv export` fails, or `pip-audit` isn't installed. No
auto-fix — bumping a vulnerable dependency needs manual review.

## Documentation

### `links`

Dead links in README and docs.

## Running subsets

```bash
preen check --only template --only ci-matrix
preen check --skip links
```
