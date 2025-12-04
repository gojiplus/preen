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
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table

from .syncer import sync_project
from .checks import run_checks
from .checks.ruff import RuffCheck
from .checks.tests import TestsCheck
from .checks.citation import CitationCheck
from .checks.deps import DepsCheck
from .checks.ci_matrix import CIMatrixCheck
from .checks.structure import StructureCheck
from .checks.version import VersionCheck
from .commands.init import init_package
from .commands.bump import bump_package_version, VersionPart

app = typer.Typer(
    help="Preen – an opinionated CLI for Python package hygiene and release",
    add_completion=False,
)


@app.command()
def sync(
    path: Optional[str] = typer.Argument(
        None,
        help="Path to the project directory. Defaults to the current working directory.",
        exists=False,
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress informational output.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Check if files need updating without making changes. Exit 1 if changes needed.",
    ),
    only: Optional[List[str]] = typer.Option(
        None,
        "--only",
        help="Only sync specific targets. Valid: ci, citation, docs, workflows",
    ),
) -> None:
    """Synchronise derived files from ``pyproject.toml``.

    This command reads the project's configuration and writes or updates files
    such as ``CITATION.cff``, documentation configuration and GitHub Actions
    workflows.  It treats ``pyproject.toml`` as the single source of truth.
    """
    project_dir = Path(path or os.getcwd())
    console = Console()

    # Convert only list to set
    targets = set(only) if only else None

    try:
        result = sync_project(project_dir, quiet=quiet, check=check, targets=targets)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    except SystemExit as e:
        # sync_project calls sys.exit(1) in check mode if files would change
        raise typer.Exit(code=e.code)

    if not quiet:
        if check:
            # In check mode, show summary
            if result["would_change"]:
                console.print("\n[bold red]Files would be updated:[/bold red]")
                for rel_path in result["would_change"]:
                    console.print(f"  • {rel_path}")
            else:
                console.print("\n[bold green]✓ All files are up to date[/bold green]")
        else:
            # Normal mode - show what was done
            console.print("\n[bold]Sync complete[/bold]")

            # Create a summary table
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Status", style="dim", width=12)
            table.add_column("File")

            for rel_path in result["updated"]:
                table.add_row("[green]✓ Updated[/green]", rel_path)

            for rel_path in result["unchanged"]:
                table.add_row("[dim]○ Unchanged[/dim]", rel_path)

            console.print(table)

            # Summary
            updated_count = len(result["updated"])
            unchanged_count = len(result["unchanged"])
            total_count = updated_count + unchanged_count

            console.print(
                f"\n[dim]{total_count} file(s) processed: "
                f"{updated_count} updated, {unchanged_count} unchanged[/dim]"
            )


