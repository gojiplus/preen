"""Tag-driven release command in the devtools::release() spirit.

Under the fleet standard the git tag *is* the version: pushing ``vX.Y.Z``
triggers the repo's release workflow (build, attestations, trusted
publishing, GitHub Release). This command runs the checks, asks for
informed consent, then tags and pushes.
"""

import re
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from ..checks import ALL_CHECKS, run_checks
from ..interactive import InteractiveReleaseWorkflow

_VERSION = re.compile(r"^\d+\.\d+\.\d+([.\-+].*)?$")


def _git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in the project directory.

    Args:
        project_dir: Repository directory.
        *args: Git arguments.

    Returns:
        The completed process.
    """
    return subprocess.run(
        ["git", *args],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )


def _latest_tag(project_dir: Path) -> str | None:
    """Return the latest v* tag reachable from HEAD, or None."""
    result = _git(project_dir, "describe", "--tags", "--abbrev=0", "--match", "v*")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _suggest_next(latest: str | None) -> str:
    """Suggest the next patch version after the latest tag.

    Args:
        latest: Latest tag (e.g. ``v1.2.3``) or None.

    Returns:
        Suggested version without the ``v`` prefix.
    """
    if latest:
        match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", latest)
        if match:
            major, minor, patch = (int(g) for g in match.groups())
            return f"{major}.{minor}.{patch + 1}"
    return "0.1.0"


def release_package(
    project_dir: Path,
    version: str | None = None,
    skip_checks: bool = False,
    dry_run: bool = False,
    console: Console | None = None,
) -> None:
    """Interactive tag-driven release workflow.

    Args:
        project_dir: Path to project directory.
        version: Version to release (without the ``v``); prompted if omitted.
        skip_checks: Skip running checks (if you just ran them).
        dry_run: Show what would happen without doing it.
        console: Rich console for output.

    Raises:
        typer.Exit: If checks block the release, the user cancels, or git
            commands fail.
    """
    console = console or Console()
    workflow = InteractiveReleaseWorkflow(console)

    console.print(
        "\n[bold cyan]preen release[/bold cyan] — tag-driven release workflow\n"
    )

    if not skip_checks:
        console.print("Running pre-release checks...\n")
        results = run_checks(project_dir, ALL_CHECKS)
    else:
        console.print("[yellow]Skipping checks as requested[/yellow]\n")
        results = {}

    if not workflow.run_release_checks(results, "GitHub (tag push)"):
        console.print("\n[red]Release cancelled[/red]")
        raise typer.Exit(1)

    dirty = _git(project_dir, "status", "--porcelain").stdout.strip()
    if dirty:
        console.print("[yellow]Working tree is not clean:[/yellow]")
        for line in dirty.splitlines()[:10]:
            console.print(f"  {line}")
        if not Confirm.ask("Tag anyway?", default=False):
            raise typer.Exit(1)

    latest = _latest_tag(project_dir)
    if latest:
        console.print(f"Latest release tag: [bold]{latest}[/bold]")
    if version is None:
        version = Prompt.ask("Version to release", default=_suggest_next(latest))
    version = version.lstrip("v")
    if not _VERSION.match(version):
        console.print(f"[red]'{version}' does not look like X.Y.Z[/red]")
        raise typer.Exit(1)
    tag = f"v{version}"

    if dry_run:
        console.print("\n[yellow]DRY RUN — would perform:[/yellow]")
        console.print(f"  1. git tag {tag}")
        console.print(f"  2. git push origin {tag}")
        console.print("  3. The tag push triggers the repo's release workflow")
        return

    if not Confirm.ask(f"\nTag and push [bold]{tag}[/bold]?", default=False):
        console.print("[red]Release cancelled[/red]")
        raise typer.Exit(1)

    result = _git(project_dir, "tag", tag)
    if result.returncode != 0:
        console.print(f"[red]git tag failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print(f"Created tag {tag}")

    result = _git(project_dir, "push", "origin", tag)
    if result.returncode != 0:
        console.print(f"[red]git push failed:[/red] {result.stderr.strip()}")
        console.print(f"The local tag {tag} still exists; push it manually.")
        raise typer.Exit(1)

    console.print(
        f"\n[bold green]Pushed {tag} — the release workflow takes it from "
        "here.[/bold green]"
    )
