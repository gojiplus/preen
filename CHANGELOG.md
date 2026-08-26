# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- `pytest-config` findings gate instead of advising. They shipped
  informational because py-canon's template carried only `testpaths`, so
  gating would have failed every repo in the fleet for following a standard
  that did not ask for this yet. py-canon 1.3.0 ships the whole set, `copier
  update` delivers it, and `preen fix pytest-config` writes it directly.
  Important, never critical — a missing setting is not a broken build. `PP301`,
  no pytest table at all, stays informational: that repo may have no tests.

### Fixed

- `preen fix pytest-config` keeps a string `addopts` a string. Splitting it to
  build a list tore quoted arguments apart: gojiplus/get-weather-data writes
  `addopts = "-v --tb=short -m 'not live'"`, which became
  `["-m", "'not", "live'"]` and sent pytest looking for a test path called
  `live'`. Found by running the fix across all 38 fleet repos before opening
  any pull request.

- `preen adopt --release-migration` fails before it writes anything when it
  cannot derive a version. `_migrate_release` runs last, so a project with a
  dynamic version and no `v*` tag to recover one from got five rewritten
  workflows, four `.bak` files and then an unhandled traceback — half-adopted,
  with `pyproject.toml` untouched and no report. gojiplus/statqa is exactly
  that shape. The precondition is now checked first, and the CLI prints the
  reason and what to do rather than a stack trace.

## [0.5.0] - 2026-08-26

### Added

- A `pytest-config` check for sp-repo-review PP301-PP309: `minversion`,
  `testpaths`, `log_level`, `xfail_strict`, `filterwarnings`, and `-ra`,
  `--strict-config`, `--strict-markers` in `addopts`. Each of these decides
  whether a test run *fails*: without `filterwarnings` a dependency's
  DeprecationWarning is invisible until the release that removes the API,
  and without `--strict-markers` a typo in a marker name silently selects
  nothing. Informational throughout for now -- py-canon's template ships only
  `testpaths`, so gating would fail the whole fleet at once -- with `preen fix
  pytest-config` to write them. preen's own configuration now carries them, and
  the suite passes under `filterwarnings = ["error"]`.

- `preen release` builds the distributions and runs `twine check` and
  `check-wheel-contents` over them before tagging. Publishing happens on the
  tag push, so a bad artifact was previously discovered only once the tag
  existed. The gate runs before anything irreversible or interactive, and in
  `--dry-run` too, which makes the dry run a free build rehearsal. A tool that
  cannot be fetched is skipped; one that runs and rejects the artifact blocks.

- `preen release` offers to bump `CITATION.cff` alongside
  `.claude-plugin/plugin.json`. Both carry a copy of the version that the tag
  does not set, and a stale citation outlives the release in someone else's
  bibliography.

- The `metadata` check validates pyproject.toml against PyPA's own schemas with
  `validate-pyproject`. Every other check reads that file by key lookup, which
  cannot tell an absent key from a misspelled one; the schema pass names the
  difference. Critical, and reported alongside the semantic findings rather
  than instead of them.

- `citation` compares `CITATION.cff`'s `version` against `project.version`:
  important when they disagree, info when the key is absent. A file can parse
  and carry every required key while citing a release from a decade ago, and
  that number is what a citation copies. `preen fix citation` rewrites the
  version line and leaves the rest of the file alone.

- A `dropped-args` check: a parameter the caller accepts and then fails to
  forward, so the callee falls back to its own default and a documented knob
  silently does nothing. ruff's `ARG001` does not cover this shape — it fires
  when a parameter is never read, whereas here the caller reads it and the call
  it makes has a valid signature. One package in the fleet shipped three of
  them, all of which passed their tests, CI, ruff and pyright: a confidence
  level that left one interval at 95% while its neighbour honoured the request,
  a subsampling cap that never reached the routine that subsamples, and a
  coverage simulation whose bootstrap arm reported identical coverage at every
  nominal level. Mark a deliberate drop `# preen: allow-dropped-arg`.

### Fixed

- `preen adopt` keeps a shim's inputs when the shim has comments. The `with:`
  block parser treated the first comment line as the end of the block, so every
  input below it was dropped — and a commented input is precisely the one
  someone thought worth explaining. gojiplus/statqa annotated both of its
  overrides and kept neither: `python-versions: '["3.12","3.13","3.14"]'` went
  entirely, and a deliberate `coverage-floor: 70` was replaced with 0.

- The version check's own test fixtures use an implausible version. preen's
  release bumped `project.version` to 0.5.0, which those fixtures happened to
  contain, so the check reported five hardcoded copies of the project version
  in preen's own suite — correctly, on the evidence available to it. A fixture
  version should be one the project will never carry.

