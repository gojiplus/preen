# Usage Guide

Preen has six commands:

- `preen new NAME` — scaffold a new package from the py-canon copier template
- `preen adopt [PATH]` — retrofit an existing repo onto the template
- `preen update [PATH]` — pull the latest template changes (`copier update`)
- `preen check [PATH]` — run conformance checks (detection only)
- `preen fix [CHECK]` — apply fixes for detected issues
- `preen release [X.Y.Z]` — guided tag-driven release

## Scaffolding: `preen new`

```bash
preen new my-package --description "Does a thing" --cli
```

Runs copier against `gh:gojiplus/py-canon` and creates `my-package/`.
Anything you don't pass as a flag (`--org`, `--description`, `--cli`),
copier prompts for.

## Adoption: `preen adopt`

```bash
cd my-existing-package
preen adopt
```

Mines the copier answers from the repo itself, renders the template into a
temp directory, and copies in only the managed files (workflow shims,
`docs/conf.py`, `.copier-answers.yml`, `py.typed`, and — only if absent —
pre-commit config, dependabot config, `LICENSE`, `CITATION.cff`). Rewrites
`[tool.ruff]`, `[tool.pyright]`, `[tool.pydoclint]` in `pyproject.toml`
to the standard — preserving repo-specific ruff ignore codes by merging
them into the canon list, and deriving `target-version` from the repo's
`requires-python` floor (falling back to py311) — and deletes legacy
`[tool.black]`, `[tool.isort]`, `[tool.flake8]`, `[tool.mypy]` sections.
Ends with an adoption report of what was written, skipped, and left for
you.

Add `--release-migration` to convert the build backend to the fleet's current
`uv_build` series with an explicit project version. The minimum is the latest
tested release and the upper bound prevents an unreviewed backend-series upgrade.
A legacy dynamic version is recovered from the latest `v*` tag.

## Staying current: `preen update`

```bash
preen update
```

Runs `copier update` for a repo with a `.copier-answers.yml`, merging
template changes with conflict markers inline, and prints the changed files.

## Checking: `preen check`

```bash
preen check            # human-readable report
preen check --strict   # exit 1 on critical/important issues (CI)
preen check --only ruff --only template
preen check --explain  # why each issue matters
```

`--strict` gates on critical and important issues (and check errors);
info-level issues never fail CI. Checks listed in `[tool.preen]`
`skip_checks` are skipped unless named in an explicit `--only`.

## Fixing: `preen fix`

```bash
preen fix              # fix everything, interactively
preen fix ruff --auto  # auto-apply ruff fixes
```

## Releasing: `preen release`

```bash
preen release            # uses project.version
preen release 1.2.0      # tag v1.2.0
preen release --dry-run  # show the plan (fully non-interactive)
```

Runs the checks, walks through any issues (critical issues block; important
ones can be overridden with informed consent), then gates the tag on four
things: the version must be PEP 440-valid, it must match the committed
`project.version`, the `vX.Y.Z` tag must not already exist, and `CHANGELOG.md`
must contain an entry for the version.
If there's no entry but a non-empty `[Unreleased]` section, preen offers to
rename it to `[X.Y.Z] - <date>` and commits that rename (only
`CHANGELOG.md`) before tagging, so the tagged commit contains the entry.
Then it creates and pushes the tag; the push triggers the repo's release
workflow: build, attestations, PyPI trusted publishing, GitHub Release.
The rename commit itself stays local — run `git push` afterwards so it is
reachable from your branch.

## Configuration

Optional `[tool.preen]` section in `pyproject.toml`:

```toml
[tool.preen]
src_layout = true
tests_at_root = true
examples_at_root = true
skip_checks = ["links"]
```
