---
name: preen
description: Use when creating a new Python package, standardizing or retrofitting an existing Python repo onto a shared conformance standard, running pre-release hygiene or package health checks, releasing a Python package, or fixing packaging metadata (license, dependency groups, CI matrix, citation). Wraps the preen CLI, the py-canon fleet-standard tool — it stays the single source of truth for checks and fixes.
---

# preen

Conformance-and-adoption CLI for the py-canon fleet standard. Drive it via
the CLI; do not reimplement its checks or fixes by hand.

## Availability

- `uv tool install preen` — install once, use everywhere.
- `uvx preen …` — one-off run with no persistent install.
- `pip install preen` — fallback if `uv` isn't available.

## Command map

- `preen new NAME [--org ORG] [--description TEXT] [--cli/--no-cli]` —
  scaffold a new package from the py-canon copier template.
- `preen adopt [PATH] [--release-migration]` — retrofit an existing repo
  onto the template: mines answers from `pyproject.toml` and the git
  remote, copies in only the managed files, rewrites `[tool.ruff]`,
  `[tool.pyright]`, `[tool.pydoclint]` to the standard. `--release-migration`
  also converts the build backend to hatchling + uv-dynamic-versioning
  (tag-derived version).
- `preen update [PATH]` — pull the latest template changes into an
  already-adopted repo.
- `preen check [PATH] [--strict] [--explain] [--skip CHECK] [--only CHECK]`
  — run conformance checks; detection only, never modifies files.
  `--strict` exits 1 on any issue (use in CI). `--explain` prints why each
  issue matters.
- `preen fix [CHECK_NAME] [--path PATH] [--auto] [--interactive/--batch]`
  — apply fixes for issues `check` found. Omit `CHECK_NAME` to fix
  everything fixable; `--auto` skips the per-fix prompts.
- `preen release [VERSION] [--path PATH] [--skip-checks] [--dry-run]` —
  interactive tag-driven release: run checks, confirm, `git tag vX.Y.Z`,
  push. `--dry-run` shows the plan without acting.

## Workflow

1. On any existing repo, run `preen check` first, before making any other
   change. Don't guess at conformance — check it.
2. Read the impact level on each issue: **critical** blocks release,
   **important** can be overridden with informed human consent, **info**
   is advisory. `preen release` walks this ladder interactively before
   tagging — let it.
3. Prefer fixing the root cause. For mechanical fixes, run
   `preen fix CHECK_NAME` (e.g. `preen fix license`) rather than hand-editing.
4. Never hand-edit files carrying a copier "managed by / do not edit"
   header (e.g. `.copier-answers.yml`, CI/docs shims copied in by
   `adopt`/`update`). Run `preen update` to pull template changes instead.
5. Never hand-bump a version string. The git tag is the version
   (uv-dynamic-versioning) — `preen release` tags and pushes, and refuses
   to proceed without a CHANGELOG.md entry for the release (it offers to
   rename `[Unreleased]` to the new version when that section has content).
6. After `preen adopt`, read the printed ADOPTION REPORT, then run
   `uv lock && uv sync --all-groups` before running `preen check`.

## Configuration

Optional `[tool.preen]` table in `pyproject.toml`:

```toml
[tool.preen]
src_layout = true        # expect src/ layout (default: true)
tests_at_root = true     # expect tests/ at repo root (default: true)
examples_at_root = true  # expect examples/ at repo root (default: true)
skip_checks = []         # check names to skip by default
```

## Do not

- Do not reimplement preen's checks by hand (ruff, pyright, pydoclint,
  pip-audit, license/changelog/dependency-group rules, etc.) — run the CLI
  and act on its output.
- Do not bypass a `--strict` failure by deleting or disabling the check;
  if a check genuinely doesn't apply, that's a `skip_checks` entry made
  with the human's sign-off, stated explicitly.
- Do not resolve ambiguous license or dependency decisions yourself —
  escalate to the human.
