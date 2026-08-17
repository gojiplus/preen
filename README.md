# preen

[![PyPI version](https://img.shields.io/pypi/v/preen.svg)](https://pypi.org/project/preen/)
[![Downloads](https://static.pepy.tech/badge/preen)](https://pepy.tech/project/preen)
[![CI](https://github.com/gojiplus/preen/actions/workflows/ci.yml/badge.svg)](https://github.com/gojiplus/preen/actions/workflows/ci.yml)
[![Documentation](https://github.com/gojiplus/preen/actions/workflows/docs.yml/badge.svg)](https://gojiplus.github.io/preen/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Preen is the conformance-and-adoption CLI for the
[py-canon](https://github.com/gojiplus/py-canon) fleet standard. py-canon
defines the standard — a copier template, reusable GitHub workflows, and
shared Sphinx configuration. Preen is how repos enter the fleet and stay in
it: it scaffolds new packages, retrofits existing ones, pulls template
updates, checks conformance, and cuts tag-driven releases.

preen itself requires Python >=3.12, stricter than the >=3.11 floor of the
fleet standard it enforces on other repos — the tool can hold itself to a
higher bar than the standard it applies.

## Install

```bash
uv tool install preen   # or: pipx install preen
```

## Use with Claude Code

```
/plugin marketplace add gojiplus/preen
/plugin install preen@gojiplus
```

The bundled skill teaches Claude Code to reach for the preen CLI —
scaffolding, adoption, checks, and releases — instead of reimplementing
its logic.

## Commands

| Command | What it does |
|---|---|
| `preen new NAME` | Scaffold a new package from the py-canon copier template |
| `preen adopt [PATH]` | Retrofit an existing repo: mine answers from the repo, copy in the managed files, rewrite `[tool.*]` in pyproject.toml |
| `preen update [PATH]` | Pull the latest template changes into an adopted repo (`copier update`) |
| `preen check [PATH]` | Run conformance checks (detection only); `--strict` for CI |
| `preen fix [CHECK]` | Apply fixes for issues the checks found |
| `preen release [X.Y.Z]` | Guided release: run checks, confirm, `git tag vX.Y.Z`, push — the tag triggers the release workflow |

### Adopting an existing repo

```bash
cd my-package
preen adopt
# review the ADOPTION REPORT, then:
uv lock && uv sync --all-groups
preen check
```

`preen adopt` mines the copier answers from the repo itself (name,
description, and authors from `pyproject.toml`; org from the git remote),
renders the template into a temp directory, and copies in **only the managed
files**: the CI/docs/release workflow shims, `.pre-commit-config.yaml` and
dependabot config (if absent), `docs/conf.py` (old one backed up),
`.copier-answers.yml`, `py.typed`, plus `LICENSE` and `CITATION.cff` if
missing. It rewrites the `[tool.ruff]` (preserving any repo-specific lint
ignores already present, and setting `target-version` from the repo's own
`requires-python` floor, falling back to `py311`), `[tool.pyright]`, and
`[tool.pydoclint]` sections to the standard with tomlkit (comments elsewhere
survive) and deletes legacy `[tool.black]`, `[tool.isort]`, `[tool.flake8]`,
and `[tool.mypy]` sections.

Pass `--release-migration` to also convert the build backend to `uv_build`. An existing
`project.version` is preserved; a legacy dynamic-version project takes its current
version from its latest `v*` tag.

### Checks

`preen check` runs: `template` (copier adoption + drift against the latest
py-canon tag), `ruff`, `tests`, `citation`, `changelog` (Keep a Changelog
structure), `deps` (deptry), `deptree` (circular imports), `depgroups` (PEP
735 dependency-groups usage), `audit` (pip-audit over the locked
dependencies), `ci-matrix` (canon shim, or a matrix covering the
requires-python floor), `structure`, `version` (hardcoded version strings),
`license` (PEP 639 license metadata), `links`, `metadata` (requires-python
upper bound, PEP 561 `py.typed`), `pydoclint`, `pyright`, and `codespell`.

Issues carry an impact level: **critical** blocks release, **important** can
be overridden with informed consent, **info** is advisory. `preen release`
walks that ladder interactively before tagging. Most checks are
detection-only; `preen fix license` migrates the deprecated
`{ text = ... }` license table form to an SPDX string where the mapping is
unambiguous, drops redundant `License ::` classifiers, and adds a missing
`license-files` entry.

### Releasing

The fleet standard keeps one explicit version in `pyproject.toml`, set with
`uv version X.Y.Z`; the matching `vX.Y.Z` tag identifies the release. `preen release`
runs the checks, then refuses to proceed
unless the version is PEP 440-valid, the tag doesn't already exist, and
CHANGELOG.md has an entry for it (offering to rename `[Unreleased]` to the
new version and commit that rename if the Unreleased section has content).
It then asks for confirmation, tags `vX.Y.Z`, and pushes the tag; the repo's
release workflow does the rest (build, PEP 740 attestations, PyPI trusted
publishing, GitHub Release). Use `--dry-run` to see the plan without
acting.

## Configuration

Preen reads an optional `[tool.preen]` section in `pyproject.toml`:

```toml
[tool.preen]
src_layout = true       # expect src/ layout (default: true)
tests_at_root = true    # expect tests/ at the repo root (default: true)
skip_checks = ["links"] # checks to skip by default
```

## Notes

- `pydoclint` covers docstring-signature consistency for now; ruff ships
  equivalent `DOC` rules (`[tool.ruff.lint] external = ["DOC"]` reserves
  the codes), but they're still preview-only, so `pydoclint` stays until
  ruff stabilizes them.
- `codespell` stays: ruff has no spelling-check rules.

## License

MIT
