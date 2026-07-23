# preen

[![PyPI version](https://img.shields.io/pypi/v/preen.svg)](https://pypi.org/project/preen/)
[![CI](https://github.com/gojiplus/preen/actions/workflows/ci.yml/badge.svg)](https://github.com/gojiplus/preen/actions/workflows/ci.yml)
[![Documentation](https://github.com/gojiplus/preen/actions/workflows/docs.yml/badge.svg)](https://gojiplus.github.io/preen/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Preen is the conformance-and-adoption CLI for the
[py-canon](https://github.com/gojiplus/py-canon) fleet standard. py-canon
defines the standard — a copier template, reusable GitHub workflows, and
shared Sphinx configuration. Preen is how repos enter the fleet and stay in
it: it scaffolds new packages, retrofits existing ones, pulls template
updates, checks conformance, and cuts tag-driven releases.

## Install

```bash
uv tool install preen   # or: pipx install preen
```

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
missing. It rewrites the `[tool.ruff]`, `[tool.pyright]`, and
`[tool.pydoclint]` sections to the standard with tomlkit (comments elsewhere
survive) and deletes legacy `[tool.black]`, `[tool.isort]`, `[tool.flake8]`,
and `[tool.mypy]` sections.

Pass `--release-migration` to also convert the build backend to hatchling +
uv-dynamic-versioning, so the git tag becomes the version.

### Checks

`preen check` runs: `template` (copier adoption + drift against the latest
py-canon tag), `ruff`, `tests`, `citation`, `deps` (deptry), `deptree`
(circular imports), `ci-matrix` (canon shim, or a matrix covering the
requires-python floor), `structure`, `version` (hardcoded version strings),
`links`, `pydoclint`, `pyright`, and `codespell`.

Issues carry an impact level: **critical** blocks release, **important** can
be overridden with informed consent, **info** is advisory. `preen release`
walks that ladder interactively before tagging.

### Releasing

The fleet standard derives versions from git tags (uv-dynamic-versioning) —
no bump commits. `preen release` runs the checks, asks for confirmation,
then tags `vX.Y.Z` and pushes the tag; the repo's release workflow does the
rest (build, PEP 740 attestations, PyPI trusted publishing, GitHub Release).
Use `--dry-run` to see the plan without acting.

## Configuration

Preen reads an optional `[tool.preen]` section in `pyproject.toml`:

```toml
[tool.preen]
src_layout = true       # expect src/ layout (default: true)
tests_at_root = true    # expect tests/ at the repo root (default: true)
skip_checks = ["links"] # checks to skip by default
```

## License

MIT
