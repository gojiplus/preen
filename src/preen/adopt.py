"""Retrofit an existing package repo onto the py-canon copier template.

The adopt flow mines copier answers from the repo itself, renders the
template into a temporary directory, copies only the *managed* files into
the repo, and rewrites the ``[tool.*]`` sections of pyproject.toml with
tomlkit so comments and ordering elsewhere survive.
"""

import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from tomlkit.items import Table

CANON_TEMPLATE = "gh:gojiplus/py-canon"
UV_BUILD_REQUIREMENT = "uv_build>=0.12.5,<0.13"

# [tool.*] sections merged onto the repo's own (see `_merge_canon`).
CANON_TOOL_TOML = """
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
external = ["DOC"]
select = [
    "E", "W", "F", "I", "B", "C4", "UP", "N", "D", "S", "SIM", "T20", "PT", "RUF",
    "PTH", "RET", "PIE", "FURB", "PERF", "DTZ", "LOG", "G", "TC", "FLY",
    "RSE", "SLOT", "FA", "A", "EXE", "ICN", "PGH", "PLE", "ARG", "SLF",
]
# D203/D213: the google convention the fleet standard picks. W191/D206/D300:
# ruff's own docs list these as always incompatible with `ruff format`, which
# the standard also runs.
ignore = ["D203", "D213", "W191", "D206", "D300"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "D", "ARG", "SLF"]
"docs/**" = ["D"]

[tool.pyright]
include = ["src"]
typeCheckingMode = "standard"

[tool.pydoclint]
style = "google"
arg-type-hints-in-docstring = false
check-return-types = false
check-yield-types = false
check-class-attributes = false
allow-init-docstring = true
exclude = '\\.venv|tests|docs'
"""

LEGACY_TOOL_SECTIONS = ("black", "isort", "flake8", "mypy")

# The template's `dev` group, in its order. pydoclint is deliberately absent:
# canon's lint job runs it through `uvx --from pydoclint==<pin>`, not `uv run`,
# so it does not have to be installable from the repo's environment -- and
# `test_canon_dependency_groups_match_template` fails if adopt and the template
# disagree about any of this.
DEV_GROUP_REQUIRED = {
    "ruff": "ruff>=0.14",
    "pyright": "pyright>=1.1.390",
    "pre-commit": "pre-commit>=4",
}

#: `dev` reaches pytest through the test group rather than pinning it twice.
DEV_GROUP_INCLUDES = ("test",)

# A separate group because the reusable CI installs it separately: the wheel
# job runs `uv pip install dist/*.whl --group test` against a clean env, which
# exits 2 when no such group exists. Emitting a flat `dev` sent every
# release-migration adoption red on its first push (issue #54).
TEST_GROUP_REQUIRED = {
    "pytest": "pytest>=8",
    "pytest-cov": "pytest-cov>=6",
}

# Tools the standard retires; their dev-group entries go with them.
DEV_GROUP_RETIRED = ("black", "isort", "flake8", "mypy")

DOCS_GROUP_REQUIRED = {
    "sphinx": "sphinx>=8",
    "furo": "furo",
    "myst-parser": "myst-parser",
    "sphinx-copybutton": "sphinx-copybutton",
    "py-canon": "py-canon @ git+https://github.com/gojiplus/py-canon@v1",
}

# Managed files, relative to the repo root.
OVERWRITE_ALWAYS = (
    ".github/workflows/ci.yml",
    ".github/workflows/docs.yml",
    ".github/workflows/release.yml",
    # Canon-managed like the other workflows: leaving it copy-if-absent meant a
    # fix to the auto-merge logic could never reach a repo that already had it.
    ".github/workflows/dependabot-auto-merge.yml",
    ".copier-answers.yml",
)
COPY_IF_ABSENT = (
    ".github/zizmor.yml",
    ".github/dependabot.yml",
    ".pre-commit-config.yaml",
    "LICENSE",
    "CITATION.cff",
)
# Workflow file -> the reusable workflow its shim calls. Kept in step with
# `preen.checks.workflows.CANON_WORKFLOWS` by
# `test_adopt_and_the_workflows_check_agree_on_canon_workflows`; not imported
# from there because `preen.checks` imports this module.
CANON_WORKFLOWS: dict[str, str] = {
    "ci.yml": "reusable-ci.yml",
    "docs.yml": "reusable-docs.yml",
    "release.yml": "reusable-release.yml",
    "dependabot-auto-merge.yml": "reusable-dependabot-auto-merge.yml",
}

WORKFLOW_DIR = ".github/workflows"

CI_WORKFLOW = f"{WORKFLOW_DIR}/ci.yml"


def _canon_shim_re(reusable: str) -> re.Pattern[str]:
    """Match the `uses:` line marking a file as a shim for `reusable`.

    Args:
        reusable: Name of the reusable workflow, e.g. ``reusable-ci.yml``.

    Returns:
        The compiled pattern.
    """
    return re.compile(
        rf"^\s*uses:\s*gojiplus/py-canon/\.github/workflows/{re.escape(reusable)}@",
        re.MULTILINE,
    )


