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
to the standard and deletes legacy `[tool.black]`, `[tool.isort]`,
`[tool.flake8]`, `[tool.mypy]` sections. Ends with an adoption report of
what was written, skipped, and left for you.

Add `--release-migration` to convert the build backend to hatchling +
uv-dynamic-versioning (the git tag becomes the version).

## Staying current: `preen update`

```bash
preen update
```

Runs `copier update` for a repo with a `.copier-answers.yml`, merging
template changes with conflict markers inline, and prints the changed files.

## Checking: `preen check`

```bash
preen check            # human-readable report
preen check --strict   # exit 1 on any issue (CI)
preen check --only ruff --only template
preen check --explain  # why each issue matters
```

## Fixing: `preen fix`

```bash
preen fix              # fix everything, interactively
preen fix ruff --auto  # auto-apply ruff fixes
```

## Releasing: `preen release`

```bash
preen release            # prompts for the version
preen release 1.2.0      # tag v1.2.0
preen release --dry-run  # show the plan
```

Runs the checks, walks through any issues (critical issues block; important
ones can be overridden with informed consent), then creates and pushes the
`vX.Y.Z` tag. The tag push triggers the repo's release workflow: build,
attestations, PyPI trusted publishing, GitHub Release.

## Configuration

Optional `[tool.preen]` section in `pyproject.toml`:

```toml
[tool.preen]
src_layout = true
tests_at_root = true
examples_at_root = true
skip_checks = ["links"]
```
