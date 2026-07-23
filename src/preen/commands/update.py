"""Update an adopted repo to the latest py-canon template."""

import subprocess
from pathlib import Path

import typer
from rich.console import Console


def run_update(repo: Path, console: Console | None = None) -> None:
    """Run copier update on an adopted repo and print a diff summary.

    Args:
        repo: Repository directory containing .copier-answers.yml.
        console: Rich console for output.

    Raises:
        typer.Exit: If the repo has no .copier-answers.yml.
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

    diff = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    changed = [line for line in diff.stdout.splitlines() if line.strip()]
    if diff.returncode != 0:
        console.print("[yellow]Not a git repo — cannot summarize changes.[/yellow]")
    elif changed:
        console.print("\n[bold]Changed files:[/bold]")
        for line in changed:
            console.print(f"  {line}")
        console.print(
            "\nSearch for inline conflict markers before committing "
            "(copier merges with conflict='inline')."
        )
    else:
        console.print("\n[green]Already up to date.[/green]")
