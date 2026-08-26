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
`conf.py`, `.copier-answers.yml`, `py.typed`, and — only if absent —
pre-commit config, dependabot config, `LICENSE`, `CITATION.cff`). Every canon
workflow shim keeps the `with:` inputs the repo set and the template knows
nothing about — `python-versions`, a raised `coverage-floor`, `docs-dir`,
`run-doctests` — and they are listed under Preserved. `conf.py` goes wherever
the repo's docs actually live: the `docs-dir` its docs.yml shim declares, or
whatever directory under `docs/` already holds a `conf.py`. If the file it
replaces carried logic the template does not have, the old copy is kept as
`conf.py.bak` and the overwrite is raised as a Manual TODO with the line count,
rather than reported as a routine write. Rewrites
`[tool.ruff]`, `[tool.pyright]`, `[tool.pydoclint]` in `pyproject.toml`
to the standard — preserving repo-specific ruff ignore codes by merging
them into the canon list, and deriving `target-version` from the repo's
`requires-python` floor (falling back to py311) — and deletes legacy
`[tool.black]`, `[tool.isort]`, `[tool.flake8]`, `[tool.mypy]` sections.

Dependency groups are brought to the template's shape: `test` holds pytest and
pytest-cov, `dev` holds the lint toolchain plus
`{ include-group = "test" }`, and `docs` holds the Sphinx stack. That split is
not cosmetic — the reusable CI installs `test` by name in a clean environment
(`uv pip install dist/*.whl --group test`), so a repo without one fails its
wheel job. A pytest pin already sitting directly in `dev` is dropped, since the
include now provides it.

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

If the merge leaves conflicts, `preen update` exits 1 rather than 0, so a
script cannot walk past an unresolved tree. When the conflict is in
`pyproject.toml`, it also names every `[project]` key the merge would change,
current value first:

```
pyproject.toml: the template is offering to replace [project] metadata
  version
    keep:    '0.8.0'
    offered: '0.1.0'
  dependencies
    keep:    ['pandas', 'pyarrow>=15']
    offered: []
```

The template renders `[project]` from the scaffold answers, so its side of the
merge is always the state the repo had on day one. Taking it would publish an
empty wheel under a version the project released long ago. Keep the current
values; the template's business is the `[tool.*]` configuration.

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
ones can be overridden with informed consent), then gates the tag on five
things: the version must be PEP 440-valid, it must match the committed
`project.version`, the `vX.Y.Z` tag must not already exist locally or on the
remote, `CHANGELOG.md` must contain an entry for the version, and the
**distributions must build and pass `twine check` and `check-wheel-contents`**.

That last gate builds into a temporary directory — a few seconds — and runs
before anything irreversible or interactive. Publishing happens on the tag
push, so without it a bad artifact is discovered only once the tag exists,
which is the expensive place to find it. `--dry-run` runs it too, which makes
the dry run a free build rehearsal. A tool that cannot be fetched (no network)
is skipped rather than treated as a failure; a tool that runs and rejects the
artifact blocks the release.

If there's no changelog entry but a non-empty `[Unreleased]` section, preen
offers to rename it to `[X.Y.Z] - <date>` and commits that rename (only
`CHANGELOG.md`) before tagging, so the tagged commit contains the entry. It
also offers to bump any file carrying a copy of the version that the tag does
not set — `.claude-plugin/plugin.json` and `CITATION.cff` — and includes them
in the same pathspec-limited commit.
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
