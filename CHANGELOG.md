# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Adopted preen onto its own py-canon template: `.copier-answers.yml`,
  `.pre-commit-config.yaml`, `src/preen/py.typed`, weekly CI drift-check
  schedule.
- Populated `[tool.preen]` with preen's own configuration.

### Changed

- `preen adopt` merges repo-specific ruff ignores into the canon list
  instead of overwriting them.
- `preen adopt` derives ruff's `target-version` from the target repo's
  `requires-python` floor, falling back to `py311` (the fleet floor) when
  it's absent or unparsable.
- License metadata switched to PEP 639: `license = "MIT"` (SPDX
  expression) plus `license-files`, dropping the redundant
  `License :: OSI Approved :: MIT License` classifier.
