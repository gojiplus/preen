# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

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

### Changed

- `preen adopt` merges repo-specific ruff ignores into the canon list
  instead of overwriting them.
- `preen adopt` derives ruff's `target-version` from the target repo's
  `requires-python` floor, falling back to `py311` (the fleet floor) when
  it's absent or unparsable.
- License metadata switched to PEP 639: `license = "MIT"` (SPDX
  expression) plus `license-files`, dropping the redundant
  `License :: OSI Approved :: MIT License` classifier.