- `check-yield-types = false` follows py-canon's pydoclint config, in the table
  `adopt` writes and in the fallback the `pydoclint` check uses. The standard
  says the signature carries the type and the docstring should not repeat it;
  that applied to `Returns:` and not to `Yields:`, so a generator annotated
  `Iterator[str]` still had to write `str:` again in its prose.

- `pydoclint` judges a repo with no `[tool.pydoclint]` against canon's options
  rather than pydoclint's stricter defaults. gojiplus/uijudge-bench drew 218
  findings, 130 of them important; all but 20 were DOC105/109/110/203 — the
  type-hints-in-docstring family canon turns off — and vanish the moment the
  canon table is added. Reporting non-adoption once per docstring buries the
  20 real findings under 110 that say nothing about the code. The `template`
  check already reports non-adoption once, which is the right number of times.

- The `metadata` check compares the build requirement as a specifier, not as a
  string. `uv_build>=0.12.5,<0.13` and `uv_build>=0.12.5,<0.13.0` admit exactly
  the same versions; gojiplus/uijudge-bench writes the second, and was told to
  migrate a build backend that is already correct and current. Equivalence, not
  laxity: a different floor, an extra pin or a different backend still fails.

- `preen adopt` backs up a managed workflow it overwrites and raises a Manual
  TODO. Input preservation covers the `with:` block; everything else in the
  file was replaced silently. Running adopt on `themains/piedomains` would have
  dropped `cancel-in-progress: ${{ github.event_name == 'pull_request' }}` from
  `docs.yml`, along with the comment explaining it must never cancel a
  main-branch build midway through a Pages deploy. The TODO deliberately does
  not claim the differing lines are the repo's own — the same comparison flags
  `tags: ["v*"]` becoming `tags: ["v*.*.*"]`, which is the template narrowing
  its own trigger — so it reports that the file differed and leaves the `.bak`.

- Comments count toward what an overwrite destroys. The conf.py line count
  ignored them and reported "2 lines" for a fifteen-line block whose value was
  mostly the reasoning: why `napoleon_use_ivar` is set, and why bare `>>>`
  blocks must not auto-execute.

- A `pydoclint` finding is never critical. `Impact.CRITICAL` means "blocks
  release — security, broken builds"; a docstring that disagrees with its
  signature is neither, and canon's CI runs bare pydoclint as its own gate, so
  preen refusing to tag adds a second veto and no information. The grade only
  became reachable once the parser started working, and it put sixteen release
  blocks on one fleet repo's `cli.py` for things like "`__init__()` should not
  have a docstring".

- `preen fix citation` moves `date-released` with the version, preserves the
  repo's quoting, and finds a citation file whatever its case. All three came
  out of running it across the fleet rather than against fixtures:

  - Syncing the number alone left `get-weather-data` claiming 6.1.0 was
    released on 2016-07-17, when the tag naming it is dated 2026-07-25. A right
    version beside a wrong date is not an improvement. The date now follows the
    tag for that version, and is left alone when no tag names it — as on
    `alsgls`, which declares 1.2.0 and has never tagged it.
  - `version: "0.6.0"` came back as `version: 0.9.0`, turning a one-line fix
    into a style change. Two fleet repos quote their values.
  - `finite-sample/rmcp` ships `citation.cff`. A macOS checkout resolves the
    exact name to it, so the check reported a file GitHub — and a
    case-sensitive CI runner — never sees. A non-canonical spelling is now an
    important finding of its own.

- `preen adopt` preserves the `with:` inputs of every canon workflow shim, not
  just ci.yml's. `docs.yml`, `release.yml` and `dependabot-auto-merge.yml` fell
  through to a blind copy, so a repo that set `docs-dir: docs/source` and
  `run-doctests: false` lost both on every adopt and its docs build broke.

- `preen adopt` writes `conf.py` where the repo's docs actually are. The path
  was hardcoded to `docs/conf.py`, so a repo whose config lives at
  `docs/source/conf.py` got a second, conflicting Sphinx config dropped beside
  it — with no `.bak`, and a report line indistinguishable from a legitimate
  fresh write. The directory now comes from the `docs-dir` input the repo's
  docs.yml declares, or from wherever a `conf.py` already sits under `docs/`.

- An overwritten `conf.py` that carried real work is raised as a Manual TODO
  naming the line count and the `.bak`, instead of being reported as a routine
  write. sharepack's adoption silently replaced a conf.py that built the three
  live demos linked from its `docs/index.md`; an unattended adopt would have
  shipped broken docs. Copy-time TODOs are also no longer discarded — the
  report assigned `build_todos`' result over them.

