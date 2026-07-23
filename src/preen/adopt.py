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
from tomlkit.items import Table

CANON_TEMPLATE = "gh:gojiplus/py-canon"

# [tool.*] sections replaced wholesale with the template's values.
CANON_TOOL_TOML = """
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP", "N", "D", "S", "SIM", "T20", "PT", "RUF"]
ignore = ["D203", "D213"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "D"]
"docs/**" = ["D"]

[tool.pyright]
include = ["src"]
typeCheckingMode = "standard"

[tool.pydoclint]
style = "google"
arg-type-hints-in-docstring = false
check-return-types = false
check-class-attributes = false
exclude = '\\.venv|tests|docs'
"""

LEGACY_TOOL_SECTIONS = ("black", "isort", "flake8", "mypy")

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
    ".copier-answers.yml",
)
COPY_IF_ABSENT = (
    ".github/workflows/dependabot-auto-merge.yml",
    ".github/dependabot.yml",
    ".pre-commit-config.yaml",
    "LICENSE",
    "CITATION.cff",
)
CANON_WORKFLOWS = {
    "ci.yml",
    "docs.yml",
    "release.yml",
    "dependabot-auto-merge.yml",
}


@dataclass
class AdoptionReport:
    """What adoption wrote, skipped, and left for the human."""

    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    pyproject_changes: list[str] = field(default_factory=list)
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
        "coverage_floor": 0,
        "default_branch": default_branch,
    }
    if author_name:
        answers["author_name"] = author_name
    if author_email:
        answers["author_email"] = author_email
    return answers


def render_template(
    answers: dict[str, Any], dst: Path, template: str = CANON_TEMPLATE
) -> None:
    """Render the copier template into a directory.

    Args:
        answers: Copier answers (mined from the repo).
        dst: Destination directory (a temp dir).
        template: Copier template source.
    """
    from copier import run_copy

    run_copy(
        template,
        dst,
        data=answers,
        defaults=True,
        unsafe=True,
        quiet=True,
        vcs_ref=None,
    )


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
        if not src.exists():
            report.skipped.append(f"{rel} (not in template)")
            continue
        _copy(src, repo / rel)
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

    # docs/conf.py: overwrite, but back up any existing config first.
    conf_src = rendered / "docs" / "conf.py"
    if conf_src.exists():
        conf_dest = repo / "docs" / "conf.py"
        if conf_dest.exists():
            shutil.copy2(conf_dest, conf_dest.with_suffix(".py.bak"))
            report.written.append("docs/conf.py (old config saved to docs/conf.py.bak)")
        else:
            report.written.append("docs/conf.py")
        _copy(conf_src, conf_dest)

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
    if key not in parent:
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


def rewrite_pyproject(repo: Path, release_migration: bool = False) -> list[str]:
    """Rewrite pyproject.toml [tool.*] sections to the fleet standard.

    Uses tomlkit so untouched sections keep their comments and order.

    Args:
        repo: Repository directory containing pyproject.toml.
        release_migration: Also convert the build backend to hatchling +
            uv-dynamic-versioning with a tag-derived version.

    Returns:
        Human-readable list of changes made.

    Raises:
        FileNotFoundError: If the repo has no pyproject.toml.
    """
    pyproject_path = repo / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(f"No pyproject.toml in {repo}")

    doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
    canon = tomlkit.parse(CANON_TOOL_TOML)
    changes: list[str] = []

    tool = _ensure_table(doc, "tool")
    for section in ("ruff", "pyright", "pydoclint"):
        existed = section in tool
        tool[section] = canon["tool"][section]  # type: ignore[index]
        changes.append(f"{'replaced' if existed else 'set'} [tool.{section}]")

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

    if release_migration:
        changes.extend(_migrate_release(doc, repo))

    pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes


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


def _migrate_release(doc: Any, repo: Path) -> list[str]:
    """Convert build backend to hatchling + uv-dynamic-versioning.

    Args:
        doc: Parsed tomlkit document.
        repo: Repository directory (for wheel package path detection).

    Returns:
        List of changes made.
    """
    changes: list[str] = []

    build = _ensure_table(doc, "build-system")
    build["requires"] = ["hatchling", "uv-dynamic-versioning"]
    build["build-backend"] = "hatchling.build"
    changes.append("build-system -> hatchling + uv-dynamic-versioning")

    project = _ensure_table(doc, "project")
    dynamic = project.get("dynamic")
    if dynamic is None or "version" not in list(dynamic):
        new_dynamic = list(dynamic) if dynamic is not None else []
        new_dynamic.append("version")
        project["dynamic"] = new_dynamic
        changes.append('added "version" to project.dynamic')
    if "version" in project:
        del project["version"]
        changes.append("removed static project.version")

    tool = _ensure_table(doc, "tool")
    hatch = _ensure_table(tool, "hatch")
    version = _ensure_table(hatch, "version")
    version["source"] = "uv-dynamic-versioning"

    udv = _ensure_table(tool, "uv-dynamic-versioning")
    udv["vcs"] = "git"
    udv["style"] = "pep440"

    project_name = str(project.get("name", repo.resolve().name))
    package_name = detect_package_name(repo, project_name)
    if (repo / "src" / package_name).is_dir():
        packages = [f"src/{package_name}"]
    else:
        packages = [package_name]
    build_table = _ensure_table(hatch, "build")
    targets = _ensure_table(build_table, "targets")
    wheel = _ensure_table(targets, "wheel")
    wheel["packages"] = packages
    changes.append(f"wheel packages = {packages}")

    return changes


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
    match = re.search(r">=\s*(\d+)\.(\d+)", requires)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


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

    with tempfile.TemporaryDirectory(prefix="preen-adopt-") as tmp:
        rendered = Path(tmp) / "rendered"
        render_template(answers, rendered, template=template)
        copy_managed_files(rendered, repo, str(answers["package_name"]), report)

    report.pyproject_changes = rewrite_pyproject(
        repo, release_migration=release_migration
    )
    report.todos = build_todos(repo, str(answers["package_name"]))
    return report
