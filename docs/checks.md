# Available Checks

Every issue a check reports carries an impact level:

- **critical** — blocks release (`preen release` refuses to proceed)
- **important** — should be fixed, but can be overridden with informed consent
- **info** — advisory

## Fleet conformance

### `template`

Copier adoption and drift. Critical if the repo has no
`.copier-answers.yml`. Important if it records a moving major tag like `v1`,
which makes `copier update` compare the tag against itself and no-op — re-run
`preen adopt` to pin the concrete release tag. Drift between the recorded
concrete tag and the latest py-canon `v*` tag (queried via `git ls-remote`,
skipped gracefully offline) is **informational**: the repo did nothing wrong
when the template moves, and gating on it would turn the whole fleet red on
every py-canon release.

### `workflows`

The four canon workflow files (`ci.yml`, `docs.yml`, `release.yml`,
`dependabot-auto-merge.yml`) must be thin callers of py-canon's reusable
workflows, not materialized copies. Important for each file that exists but
does not call the matching `gojiplus/py-canon/.github/workflows/reusable-*`
workflow — a copy stops receiving fleet fixes the moment it is written.

### `ci-matrix`

Passes if `.github/workflows/ci.yml` is a canon shim (calls
`gojiplus/py-canon/.github/workflows/reusable-ci.yml`). Otherwise the
workflow's test matrix must cover the `requires-python` floor.

### `citation`

`CITATION.cff` exists, parses as YAML, and has the core CFF keys.

### `files`

`README` (any of the common spellings) and `.gitignore` exist
(sp-repo-review PY002/PY008). `preen fix files` writes a standard Python
`.gitignore` when it is missing.

### `precommit`

`.pre-commit-config.yaml` exists and parses as YAML. Deliberately does not
police which hooks it configures — CI is the gate; pre-commit is the fast
local echo of it.

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

Three independent pyproject.toml checks. `build-system`: important if an
existing table does not use the fleet's current `uv_build` requirement and
backend exactly; `preen adopt --release-migration` applies that standard.
`requires-python`: important if it has an upper bound (`<`, `<=`, `==`, `===`,
`~=`), which caps installs on future Pythons for no benefit (sp-repo-review
PP004); info if it's absent entirely. `py.typed`: important if `[tool.pyright]`
or `[tool.mypy]` is configured but the package directory has no PEP 561
`py.typed` marker.

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

### `dropped-args`

A parameter the caller accepts and then fails to forward. Function `f` takes
`p` and calls `g`, which also takes `p` and gives it a default; the call omits
`p`, so `g` uses its default and `f`'s `p` reaches nothing. Important, because
the failure is silent: the code runs, the tests pass, and a documented knob
does nothing.

ruff's `ARG001` does not cover this. `ARG001` fires when a parameter is never
read in the body, but here `f` may read `p` elsewhere and the call to `g` has
a valid signature. Only comparing the two signatures shows it.

The check resolves callees by name within the package and skips a name defined
more than once, since a bare call cannot then be attributed with confidence. A
`**kwargs` forward counts as passing everything. No auto-fix: forwarding the
parameter is usually right, but sometimes the callee is meant to use its own
default, and only the author knows which. Mark a deliberate one with `# preen:
allow-dropped-arg` on the call or the line above it.

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