- `preen adopt` emits the template's dependency-group shape: a `test` group
  holding pytest and pytest-cov, with `dev` reaching it through
  `{ include-group = "test" }`. The reusable CI installs that group by name --
  its wheel job runs `uv pip install dist/*.whl --group test` against a clean
  environment -- so the flat `dev` group adopt used to write failed with
  `error: The dependency group 'test' was not found` on the first push after
  every release-migration adoption. A direct pytest pin in `dev` is removed
  rather than left beside the include, and `pre-commit` joins the dev group,
  which the template has and adopt did not.

  `tests/test_canon_template_sync.py` now compares `[dependency-groups]`
  against the template as well as `[tool.*]`. That table drifting unwatched is
  why this was possible.

- `links` no longer reports a repo's own `[tool.preen] link_ignore` patterns as
  dead links. pyproject.toml is in the scan set, so each pattern carrying a
  scheme is extracted as a URL, and it survives its own `--exclude` only when
  it happens to be a regex matching its own literal text. A properly escaped
  one does not, so it was fetched, failed DNS, and reported as a dead critical
  link in the very file that declared it.

- `links` says so when the scan did not run. A missing lychee binary, a
  timeout, or output that is not the expected JSON produced an empty report,
  which was indistinguishable from every link being healthy. It is now an info
  finding — it must not gate, since none of those are the repo's fault, but it
  must not read as verified either.

- `pydoclint` no longer reports `passed` on code pydoclint rejects. The parser
  understood only the flat `path:10: DOC101 ...` layout, while pydoclint 0.9.1
  emits a per-file block; a real report matched nothing, and an empty issue
  list read as a clean bill of health. It now handles both layouts, and a
  non-zero pydoclint exit whose output cannot be parsed is reported as such
  instead of becoming a green check. The target is passed relative, so a repo's
  own `[tool.pydoclint] exclude` can no longer be satisfied by an ancestor
  directory of the checkout.

- A `[tool.ruff]` exclude no longer switches off `runtime-assets`. Ruff excludes
  now scope only the checks that scan text — codespell, links, the import graph,
  layout — through a separate `is_lint_excluded`. `extend-exclude = ["data"]`
  had been making a whole package subtree invisible to the packaging check, so
  it passed on a tree of `.safetensors` files for reasons unrelated to whether
  they ship. The same check also tested absolute paths, so a repo cloned under
  a directory named `build`, `dist` or `venv` skipped every asset it holds.

- `ci-matrix` checks a canon shim instead of only recognising one. The reusable
  workflow's `python-versions` default is read from the ref on the `uses:` line,
  or the shim's own input where it passes one, and compared against
  `requires-python`. A repo whose floor sits above the lowest default version
  was getting a CI leg that cannot resolve while preen reported the matrix
  green. A floor that is merely never *tested* is advisory instead: CI is
  green there, and gating on it would turn every repo still declaring a 3.11
  floor red the day py-canon raised its default. Offline, the comparison is
  skipped with an info note rather than reported as verified.

- `template` reports a `_commit` that is not a release tag. The version parser
  truncated to three components, so the mangled `v1.0.1.0.1` compared equal to
  `v1.0.1` and passed; `git describe` strings and bare SHAs were equally
  invisible. Version comparison now keeps every component.

- `runtime-assets` honours `[tool.uv.build-backend]` excludes. A file that
  `source-exclude` or `wheel-exclude` keeps out of the wheel is reported at info
  — source-tree hygiene, not a packaging defect — rather than as a critical
  finding about an artifact nobody installs. An explicit `module-name` is also
  honoured, so a flat-layout package whose import name differs from its
  distribution name is no longer skipped entirely.

- `preen update` exits 1 when the merge leaves conflict markers, and names the
  `[project]` keys at risk. copier renders `[project]` from the scaffold
  answers, so a template edit anywhere near that table conflicts with the
  project's real metadata and offers `version = "0.1.0"` and
  `dependencies = []` as the "after updating" side. Previously the command
  printed one line of advice and exited 0, so nothing downstream caught a
  wrong resolution: the `version` check looks for hardcoded `__version__`
  copies, not for a version that went backwards. py-canon v1.2.0 changed two
  lines and produced exactly this conflict in an adopted repo.

- The canon-template sync test no longer compares ruff's `target-version`.
  `adopt` derives it from each repo's own `requires-python` floor, so it is a
  template default rather than a value the two copies must agree on — and
  comparing it turned every fleet floor change into a spurious drift failure.

## [0.4.1] - 2026-08-19

### Fixed

- Template drift is advisory, not blocking. A repo recording an older concrete
  py-canon tag now reports an info-level note instead of an important finding,
  so a py-canon release no longer fails `--strict` in every adopted repo at
  once — v1.1.1 turned the whole fleet red the moment it was tagged. A moving
  major tag (`_commit: v1`) is still important: that one is a real config
  error, since it makes `copier update` no-op forever.

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
