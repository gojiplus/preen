"""Update an adopted repo to the latest py-canon template."""

import subprocess
import tomllib
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape

CONFLICT_OURS = "<<<<<<<"
CONFLICT_SEP = "======="
CONFLICT_THEIRS = ">>>>>>>"

# The template renders `[project]` from the scaffold answers, so on every
# update its side of the merge is the *scaffold*: version 0.1.0, no
# dependencies, one author. A project that took that side would publish an
# empty wheel under a version it released long ago.
PROJECT_OWNED = "pyproject.toml"


def has_conflict_markers(text: str) -> bool:
    """Report whether text carries copier's inline conflict markers.

    Args:
        text: File contents.

    Returns:
        True if a conflict block opens anywhere in the text.
    """
    return any(line.startswith(CONFLICT_OURS) for line in text.splitlines())


def split_conflict_sides(text: str) -> tuple[str, str]:
    """Reconstruct both candidate files from inline conflict markers.

    A bare ``=======`` line counts as a separator only inside an open
    conflict block, so a Markdown heading underline in an unconflicted file
    is not mistaken for one.

    Args:
        text: File contents, with or without conflict markers.

    Returns:
        The "before updating" and "after updating" files, in that order.
    """
    ours: list[str] = []
    theirs: list[str] = []
    side = "both"

    for line in text.splitlines():
        if line.startswith(CONFLICT_OURS):
            side = "ours"
        elif line.startswith(CONFLICT_SEP) and side == "ours":
            side = "theirs"
        elif line.startswith(CONFLICT_THEIRS):
            side = "both"
        elif side == "ours":
            ours.append(line)
        elif side == "theirs":
            theirs.append(line)
        else:
            ours.append(line)
            theirs.append(line)

    return "\n".join(ours) + "\n", "\n".join(theirs) + "\n"


def conflict_hunks(text: str) -> list[tuple[str, list[str], list[str]]]:
    """Split text into its conflict hunks, tagged with the enclosing table.

    Args:
        text: File contents carrying inline conflict markers.

    Returns:
        One ``(table_header, ours_lines, theirs_lines)`` triple per conflict.
        The header is the last table header seen outside a conflict, or the
        empty string before the first one.
    """
    hunks: list[tuple[str, list[str], list[str]]] = []
    table = ""
    ours: list[str] = []
    theirs: list[str] = []
    side = "both"

    for line in text.splitlines():
        if line.startswith(CONFLICT_OURS):
            side, ours, theirs = "ours", [], []
        elif line.startswith(CONFLICT_SEP) and side == "ours":
            side = "theirs"
        elif line.startswith(CONFLICT_THEIRS):
            hunks.append((table, ours, theirs))
            side = "both"
        elif side == "ours":
            ours.append(line)
        elif side == "theirs":
            theirs.append(line)
        elif line.startswith("[") and line.rstrip().endswith("]"):
            table = line.rstrip()

    return hunks


def _parse_in_table(table: str, lines: list[str]) -> dict[str, Any] | None:
    """Parse conflict-hunk lines as the body of one TOML table.

    Reading each side of a hunk on its own avoids the duplicate-key errors
    that reconstructing the whole file produces: the template's side of a
    ``[project]`` conflict routinely reintroduces a key, such as ``version``,
    that also survives outside the conflict.

    Args:
        table: The enclosing table header, e.g. ``[project]``.
        lines: One side of a conflict hunk.

    Returns:
        The table's keys, or None if the fragment is not valid TOML (a
        conflict cutting through an array leaves it unterminated).
    """
    name = table.strip().strip("[]")
    try:
        parsed = tomllib.loads("\n".join([table, *lines]) + "\n")
    except tomllib.TOMLDecodeError:
        return None
    value = parsed.get(name)
    return value if isinstance(value, dict) else None


def project_metadata_at_risk(text: str) -> list[tuple[str, Any, Any]]:
    """List `[project]` keys the merge would change, current value first.

    Args:
        text: Contents of a conflicted ``pyproject.toml``.

    Returns:
        One ``(key, current, offered)`` triple per differing key, sorted by
        key, where ``offered`` is None for a key the merge would drop. Empty
        when no ``[project]`` hunk parses or nothing differs.
    """
    at_risk: dict[str, tuple[Any, Any]] = {}
    # A key the hunk does not carry may still be set elsewhere in the table:
    # `version` sat above this conflict, so the hunk's own "before" side has
    # no version at all while the file plainly does.
    current_table = _whole_file_project(text)

    for table, ours_lines, theirs_lines in conflict_hunks(text):
        if table.strip() != "[project]":
            continue
        ours = _parse_in_table(table, ours_lines)
        theirs = _parse_in_table(table, theirs_lines)
        if ours is None or theirs is None:
            continue
        for key in set(ours) | set(theirs):
            current = ours.get(key, current_table.get(key))
            offered = theirs.get(key)
            if current != offered:
                at_risk[key] = (current, offered)

    return [(key, *at_risk[key]) for key in sorted(at_risk)]


