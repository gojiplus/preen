# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.4.0] - 2026-08-18

### Added

- A template-sync test compares `preen.adopt.CANON_TOOL_TOML` against py-canon's
  `template/pyproject.toml.jinja`, so the two copies of the canonical `[tool.*]`
  configuration can no longer drift silently.

### Changed

- Preen now holds itself to the fleet standard it enforces: CI runs
  `preen check --strict` (`run-preen: true`), and its own
  `.copier-answers.yml` records the concrete `v1.0.1` release tag instead of
  the moving `v1`.
- Documented the `workflows`, `files`, and `precommit` checks in
  `docs/checks.md` and the README check list; they shipped undocumented.

### Fixed

- `preen adopt` now renders the template at the latest concrete `vX.Y.Z` release
  tag and records it in `.copier-answers.yml`. Copier's `git describe` could
  record the moving `v1` tag instead, which made `copier update` compare the tag
  against itself and no-op forever.
- The template check now flags a `.copier-answers.yml` that records a moving
  major tag (`_commit: v1`) as an important issue, even offline.

## [0.3.2] - 2026-08-17

### Changed

- `preen adopt --release-migration` and the metadata check now share one current
  `uv_build>=0.12.5,<0.13` requirement. Existing projects using Hatchling, stale
  `uv_build` series, extra build requirements, or malformed build metadata are
  migrated or reported consistently.
- `preen release` now uses `project.version` when no version is supplied and
  refuses to create a mismatched tag. The bundled coding skill now documents
  the same static-version and `uv_build` policy.

## [0.3.1] - 2026-08-17

### Fixed

- The link check now scans only Git-tracked or non-ignored source and documentation
  files. Local caches and downloaded datasets no longer turn one check into minutes of
  unrelated network probes and hundreds of false failures.

## [0.3.0] - 2026-08-17

### Added

- Added the `runtime-assets` check: runtime tables must use schema-bearing formats,
  serialized model weights must live on Hugging Face, and Hub revisions must be pinned
  to full commit SHAs.

### Fixed

- Replaced the serial, hand-rolled HTTP link checker with `lychee`, which validates
  unique links concurrently and correctly parses legal URL characters. Repository-level
  `link_ignore` patterns cover known-good API bases without disabling link validation.
- `--release-migration` now writes the actual py-canon standard: `uv_build` with an
  explicit project version. It no longer reintroduces Hatchling and
  `uv-dynamic-versioning`.
- The codespell check now scans only tracked or non-ignored prose, code, and config files,
  in bounded batches. Ignored caches and training-data directories no longer produce
  hundreds of thousands of false findings or megabytes of output.