_WITH_HEADER_RE = re.compile(r"^(\s*)with:\s*$")
_WITH_INPUT_RE = re.compile(r"^(\s*)([A-Za-z0-9_-]+):[ \t]*(.*?)\s*$")


@dataclass
class AdoptionReport:
    """What adoption wrote, skipped, and left for the human."""

    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    pyproject_changes: list[str] = field(default_factory=list)
    #: Repo-specific configuration adoption kept instead of overwriting.
    preserved: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str | None:
    """Run a git command in the repo and return stripped stdout, or None.

    Args:
        repo: Repository directory.
        *args: Git arguments.

    Returns:
        Stdout stripped of whitespace, or None on failure.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def detect_package_name(repo: Path, project_name: str) -> str:
    """Determine the import package name for the repo.

    Args:
        repo: Repository directory.
        project_name: Distribution name from pyproject.toml.

    Returns:
        The import name — a package under ``src/``, a flat-layout package
        directory, or the normalized project name as fallback.
    """
    normalized = project_name.replace("-", "_")
    src = repo / "src"
    if src.is_dir():
        if (src / normalized / "__init__.py").exists():
            return normalized
        packages = [
            d.name for d in src.iterdir() if d.is_dir() and (d / "__init__.py").exists()
        ]
        if len(packages) == 1:
            return packages[0]
    if (repo / normalized / "__init__.py").exists():
        return normalized
    return normalized


def _mine_coverage_floor(repo: Path) -> int:
    """Read the coverage floor out of an existing canon ci.yml shim.

    The answer is persisted to .copier-answers.yml, so defaulting to 0 here
    would not just clobber the floor on this run — it would re-clobber it on
    every later ``preen update``.

    Args:
        repo: Repository directory.

    Returns:
        The repo's declared coverage floor, or 0 if it has none.
    """
    ci = repo / CI_WORKFLOW
    if not ci.exists():
        return 0
    try:
        text = ci.read_text(encoding="utf-8")
    except OSError:
        return 0
    block = _find_with_block(text.split("\n"))
    if block is None or "coverage-floor" not in block.inputs:
        return 0
    _, value = block.inputs["coverage-floor"]
    try:
        return int(value.strip().strip("'\""))
    except ValueError:
        return 0


def mine_answers(repo: Path) -> dict[str, Any]:
    """Mine copier answers from an existing repo.

    Args:
        repo: Repository directory containing a pyproject.toml.

    Returns:
        Answers dict suitable for ``copier.run_copy(data=...)``.

    Raises:
        FileNotFoundError: If the repo has no pyproject.toml.
    """
    pyproject_path = repo / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(f"No pyproject.toml in {repo}")

    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    project = data.get("project", {})

    project_name = project.get("name") or repo.resolve().name
    description = project.get("description", "")
    authors = project.get("authors", [])
    author_name = authors[0].get("name", "") if authors else ""
    author_email = authors[0].get("email", "") if authors else ""

    org = "gojiplus"
    remote = _git(repo, "remote", "get-url", "origin")
    if remote:
        match = re.search(r"github\.com[:/]([^/]+)/", remote)
        if match:
            org = match.group(1)

    default_branch = None
    head = _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    if head:
        default_branch = head.rsplit("/", 1)[-1]
    if not default_branch:
        default_branch = _git(repo, "branch", "--show-current") or "main"

    answers: dict[str, Any] = {
        "project_name": project_name,
        "package_name": detect_package_name(repo, project_name),
        "org": org,
        "description": description,
        "needs_cli": bool(project.get("scripts")),
        "coverage_floor": _mine_coverage_floor(repo),
        "default_branch": default_branch,
    }
    if author_name:
        answers["author_name"] = author_name
    if author_email:
        answers["author_email"] = author_email
    return answers


def render_template(
    answers: dict[str, Any],
    dst: Path,
    template: str = CANON_TEMPLATE,
    vcs_ref: str | None = None,
) -> None:
    """Render the copier template into a directory.

    Args:
        answers: Copier answers (mined from the repo).
        dst: Destination directory (a temp dir).
        template: Copier template source.
        vcs_ref: Template ref to render; None lets copier pick a tag.
    """
    from copier import run_copy

    run_copy(
        template,
        dst,
        data=answers,
        defaults=True,
        unsafe=True,
        quiet=True,
        vcs_ref=vcs_ref,
    )


def _pin_answers_commit(rendered: Path, tag: str) -> None:
    """Force the rendered answers file to record a concrete release tag.

    Copier derives ``_commit`` from ``git describe``, which can resolve to a
    moving major tag like ``v1`` when it points at the same commit as the
    release tag — and a moving-tag record makes ``copier update`` no-op
    forever. Rewriting the line keeps the record deterministic.

    Args:
        rendered: Directory containing the rendered template.
        tag: The concrete ``vX.Y.Z`` tag that was rendered.
    """
    answers_path = rendered / ".copier-answers.yml"
    if not answers_path.exists():
        return
    lines = answers_path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("_commit:"):
            lines[i] = f"_commit: {tag}\n"
            break
    answers_path.write_text("".join(lines), encoding="utf-8")


def copy_managed_files(
    rendered: Path, repo: Path, package_name: str, report: AdoptionReport
) -> None:
    """Copy the managed subset of rendered template files into the repo.

    Args:
        rendered: Directory containing the rendered template.
        repo: Target repository directory.
        package_name: Import name (for py.typed placement).
        report: Adoption report to record written/skipped files into.
    """
    for rel in OVERWRITE_ALWAYS:
        src = rendered / rel
        dest = repo / rel
        if not src.exists():
            report.skipped.append(f"{rel} (not in template)")
            continue
        # A shim carries repo-specific inputs the template knows nothing about;
        # overwriting it blind loses them. This covered ci.yml alone, so
        # `docs-dir: docs/source` and `run-doctests: false` were deleted from
        # docs.yml on every adopt (issue #51).
        reusable = CANON_WORKFLOWS.get(Path(rel).name)
        if reusable is not None and dest.exists():
            existing = dest.read_text(encoding="utf-8")
            merged, preserved = _preserve_shim_inputs(
                existing, src.read_text(encoding="utf-8"), reusable
            )
            _report_lost_lines(rel, existing, merged, dest, report)
            dest.write_text(merged, encoding="utf-8")
            report.written.append(rel)
            for entry in preserved:
                report.preserved.append(f"{rel}: {entry}")
            continue
        _copy(src, dest)
        report.written.append(rel)

    for rel in COPY_IF_ABSENT:
        src = rendered / rel
        dest = repo / rel
        if not src.exists():
            report.skipped.append(f"{rel} (not in template)")
            continue
        if dest.exists():
            report.skipped.append(f"{rel} (exists)")
            continue
        _copy(src, dest)
        report.written.append(rel)

    conf_src = rendered / "docs" / "conf.py"
    if conf_src.exists():
        _write_docs_conf(conf_src, repo, report)

    # py.typed in whichever layout the repo uses.
    if (repo / "src" / package_name).is_dir():
        typed = repo / "src" / package_name / "py.typed"
    elif (repo / package_name).is_dir():
        typed = repo / package_name / "py.typed"
    else:
        typed = None
        report.skipped.append(f"py.typed (no package dir found for {package_name!r})")
    if typed is not None:
        if typed.exists():
            report.skipped.append(f"{typed.relative_to(repo)} (exists)")
        else:
            typed.touch()
            report.written.append(str(typed.relative_to(repo)))


@dataclass
class _WithBlock:
    """The `with:` block of a workflow job, located by line."""

    header: int
    indent: str
    #: input name -> (line index, raw value)
    inputs: dict[str, tuple[int, str]] = field(default_factory=dict)


def _find_with_block(lines: list[str]) -> _WithBlock | None:
    """Locate the first `with:` block in a workflow file.

    Args:
        lines: The file split on newlines.

    Returns:
        The block, or None if the file has no ``with:`` mapping.
    """
    block = None
    for index, line in enumerate(lines):
        match = _WITH_HEADER_RE.match(line)
        if match:
            block = _WithBlock(header=index, indent=match.group(1))
            break
    if block is None:
        return None
    for index in range(block.header + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        entry = _WITH_INPUT_RE.match(line)
        if entry is None or len(entry.group(1)) <= len(block.indent):
            break
        block.inputs[entry.group(2)] = (index, entry.group(3))
    return block


def _preserve_shim_inputs(
    old_text: str, new_text: str, reusable: str
) -> tuple[str, list[str]]:
    """Re-apply an existing canon shim's `with:` inputs onto the rendered one.

    The template renders only the inputs it knows about — ``wheel-import`` and
    ``coverage-floor`` for ci.yml, ``deploy`` for docs.yml — so a repo that
    hand-added ``python-versions``, raised its coverage floor, or pointed
    ``docs-dir`` at ``docs/source`` would lose those to the overwrite. This
    edits the rendered shim's ``with:`` block textually rather than
    round-tripping the YAML, so comments and the ``on:`` key survive intact.

    Args:
        old_text: The repo's existing workflow file.
        new_text: The freshly rendered one.
        reusable: The reusable workflow both must call for this to apply.

    Returns:
        The rendered text with the repo's inputs re-applied, and a list of
        what was preserved.
    """
    shim = _canon_shim_re(reusable)
    if not (shim.search(old_text) and shim.search(new_text)):
        return new_text, []

    lines = new_text.split("\n")
    old_block = _find_with_block(old_text.split("\n"))
    new_block = _find_with_block(lines)
    if old_block is None or new_block is None or not old_block.inputs:
        return new_text, []

    preserved: list[str] = []
    added: list[tuple[str, str]] = []
    for key, (_, old_value) in old_block.inputs.items():
        if key not in new_block.inputs:
            added.append((key, old_value))
            preserved.append(f"{key}: {old_value} (absent from the template)")
            continue
        index, rendered_value = new_block.inputs[key]
        if rendered_value == old_value:
            continue
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines[index] = f"{indent}{key}: {old_value}"
        preserved.append(f"{key}: {old_value} (template rendered {rendered_value})")

    if added:
        if new_block.inputs:
            last = max(index for index, _ in new_block.inputs.values())
            entry_indent = lines[last][: len(lines[last]) - len(lines[last].lstrip())]
        else:
            last = new_block.header
            entry_indent = new_block.indent + "  "
        lines[last + 1 : last + 1] = [
            f"{entry_indent}{key}: {value}" for key, value in added
        ]

    return "\n".join(lines), preserved


def docs_dir(repo: Path) -> Path:
    """Locate the repo's Sphinx source directory, relative to the repo root.

    Assuming ``docs/`` wrote a second, conflicting ``conf.py`` into repos whose
    real one lives at ``docs/source/conf.py`` -- and reported it as a
    legitimate fresh write (issue #51).

    Args:
        repo: Repository directory.

    Returns:
        The directory holding ``conf.py``, defaulting to ``docs``.
    """
    declared = _declared_docs_dir(repo)
    if declared is not None:
        return declared

    docs = repo / "docs"
    if (docs / "conf.py").exists():
        return Path("docs")
    # Shallow, and deterministic: the nearest conf.py under docs/, not whichever
    # one rglob happens to reach first.
    found = sorted(
        path.parent.relative_to(repo)
        for path in docs.glob("*/conf.py")
        if path.is_file()
    )
    return found[0] if found else Path("docs")


def _declared_docs_dir(repo: Path) -> Path | None:
    """Return the ``docs-dir`` input the repo's docs.yml shim passes, if any.

    Args:
        repo: Repository directory.

    Returns:
        The declared directory, or None when the shim does not set one.
    """
    shim = repo / WORKFLOW_DIR / "docs.yml"
    if not shim.exists():
        return None
    text = shim.read_text(encoding="utf-8")
    if not _canon_shim_re("reusable-docs.yml").search(text):
        return None
    block = _find_with_block(text.split("\n"))
    if block is None or "docs-dir" not in block.inputs:
        return None
    value = block.inputs["docs-dir"][1].strip().strip("\"'")
    return Path(value) if value else None


def _write_docs_conf(conf_src: Path, repo: Path, report: AdoptionReport) -> None:
    """Install the canon ``conf.py``, saying so when it displaces real work.

    A ``.bak`` on disk is not a report: sharepack's adoption overwrote a
    conf.py that built the three live demos linked from ``docs/index.md``, and
    nothing in the ADOPTION REPORT distinguished that from a routine write
    (issue #48). An unattended adopt would have shipped broken docs.

    Args:
        conf_src: The rendered template's conf.py.
        repo: Repository directory.
        report: Adoption report to record the write into.
    """
    rel = docs_dir(repo) / "conf.py"
    conf_dest = repo / rel
    if not conf_dest.exists():
        _copy(conf_src, conf_dest)
        report.written.append(str(rel))
        return

    existing = conf_dest.read_text(encoding="utf-8")
    template = conf_src.read_text(encoding="utf-8")
    backup = conf_dest.with_suffix(".py.bak")
    shutil.copy2(conf_dest, backup)
    _copy(conf_src, conf_dest)
    report.written.append(f"{rel} (old config saved to {rel.with_suffix('.py.bak')})")

    if existing.strip() == template.strip():
        return
    extra = _custom_conf_lines(existing, template)
    if not extra:
        return
    report.todos.append(
        f"{rel} had {extra} line(s) the canon template does not: review "
        f"{rel.with_suffix('.py.bak')} and re-apply anything your docs need."
    )


def _custom_conf_lines(existing: str, template: str) -> int:
    """Count lines the existing conf.py has that the template does not.

    Line-set rather than a real diff: the question is only "did this file carry
    work of its own", and the answer decides whether a human is told to look.

    Args:
        existing: The repo's conf.py.
        template: The rendered template's conf.py.

    Returns:
        How many non-blank, non-comment lines are unique to the existing file.
    """
    canon = set(_meaningful_lines(template))
    return sum(1 for line in _meaningful_lines(existing) if line not in canon)


def _meaningful_lines(text: str) -> list[str]:
    """Return the lines of a file that carry content.

    Comments count. In a workflow or a Sphinx config the comment is often the
    only record of *why* a setting is what it is, so dropping them from the
    comparison undercounts what an overwrite destroys -- piedomains' conf.py
    reported "2 lines" for a fifteen-line block whose value was mostly the
    reasoning.

    Args:
        text: File contents.

    Returns:
        Stripped non-blank lines.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def _report_lost_lines(
    rel: str, existing: str, merged: str, dest: Path, report: AdoptionReport
) -> None:
    """Back up a managed workflow the overwrite changes, and say so.

    Input preservation covers the ``with:`` block. Everything else is the
    template's, and a repo may still have had a reason for a line there:
    piedomains' docs.yml carried ``cancel-in-progress: ${{ github.event_name ==
    'pull_request' }}`` with a comment explaining it must never cancel a
    main-branch build midway through a Pages deploy, and the overwrite replaced
    it with a bare ``true``.

    Deliberately does *not* claim the differing lines are the repo's own. The
    same comparison flags ``tags: ["v*"]`` becoming ``tags: ["v*.*.*"]``, which
    is the template narrowing its own trigger to semver -- an improvement, not
    a loss. Telling the two apart needs the template version the repo was last
    adopted from, i.e. the three-way merge ``preen update`` delegates to copier.
    So this reports that the file differed and leaves the ``.bak`` for a human
    to read, rather than guessing.

    Args:
        rel: Repo-relative path of the workflow.
        existing: The repo's current file.
        merged: What is about to be written.
        dest: Path being written.
        report: Adoption report to record the backup and TODO into.
    """
    kept = set(_meaningful_lines(merged))
    lost = [line for line in _meaningful_lines(existing) if line not in kept]
    if not lost:
        return
    backup = dest.with_suffix(dest.suffix + ".bak")
    shutil.copy2(dest, backup)
    preview = "; ".join(lost[:2]) + (" ..." if len(lost) > 2 else "")
    report.todos.append(
        f"{rel} differed from the template in {len(lost)} line(s) and was "
        f"overwritten ({preview}). Some of those are the template moving; diff "
        f"{backup.name} and re-apply anything that was the repo's own."
    )


def _copy(src: Path, dest: Path) -> None:
    """Copy a file, creating parent directories.

    Args:
        src: Source file.
        dest: Destination file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _ensure_table(parent: Any, key: str) -> Table:
    """Get or create a sub-table of a tomlkit container.

    Args:
        parent: Parent tomlkit container.
        key: Table key.

    Returns:
        The existing or newly created table.
    """
    if key not in parent or not isinstance(parent[key], dict):
        table = tomlkit.table(True)
        parent[key] = table
        return table
    return parent[key]


def _requirement_name(spec: str) -> str:
    """Extract the distribution name from a requirement string.

    Args:
        spec: A PEP 508-ish requirement string.

    Returns:
        The lowercased, normalized distribution name.
    """
    return (
        re.split(r"[\s@><=!~\[;]", spec.strip(), maxsplit=1)[0]
        .lower()
        .replace("_", "-")
    )


# Array settings where a repo's extra entries are appended to canon's list
# rather than replaced by it. Paths are relative to [tool].
UNION_PATHS = frozenset(
    {
        ("ruff", "lint", "ignore"),
        ("ruff", "lint", "select"),
        ("ruff", "lint", "extend-select"),
        ("ruff", "lint", "external"),
    }
)

# Every code list under this table is unioned, whatever its pattern key.
PER_FILE_IGNORES_PATH = ("ruff", "lint", "per-file-ignores")

# Lint settings ruff moved under [tool.ruff.lint]; older configs still put
# them at the top level of [tool.ruff], where the canon merge would preserve
# them into a config ruff warns about.
LEGACY_LINT_KEYS = ("select", "ignore", "extend-select", "external", "per-file-ignores")


def _describe(path: tuple[str, ...], value: Any) -> str:
    """Render a [tool] sub-path for the adoption report.

    Args:
        path: Key path below ``[tool]``.
        value: The value at that path, which decides table vs key phrasing.

    Returns:
        A TOML-ish location, e.g. ``[tool.ruff] exclude``.
    """
    if isinstance(value, dict):
        return "[tool." + ".".join(path) + "]"
    return "[tool." + ".".join(path[:-1]) + "] " + path[-1]


def _is_union_path(path: tuple[str, ...]) -> bool:
    """Return True if repo entries at `path` should be unioned with canon's."""
    return path in UNION_PATHS or path[:-1] == PER_FILE_IGNORES_PATH


def _hoist_legacy_lint_keys(ruff: Any, changes: list[str]) -> None:
    """Move deprecated top-level [tool.ruff] lint settings under [tool.ruff.lint].

    Args:
        ruff: The repo's existing ``[tool.ruff]`` table.
        changes: Change log to append to.
    """
    legacy = [key for key in LEGACY_LINT_KEYS if key in ruff]
    if not legacy:
        return
    lint = _ensure_table(ruff, "lint")
    for key in legacy:
        if key not in lint:
            lint[key] = ruff[key]
        del ruff[key]
        changes.append(f"moved legacy [tool.ruff] {key} under [tool.ruff.lint]")


def _merge_canon(
    canon: Any, repo: Any, path: tuple[str, ...], preserved: list[str]
) -> None:
    """Merge a repo's table onto the canon table for the same path, in place.

    Canon wins on every key it defines, except array settings on the union
    allowlist, where the repo's extra entries are appended. Keys and
    subtables canon says nothing about — a repo's ``exclude`` list, its
    ``flake8-bugbear`` settings, its extra per-file-ignore patterns — are
    preserved verbatim, so adoption never silently drops deliberate config.

    Args:
        canon: The canon table for this path (mutated).
        repo: The repo's existing table for this path.
        path: Key path below ``[tool]``, for reporting.
        preserved: Log of preserved settings to append to.
    """
    if not isinstance(repo, dict):
        return
    for key, repo_value in repo.items():
        sub_path = (*path, str(key))
        if key not in canon:
            canon[key] = repo_value
            preserved.append(_describe(sub_path, repo_value))
            continue
        canon_value = canon[key]
        if isinstance(canon_value, dict) and isinstance(repo_value, dict):
            _merge_canon(canon_value, repo_value, sub_path, preserved)
        elif (
            _is_union_path(sub_path)
            and isinstance(canon_value, list)
            and isinstance(repo_value, list)
        ):
            entries = [str(entry) for entry in canon_value]
            extra = sorted({str(entry) for entry in repo_value} - set(entries))
            if extra:
                canon[key] = entries + extra
                preserved.append(
                    f"{_describe(sub_path, repo_value)} entries: " + ", ".join(extra)
                )


def rewrite_pyproject(
    repo: Path, release_migration: bool = False
) -> tuple[list[str], list[str]]:
    """Rewrite pyproject.toml [tool.*] sections to the fleet standard.

    Uses tomlkit so untouched sections keep their comments and order, and
    merges rather than replaces the canon-managed sections so repo-specific
    settings survive adoption (see `_merge_canon`).

    Args:
        repo: Repository directory containing pyproject.toml.
        release_migration: Also convert the build backend to ``uv_build`` with
            an explicit project version.

    Returns:
        A (changes, preserved) pair of human-readable lists.

    Raises:
        FileNotFoundError: If the repo has no pyproject.toml.
    """
    pyproject_path = repo / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(f"No pyproject.toml in {repo}")

    doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
    canon = tomlkit.parse(CANON_TOOL_TOML)
    changes: list[str] = []
    preserved: list[str] = []

    tool = _ensure_table(doc, "tool")
    for section in ("ruff", "pyright", "pydoclint"):
        canon_section = canon["tool"][section]  # type: ignore[index]
        if section in tool:
            changes.append(f"merged canon into [tool.{section}]")
            repo_section = tool[section]
            if section == "ruff":
                _hoist_legacy_lint_keys(repo_section, changes)
            _merge_canon(canon_section, repo_section, (section,), preserved)
        else:
            changes.append(f"set [tool.{section}]")
        tool[section] = canon_section

    target_version = _ruff_target_version(doc)
    tool["ruff"]["target-version"] = target_version  # type: ignore[index]
    changes.append(f"target-version = {target_version!r} (from requires-python floor)")

    # Point pyright at the actual package location (src/ vs flat layout)
    project = doc.get("project", {})
    project_name = str(project.get("name", repo.resolve().name))
    package_name = detect_package_name(repo, project_name)
    if not (repo / "src" / package_name).is_dir() and (repo / package_name).is_dir():
        tool["pyright"]["include"] = [package_name]  # type: ignore[index]
        changes.append(f"pyright include = ['{package_name}'] (flat layout)")

    for section in LEGACY_TOOL_SECTIONS:
        if section in tool:
            del tool[section]
            changes.append(f"deleted [tool.{section}]")

    changes.extend(_ensure_docs_group(doc))
    # Before the dev group, which reaches pytest through it.
    changes.extend(_ensure_test_group(doc))
    changes.extend(_ensure_dev_group(doc))

    if release_migration:
        changes.extend(_migrate_release(doc, repo))

    pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes, preserved


def _ensure_docs_group(doc: Any) -> list[str]:
    """Ensure [dependency-groups].docs contains the standard entries.

    Args:
        doc: Parsed tomlkit document.

    Returns:
        List of changes made.
    """
    changes: list[str] = []
    groups = _ensure_table(doc, "dependency-groups")
    if "docs" not in groups:
        groups["docs"] = tomlkit.array()
        changes.append("created [dependency-groups].docs")
    docs = groups["docs"]
    present = {_requirement_name(entry) for entry in docs if isinstance(entry, str)}
    for name, spec in DOCS_GROUP_REQUIRED.items():
        if name not in present:
            docs.append(spec)  # type: ignore[union-attr]
            changes.append(f"added {spec!r} to docs group")
    return changes


def _ensure_test_group(doc: Any) -> list[str]:
    """Ensure [dependency-groups].test exists and carries pytest.

    The reusable CI installs this group by name -- the wheel job runs
    ``uv pip install dist/*.whl --group test`` against a clean environment --
    so a repo without one fails that job with exit 2 no matter what its `dev`
    group contains.

    Args:
        doc: Parsed tomlkit document.

    Returns:
        List of changes made.
    """
    changes: list[str] = []
    groups = _ensure_table(doc, "dependency-groups")
    if "test" not in groups:
        groups["test"] = tomlkit.array()
        changes.append("created [dependency-groups].test")
    test = groups["test"]
    present = _group_requirements(groups, "test")
    for name, spec in TEST_GROUP_REQUIRED.items():
        if name not in present:
            test.append(spec)  # type: ignore[union-attr]
            changes.append(f"added {spec!r} to test group")
    return changes


def _ensure_dev_group(doc: Any) -> list[str]:
    """Ensure [dependency-groups].dev carries the standard toolchain.

    CI's lint job runs ruff and pyright via ``uv run``, so they must be
    installable from the dev group, and pre-commit is the local echo of that
    gate. pytest arrives through ``{ include-group = "test" }`` rather than a
    direct pin: two pins for one distribution is the drift this shape exists to
    prevent. Entries for retired tools (black, isort, flake8, mypy) are
    dropped, as is a direct pytest pin the include now supersedes.

    Args:
        doc: Parsed tomlkit document.

    Returns:
        List of changes made.
    """
    changes: list[str] = []
    groups = _ensure_table(doc, "dependency-groups")
    if "dev" not in groups:
        groups["dev"] = tomlkit.array()
        changes.append("created [dependency-groups].dev")
    dev = groups["dev"]

    superseded = set(TEST_GROUP_REQUIRED)
    kept = []
    for entry in dev:
        if isinstance(entry, str):
            name = _requirement_name(entry)
            if name in DEV_GROUP_RETIRED:
                changes.append(f"removed {entry!r} from dev group (retired tool)")
                continue
            if name in superseded:
                changes.append(
                    f"removed {entry!r} from dev group (provided by the test group)"
                )
                continue
        kept.append(entry)
    if len(kept) != len(dev):
        new = tomlkit.array()
        for entry in kept:
            new.append(entry)
        groups["dev"] = new
        dev = new

    included = {
        str(entry["include-group"])
        for entry in dev
        if isinstance(entry, dict) and "include-group" in entry
    }
    for group in DEV_GROUP_INCLUDES:
        if group not in included:
            dev.append(tomlkit.inline_table().append("include-group", group))  # type: ignore[union-attr]
            changes.append(f"added {{ include-group = {group!r} }} to dev group")

    present = _group_requirements(groups, "dev")
    for name, spec in DEV_GROUP_REQUIRED.items():
        if name not in present:
            dev.append(spec)  # type: ignore[union-attr]
            changes.append(f"added {spec!r} to dev group")
    return changes


def _group_requirements(
    groups: Any, name: str, seen: frozenset[str] = frozenset()
) -> set[str]:
    """Collect the distributions a dependency group provides, following includes.

    A PEP 735 group can pull in another via ``{ include-group = ... }``.
    Ignoring those makes a requirement look absent and adds a second, weaker
    pin beside the one the included group already carries.

    Args:
        groups: The ``[dependency-groups]`` table.
        name: Group to resolve.
        seen: Groups already being resolved, to stop include cycles.

    Returns:
        Normalized distribution names the group provides.
    """
    if name in seen or name not in groups:
        return set()
    seen = seen | {name}
    names: set[str] = set()
    for entry in groups[name]:
        if isinstance(entry, str):
            names.add(_requirement_name(entry))
        elif isinstance(entry, dict) and "include-group" in entry:
            names |= _group_requirements(groups, str(entry["include-group"]), seen)
    return names


def _migrate_release(doc: Any, repo: Path) -> list[str]:
    """Convert build metadata to the fleet's ``uv_build`` standard.

    Args:
        doc: Parsed tomlkit document.
        repo: Repository directory (for wheel package path detection).

    Returns:
        List of changes made.
    """
    changes: list[str] = []

    build = _ensure_table(doc, "build-system")
    for key in list(build):
        if key not in {"requires", "build-backend"}:
            del build[key]
    build["requires"] = [UV_BUILD_REQUIREMENT]
    build["build-backend"] = "uv_build"
    changes.append("build-system -> uv_build")

    project = _ensure_table(doc, "project")
    if "version" not in project:
        project["version"] = _version_from_latest_tag(repo)
        changes.append(f"project.version = {project['version']!r} (from latest tag)")
    dynamic = list(project.get("dynamic", []))
    if "version" in dynamic:
        dynamic.remove("version")
        if dynamic:
            project["dynamic"] = dynamic
        else:
            del project["dynamic"]
        changes.append('removed "version" from project.dynamic')

    tool = _ensure_table(doc, "tool")
    for legacy in ("hatch", "uv-dynamic-versioning"):
        if legacy in tool:
            del tool[legacy]
            changes.append(f"deleted [tool.{legacy}]")

    project_name = str(project.get("name", repo.resolve().name))
    package_name = detect_package_name(repo, project_name)
    uv = _ensure_table(tool, "uv")
    backend = _ensure_table(uv, "build-backend")
    backend["module-name"] = package_name
    if (repo / "src" / package_name).is_dir():
        if "module-root" in backend:
            del backend["module-root"]
    else:
        backend["module-root"] = ""
    changes.append(f"uv_build module = {package_name!r}")

    return changes


def _version_from_latest_tag(repo: Path) -> str:
    """Return the latest PEP 440 version from a ``v*`` Git tag.

    Args:
        repo: Repository whose current released version is needed.

    Returns:
        Normalized PEP 440 version without the leading ``v``.

    Raises:
        ValueError: If a dynamic-version project has no usable release tag.
    """
    missing_version = (
        "release migration needs project.version or a reachable v* Git tag"
    )
    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if (
            top_level.returncode != 0
            or not top_level.stdout.strip()
            or Path(top_level.stdout.strip()).resolve() != repo.resolve()
        ):
            raise ValueError(missing_version)
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(missing_version) from exc
    candidate = result.stdout.strip().removeprefix("v")
    if result.returncode != 0 or not candidate:
        raise ValueError(missing_version)
    try:
        return str(Version(candidate))
    except InvalidVersion as exc:
        message = f"latest Git tag is not a PEP 440 version: {candidate}"
        raise ValueError(message) from exc


def build_todos(repo: Path, package_name: str) -> list[str]:
    """Detect manual follow-ups the adopter should handle.

    Args:
        repo: Repository directory.
        package_name: Import name of the package.

    Returns:
        List of TODO strings.
    """
    todos: list[str] = []

    if not (repo / "src").is_dir() and (repo / package_name).is_dir():
        todos.append(
            f"Flat layout: consider moving {package_name}/ to src/{package_name}/ "
            "(the standard uses src/ layout)"
        )

    if not (repo / "uv.lock").exists():
        todos.append("No uv.lock: run 'uv lock' and commit it (CI installs --frozen)")

    workflows = repo / ".github" / "workflows"
    if workflows.is_dir():
        stale = sorted(
            f.name
            for f in workflows.iterdir()
            if f.is_file()
            and f.suffix in {".yml", ".yaml"}
            and f.name not in CANON_WORKFLOWS
        )
        if stale:
            todos.append(
                "Old workflows left behind — review and delete: " + ", ".join(stale)
            )

    floor = _requires_python_floor(repo)
    if floor is not None and floor < (3, 11):
        todos.append(
            f"requires-python floor {floor[0]}.{floor[1]} is below the fleet "
            "standard (>=3.11); raise it"
        )

    return todos


def _requires_python_floor(repo: Path) -> tuple[int, int] | None:
    """Return the requires-python floor as a tuple, or None if unknown."""
    pyproject_path = repo / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    requires = data.get("project", {}).get("requires-python", "")
    return _parse_requires_python_floor(requires)


def _parse_requires_python_floor(requires: str) -> tuple[int, int] | None:
    """Parse the floor out of a requires-python specifier string.

    Handles every specifier that pins a lower bound: ``>=3.12``, ``~=3.12``,
    ``==3.12.*`` and ``>3.11`` all floor at 3.12/3.11 respectively. When
    several clauses set a floor, the highest wins.

    Args:
        requires: A PEP 440 specifier string, e.g. ``">=3.11,<4"``.

    Returns:
        The (major, minor) floor, or None if no clause pins one.
    """
    try:
        specifiers = SpecifierSet(requires)
    except InvalidSpecifier:
        return None
    floors: list[tuple[int, int]] = []
    for specifier in specifiers:
        # `>` floors at the same major.minor: >3.11 still admits 3.11.1.
        if specifier.operator not in (">=", "~=", "==", ">"):
            continue
        try:
            version = Version(specifier.version.rstrip(".*"))
        except InvalidVersion:
            continue
        floors.append((version.major, version.minor))
    return max(floors) if floors else None


def _ruff_target_version(doc: Any) -> str:
    """Derive ruff target-version from the repo's requires-python floor.

    Falls back to the fleet floor (py311) when requires-python is absent
    or unparsable.

    Args:
        doc: Parsed tomlkit document for the target repo's pyproject.toml.

    Returns:
        Ruff target-version string, e.g. "py312".
    """
    requires = str(doc.get("project", {}).get("requires-python", ""))
    floor = _parse_requires_python_floor(requires)
    if floor is None:
        return "py311"
    return f"py{floor[0]}{floor[1]}"


def _assert_release_migratable(repo: Path) -> None:
    """Fail before adoption writes anything if the version cannot be derived.

    Propagates the ``ValueError`` from :func:`_version_from_latest_tag` when the
    project declares a dynamic version and no ``v*`` tag exists to recover a
    concrete one from.

    Args:
        repo: Repository directory.
    """
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        return
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get(
            "project", {}
        )
    except (OSError, tomllib.TOMLDecodeError):
        return
    if "version" in project:
        return
    _version_from_latest_tag(repo)


def adopt_repo(
    repo: Path,
    release_migration: bool = False,
    template: str = CANON_TEMPLATE,
) -> AdoptionReport:
    """Run the full adoption flow on a repo.

    Args:
        repo: Repository directory.
        release_migration: Also migrate the build backend to tag-derived
            versioning.
        template: Copier template source.

    Returns:
        The adoption report.
    """
    answers = mine_answers(repo)
    report = AdoptionReport()

    # Before anything is written. `_migrate_release` runs at the very end, so a
    # repo it cannot migrate -- a dynamic version with no v* tag to recover one
    # from -- used to get five rewritten workflows, four .bak files and then a
    # traceback, with pyproject.toml untouched. Half-adopted and no report.
    # gojiplus/statqa is exactly that shape.
    if release_migration:
        _assert_release_migratable(repo)

    # Imported lazily: preen.checks.metadata imports back from this module.
    from .checks.template import latest_canon_tag

    release_tag = latest_canon_tag(concrete_only=True)

    with tempfile.TemporaryDirectory(prefix="preen-adopt-") as tmp:
        rendered = Path(tmp) / "rendered"
        render_template(answers, rendered, template=template, vcs_ref=release_tag)
        if release_tag is not None:
            _pin_answers_commit(rendered, release_tag)
        copy_managed_files(rendered, repo, str(answers["package_name"]), report)

    changes, preserved = rewrite_pyproject(repo, release_migration=release_migration)
    report.pyproject_changes = changes
    report.preserved.extend(f"pyproject.toml: {item}" for item in preserved)
    # Extend, not assign: copy_managed_files raises its own TODOs -- an
    # overwritten conf.py that carried real work -- and build_todos runs
    # afterwards with no view of what the copy did.
    report.todos.extend(build_todos(repo, str(answers["package_name"])))
    return report
