"""Command‑line interface for preen.

This module defines a Typer application exposing the ``preen`` command.  At
present only the ``sync`` subcommand is implemented, which reads the
``pyproject.toml`` in the current working directory (or a user‑supplied
directory) and regenerates derived files.  Additional subcommands will be
added in future phases of development.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .syncer import sync_project

app = typer.Typer(
    help="Preen – an opinionated CLI for Python package hygiene and release",
    add_completion=False,
)


@app.command()
def sync(
    path: Optional[str] = typer.Argument(
        None,
        help="Path to the project directory.  Defaults to the current working directory.",
        exists=False,
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress informational output.",
    ),
) -> None:
    """Synchronise derived files from ``pyproject.toml``.

    This command reads the project's configuration and writes or updates files
    such as ``CITATION.cff``, documentation configuration and GitHub Actions
    workflows.  It treats ``pyproject.toml`` as the single source of truth.
    """
    project_dir = Path(path or os.getcwd())
    console = Console()
    try:
        outputs = sync_project(project_dir, quiet=quiet)
    except FileNotFoundError as e:
        console.print(f"[red]{e}\n[/red]")
        raise typer.Exit(code=1)
    if not quiet:
        console.print("\n[bold green]Sync complete[/bold green]")
        for rel_path in outputs:
            console.print(f"  • {rel_path}")


def run():  # pragma: no cover
    """Entry point for console scripts created by the build backend."""
    app()


if __name__ == "__main__":  # pragma: no cover
    run()