@app.command()
def check(
    path: Optional[str] = typer.Argument(
        None,
        help="Path to the project directory. Defaults to the current working directory.",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        "-f",
        help="Automatically apply fixes without prompting.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit with code 1 if any issues found (for CI).",
    ),
    skip: Optional[List[str]] = typer.Option(
        None,
        "--skip",
        help="Skip specific checks.",
    ),
    only: Optional[List[str]] = typer.Option(
        None,
        "--only",
        help="Run only specific checks.",
    ),
) -> None:
    """Run pre-release checks on the package.

    This command runs various checks including linting, tests, and
    configuration validation. Issues can be fixed interactively or
    automatically with --fix.
    """
    project_dir = Path(path or os.getcwd())
    console = Console()

    # Header
    console.print("\n[bold cyan]preen check[/bold cyan] - Running pre-release checks\n")

    # Available checks
    check_classes = [
        RuffCheck,
        TestsCheck,
        CitationCheck,
        DepsCheck,
        CIMatrixCheck,
        StructureCheck,
        VersionCheck,
    ]

    # Run checks
    results = run_checks(
        project_dir,
        check_classes,
        skip=skip,
        only=only,
    )

    # Display results table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Check", style="dim", width=20)
    table.add_column("Status")
    table.add_column("Issues")

    total_issues = 0
    has_errors = False
    fixable_issues = []

    for check_name, result in results.items():
        if result.passed:
            status = "[green]✓ passed[/green]"
            issue_text = ""
        else:
            if result.has_errors:
                status = "[red]✗ failed[/red]"
                has_errors = True
            else:
                status = "[yellow]⚠ warning[/yellow]"

            issue_count = len(result.issues)
            total_issues += issue_count
            issue_text = f"{issue_count} issue{'s' if issue_count != 1 else ''}"

            # Collect fixable issues
            for issue in result.issues:
                if issue.proposed_fix:
                    fixable_issues.append(issue)

        table.add_row(check_name, status, issue_text)

    console.print(table)

    # Summary
    if total_issues == 0:
        console.print("\n[bold green]✓ All checks passed![/bold green]\n")
    else:
        console.print(f"\n[bold]Found {total_issues} issue(s)[/bold]")

        # Show issues
        for check_name, result in results.items():
            if not result.passed:
                for issue in result.issues:
                    console.print(f"  {issue}")

        # Handle fixes
        if fixable_issues:
            console.print(
                f"\n{len(fixable_issues)} issue(s) can be automatically fixed."
            )

            if fix:
                # Apply all fixes
                console.print("\nApplying fixes...")
                for issue in fixable_issues:
                    console.print(f"  Fixing: {issue.description}")
                    issue.proposed_fix.apply()
                console.print("[green]✓ Fixes applied[/green]")
            elif not strict:
                # Interactive mode
                if typer.confirm("\nApply fixes interactively?"):
                    for issue in fixable_issues:
                        console.print(f"\n[bold]Issue:[/bold] {issue.description}")
                        console.print("\n[dim]Proposed fix:[/dim]")
                        console.print(issue.proposed_fix.preview())

                        if typer.confirm("Apply this fix?"):
                            issue.proposed_fix.apply()
                            console.print("[green]✓ Fixed[/green]")
                        else:
                            console.print("[yellow]Skipped[/yellow]")

    # Exit with error in strict mode if issues found
    if strict and (total_issues > 0 or has_errors):
        raise typer.Exit(code=1)


@app.command()
def init(
    package_name: Optional[str] = typer.Argument(
        None,
        help="Name of the package to create. If not provided, will prompt interactively.",
    ),
    directory: Optional[str] = typer.Option(
        None,
        "--dir",
        "-d",
        help="Directory to create the package in. Defaults to ./PACKAGE_NAME",
    ),
) -> None:
    """Initialize a new Python package with opinionated structure.

    Creates a new package directory with:
    - pyproject.toml with modern Python packaging configuration
    - Opinionated directory structure (src/ layout by default)
    - Basic tests and CI configuration
    - Generated files (CITATION.cff, workflows, etc.)
    """
    target_dir = None
    if directory:
        target_dir = Path(directory)

    init_package(package_name, target_dir)


@app.command()
def bump(
    part: VersionPart = typer.Argument(
        ...,
        help="Part of version to bump: major, minor, or patch",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Path to project directory. Defaults to current directory.",
    ),
    no_commit: bool = typer.Option(
        False,
        "--no-commit",
        help="Don't commit the version bump to git",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be changed without making any changes",
    ),
) -> None:
    """Bump package version and sync derived files.

    Updates the version in pyproject.toml according to semantic versioning,
    then syncs all derived files (CITATION.cff, workflows, etc.) and
    optionally commits the changes to git.

    Examples:

        preen bump patch      # 1.0.0 -> 1.0.1
        preen bump minor      # 1.0.1 -> 1.1.0
        preen bump major      # 1.1.0 -> 2.0.0
    """
    project_dir = Path(path) if path else None
    bump_package_version(
        part=part,
        project_dir=project_dir,
        commit=not no_commit,
        dry_run=dry_run,
    )


def run():  # pragma: no cover
    """Entry point for console scripts created by the build backend."""
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