def _whole_file_project(text: str) -> dict[str, Any]:
    """Read the `[project]` table from the current side of a conflicted file.

    Args:
        text: Contents of a conflicted ``pyproject.toml``.

    Returns:
        The table as it stands today, or an empty dict if it does not parse.
    """
    ours_text, _ = split_conflict_sides(text)
    try:
        project = tomllib.loads(ours_text).get("project")
    except tomllib.TOMLDecodeError:
        return {}
    return project if isinstance(project, dict) else {}


def _changed_paths(repo: Path) -> tuple[list[str], bool]:
    """Return `git status --porcelain` lines for the repo.

    Args:
        repo: Repository directory.

    Returns:
        The non-empty status lines, and whether git could read the repo.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return [], False
    return [line for line in result.stdout.splitlines() if line.strip()], True


def _conflicted(repo: Path, status_lines: list[str]) -> list[Path]:
    """Find changed files that still carry conflict markers.

    Args:
        repo: Repository directory.
        status_lines: Porcelain status lines from ``_changed_paths``.

    Returns:
        Paths, relative to the repo, of files with unresolved conflicts.
    """
    found = []
    for line in status_lines:
        rel = line[3:].strip().strip('"')
        path = repo / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if has_conflict_markers(text):
            found.append(Path(rel))
    return found


def _report_conflicts(repo: Path, conflicted: list[Path], console: Console) -> None:
    """Print unresolved conflicts and what they put at risk.

    Args:
        repo: Repository directory.
        conflicted: Paths, relative to the repo, that hold conflict markers.
        console: Rich console for output.
    """
    console.print("\n[bold red]Unresolved conflicts:[/bold red]")
    for rel in conflicted:
        console.print(f"  {rel}")

    if Path(PROJECT_OWNED) not in conflicted:
        return

    text = (repo / PROJECT_OWNED).read_text(encoding="utf-8")
    at_risk = project_metadata_at_risk(text)
    if not at_risk:
        return

    # Rich reads a bare [project] as a markup tag and swallows it.
    table = escape("[project]")
    console.print(
        f"\n[bold red]{PROJECT_OWNED}: the template is offering to replace "
        f"{table} metadata[/bold red]"
    )
    for key, current, offered in at_risk:
        shown = "(dropped)" if offered is None else repr(offered)
        console.print(
            f"  {key}\n"
            f"    keep:    {escape(repr(current))}\n"
            f"    offered: {escape(shown)}"
        )
    console.print(
        f"\n[yellow]The template renders {table} from the scaffold answers, so "
        "what it offers is the state this repo had on day one. These are "
        "per-project facts, not fleet settings: keep the current values.[/yellow]"
    )


def run_update(repo: Path, console: Console | None = None) -> None:
    """Run copier update on an adopted repo and print a diff summary.

    Args:
        repo: Repository directory containing .copier-answers.yml.
        console: Rich console for output.

    Raises:
        typer.Exit: If the repo has no .copier-answers.yml, or if the merge
            left conflict markers behind.
    """
    from copier import run_update as copier_run_update

    console = console or Console()

    if not (repo / ".copier-answers.yml").exists():
        console.print(
            "[red]No .copier-answers.yml — this repo is not adopted from the "
            "py-canon template. Run 'preen adopt' first.[/red]"
        )
        raise typer.Exit(code=1)

    console.print("Updating from the py-canon template ...")
    copier_run_update(
        repo,
        defaults=True,
        overwrite=True,
        conflict="inline",
        unsafe=True,
    )

    changed, is_git = _changed_paths(repo)
    if not is_git:
        console.print("[yellow]Not a git repo — cannot summarize changes.[/yellow]")
        return
    if not changed:
        console.print("\n[green]Already up to date.[/green]")
        return

    console.print("\n[bold]Changed files:[/bold]")
    for line in changed:
        console.print(f"  {line}")

    conflicted = _conflicted(repo, changed)
    if not conflicted:
        return

    _report_conflicts(repo, conflicted, console)
    raise typer.Exit(code=1)
