# Available Checks

Every issue a check reports carries an impact level:

- **critical** — blocks release (`preen release` refuses to proceed)
- **important** — should be fixed, but can be overridden with informed consent
- **info** — advisory

## Fleet conformance

### `template`

Copier adoption and drift. Critical if the repo has no
`.copier-answers.yml`. Important if `_commit` is not a release tag at all — a
mangled value like `v1.0.1.0.1`, a `git describe` string like
`v1.2.0-3-gabc1234`, or a bare SHA — since `copier update` cannot resolve any
of them. Important if it records a moving major tag like `v1`,
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

The Python versions CI actually runs must cover the `requires-python` floor.
For a canon shim (one calling
`gojiplus/py-canon/.github/workflows/reusable-ci.yml`) that means the
`python-versions` input if the shim passes one, and otherwise the reusable
workflow's own default, fetched from the ref on the `uses:` line. Important
when a version below the floor is in the matrix — that leg cannot resolve and
`uv sync` exits 2. A floor that is merely never run is advisory on a shim,
since the matrix came from py-canon rather than from the repo; on a
hand-written matrix it stays important. When the reusable workflow cannot be
fetched, the comparison is skipped with an info note rather than reported as
verified.

### `citation`

`CITATION.cff` exists, parses as YAML, and has the core CFF keys. Its `version`
must match `project.version`: important when the two disagree, info when the
key is absent. `preen fix citation` rewrites the version line in place, leaving
the rest of a hand-written file alone.

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

A file that `[tool.uv.build-backend]` keeps out of the wheel — via
`source-exclude` or `wheel-exclude` — is reported at info instead: nothing
installs it, so it is source-tree hygiene rather than a packaging defect.
Unlike the scanning checks, this one ignores `[tool.ruff]` excludes: whether a
file ships in the wheel is not a question a lint setting gets to answer.

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

### `pytest-config`

pytest is configured to fail on what it should fail on: `minversion`,
`testpaths`, `log_level`, `xfail_strict`, `filterwarnings`, and `-ra`,
`--strict-config`, `--strict-markers` in `addopts` (sp-repo-review
PP301–PP309). Without `filterwarnings`, a DeprecationWarning from a dependency
is invisible until the release that removes the API; without
`--strict-markers`, a typo in a marker name silently selects nothing.

**Informational throughout, for now.** py-canon's template ships only
`testpaths`, so gating here would fail every repo in the fleet at once. `preen
fix pytest-config` writes the settings; the grade can rise once the template
carries them.

### `metadata`

Three independent pyproject.toml checks. `build-system`: important if an
existing table does not use the fleet's current `uv_build` requirement and
backend exactly; `preen adopt --release-migration` applies that standard.
`requires-python`: important if it has an upper bound (`<`, `<=`, `==`, `===`,
`~=`), which caps installs on future Pythons for no benefit (sp-repo-review
PP004); info if it's absent entirely. `py.typed`: important if `[tool.pyright]`
or `[tool.mypy]` is configured but the package directory has no PEP 561
`py.typed` marker.

The file is also validated against PyPA's own schemas with
`validate-pyproject` before any of that: critical if it fails, since every
other check reads this file by key lookup and cannot otherwise tell an absent
key from a misspelled one. Reported alongside the semantic findings rather than
instead of them.

## Code quality

### `ruff`

Lint and format with ruff — the standard's only linter/formatter.

### `pyright`

Type checking in `standard` mode.

### `pydoclint`

Docstring–signature consistency (google style). Important for a docstring that
contradicts its code, informational for the `--arg-type-hints-*` option codes
(DOC106–DOC111), which report a configuration preference rather than a
docstring that misleads a reader. Never critical: a docstring is not a broken
build, and canon's CI runs bare pydoclint as its own gate, so a second veto
here would add no information.

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

Dead links in README and docs, extracted and resolved by lychee. Placeholder
hosts are skipped, as are the RFC 2606 / RFC 6761 reserved names — `.invalid`,
`.test`, `.example`, `.localhost`, `example.com` and friends — which exist
precisely so that they never resolve, so a fixture using one is doing the right
thing.

A repo declares its own known-good endpoints in `[tool.preen] link_ignore`.
Those patterns are regexes, so write them in a TOML literal string
(for example an https pattern written `'https://api\\.example\\.org/.*'`) rather than a basic one; pyproject.toml is
itself scanned, and preen no longer reports a repo's own ignore patterns as
dead links.

A scan that could not run — no lychee binary, a timeout, unreadable output —
reports that fact at info rather than passing silently: no link having been
checked is not the same as every link being healthy.

## Running subsets

```bash
preen check --only template --only ci-matrix
preen check --skip links
```