- `preen adopt` no longer clobbers repo-specific configuration. The
  `[tool.ruff]`, `[tool.pyright]` and `[tool.pydoclint]` sections are now
  merged rather than replaced: canon wins on keys it defines, anything it says
  nothing about (`exclude`, `[tool.ruff.lint.flake8-bugbear]`, extra
  per-file-ignore patterns) survives, and `lint.ignore`/`select`/`extend-select`
  plus per-file-ignore code lists union with canon's. Deprecated top-level
  `[tool.ruff]` lint keys are hoisted under `[tool.ruff.lint]`. The adoption
  report gained a "Preserved" section listing everything kept (#13).
- `preen adopt` preserves the CI shim's `with:` inputs. `coverage-floor` is
  mined from an existing `.github/workflows/ci.yml` — so it is also persisted
  to `.copier-answers.yml` instead of being reset to 0 on every `preen update`
  — and any input the template does not render (e.g. `python-versions`) is
  re-applied after the overwrite (#13).
- `preen fix codespell --auto` no longer rewrites data fixtures. Fixes are now
  emitted per file instead of one repo-wide fix, and files outside prose/code
  (`.md`, `.rst`, `.txt`, `.py`) or under `data`/`fixtures`/`testdata`/
  `samples`/`golden` directories are deferred for human review rather than
  applied unattended — a suggestion in a fixture is as likely to be a real
  proper noun (#19).
- The `codespell` check now passes `--toml`, so a repo's `[tool.codespell]`
  configuration is actually honored; codespell reads `setup.cfg`/`.codespellrc`
  but never discovers `pyproject.toml` on its own. The scan target is also
  relative now, so repo-relative `skip` globs match (#19).
- The changelog gate understands PEP 440. Version headings are matched to a
  word boundary and validated with `packaging`, so a `## [0.2.0rc1]` heading no
  longer falsely satisfies a 0.2.0 release, and releasing `1.2.3rc1` matches its
  own heading instead of being forced down the rename path (#14).
- `adopt` derives the `requires-python` floor from `~=` and `==` specifiers, not
  just `>=`, so `~=3.12` no longer understates ruff's `target-version` (#15).
- `preen release` checks whether the tag already exists on origin, failing
  before the changelog is rewritten rather than at push. An unreachable origin
  is treated as unknown, not as a block (#18).
- `preen release` offers to bump `.claude-plugin/plugin.json` to the release
  version and includes it in the release commit, so the hand-written manifest
  stops drifting behind the tags (#18).
- `adopt` resolves `{ include-group = ... }` when checking the dev group, so a
  requirement already provided by an included group is not added a second time
  with a weaker pin (#18).
- The `depgroups` check recognizes `type-check`/`type_check`/`type-checking`
  extra-name variants (#18).
- The `license` check reports an empty `license = {}` table as such instead of
  as `{ file = "None" }`, and its SPDX tokenizer no longer splits identifiers
  that merely begin with `AND`/`OR`/`WITH` (#16).

### Changed

- Expanded the canon ruff rule set from 14 to 34 selectors, adding `PTH`, `RET`,
  `PIE`, `FURB`, `PERF`, `DTZ`, `LOG`, `G`, `TC`, `FLY`, `RSE`, `SLOT`, `FA`,
  `A`, `EXE`, `ICN`, `PGH`, `PLE`, `ARG` and `SLF` (~400 of ruff 0.15's 800
  stable rules, up from ~400 enabled before). `ARG` and `SLF` are ignored under
  `tests/**`.
- Added `W191`, `D206` and `D300` to the canon ignore list. Selecting `W` and
  `D` wholesale enabled three rules ruff's own documentation lists as always
  incompatible with `ruff format`, which the standard also runs.

## [0.2.0] - 2026-07-24

### Added

- Ship Claude Code plugin + skill: `.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, and `skills/preen/SKILL.md`, installable
  via `/plugin marketplace add gojiplus/preen` then
  `/plugin install preen@gojiplus`.
- Raised own test coverage from 54% to 90%; enforce a 70% floor in CI.
- New `metadata` check: flags a `requires-python` upper bound (`<`, `<=`,
  `==`, `===`, `~=` specifiers cap installs on future Pythons for no
  benefit, per sp-repo-review PP004) and, for projects with `[tool.pyright]`
  or `[tool.mypy]` configured, a missing PEP 561 `py.typed` marker in the
  package directory.
- Adopted preen onto its own py-canon template: `.copier-answers.yml`,
  `.pre-commit-config.yaml`, `src/preen/py.typed`, weekly CI drift-check
  schedule.
- Populated `[tool.preen]` with preen's own configuration.
- New `license` check enforcing PEP 639 license metadata (SPDX string form,
  no deprecated `License ::` classifiers, `license-files` present when a
  license file exists), plus `preen fix license` to auto-migrate the
  deprecated `{ text = ... }` table form, remove redundant classifiers, and
  add a missing `license-files` entry.
- New `depgroups` check enforcing PEP 735 `[dependency-groups]` usage:
  flags a missing `[dependency-groups]` section, a missing `dev` umbrella
  group, dev-type extras (test, docs, lint, etc.) left in
  `[project.optional-dependencies]`, and names duplicated across both
  sections.
- New `audit` check running pip-audit over the project's locked dependencies
  (exported via `uv export`) to flag known-vulnerable packages; complements
  `deps`, which doesn't check for CVEs.
- New `changelog` check enforcing Keep a Changelog structure in
  `CHANGELOG.md`; `preen release` now refuses to tag without a PEP 440
  version, a not-already-existing tag, and a changelog entry for the
  release (offering to rename `[Unreleased]` to the new version when
  appropriate).

### Changed

- `[tool.preen] skip_checks` is now honored by `preen check` and the
  `preen release` pre-checks; an explicit `--only` overrides it.
- `preen release`: `--dry-run` is fully non-interactive, the changelog
  rename commit is pathspec-limited to `CHANGELOG.md` (pre-staged files
  stay staged), and a successful tag push reminds you to push the branch
  so the release commit is reachable.
- `preen adopt` merges repo-specific ruff ignores into the canon list
  instead of overwriting them.
- `preen adopt` derives ruff's `target-version` from the target repo's
  `requires-python` floor, falling back to `py311` (the fleet floor) when
  it's absent or unparsable.
- License metadata switched to PEP 639: `license = "MIT"` (SPDX
  expression) plus `license-files`, dropping the redundant
  `License :: OSI Approved :: MIT License` classifier.
- Documented the new checks (`license`, `depgroups`, `audit`, `changelog`,
  `metadata`) and release gates in README.md and docs/checks.md.
