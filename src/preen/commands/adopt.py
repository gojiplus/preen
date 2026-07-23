"""CLI wrapper for the adoption flow: retrofit a repo onto py-canon."""

from pathlib import Path

import typer
from rich.console import Console

from ..adopt import AdoptionReport, adopt_repo


def run_adopt(
    repo: Path,
    release_migration: bool = False,
    console: Console | None = None,
) -> AdoptionReport:
    """Adopt a repo and print the adoption report.

    Args:
        repo: Repository directory.
        release_migration: Also migrate the build backend to tag-derived
            versioning.
        console: Rich console for output.

    Returns:
        The adoption report.

    Raises:
        typer.Exit: If the repo has no pyproject.toml.
    """
    console = console or Console()
    try:
        report = adopt_repo(repo, release_migration=release_migration)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print("\n[bold cyan]ADOPTION REPORT[/bold cyan]")

    console.print("\n[bold]Written:[/bold]")
    if report.written:
        for item in report.written:
            console.print(f"  [green]+[/green] {item}")
    else:
        console.print("  (nothing)")

    console.print("\n[bold]Skipped:[/bold]")
    if report.skipped:
        for item in report.skipped:
            console.print(f"  [dim]-[/dim] {item}")
    else:
        console.print("  (nothing)")

    console.print("\n[bold]pyproject.toml:[/bold]")
    for item in report.pyproject_changes:
        console.print(f"  [yellow]~[/yellow] {item}")

    if report.todos:
        console.print("\n[bold]Manual TODOs:[/bold]")
        for item in report.todos:
            console.print(f"  [red]![/red] {item}")

    console.print(
        "\nRun [cyan]uv lock && uv sync --all-groups[/cyan], then "
        "[cyan]preen check[/cyan] to see where the repo stands."
    )
    return report
