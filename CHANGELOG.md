# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
