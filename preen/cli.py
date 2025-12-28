"""Command‑line interface for preen.

This module defines a Typer application exposing the ``preen`` command.  At
present only the ``sync`` subcommand is implemented, which reads the
``pyproject.toml`` in the current working directory (or a user‑supplied
directory) and regenerates derived files.  Additional subcommands will be
added in future phases of development.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .syncer import sync_project
from .checks import run_checks
from .checks.base import Impact
from .interactive import EducationalPrompt
from .checks.ruff import RuffCheck
from .checks.tests import TestsCheck
from .checks.citation import CitationCheck
from .checks.deps import DepsCheck
from .checks.deptree import DeptreeCheck
from .checks.ci_matrix import CIMatrixCheck
from .checks.structure import StructureCheck
from .checks.version import VersionCheck
from .checks.links import LinkCheck
from .checks.pydoclint import PydoclintCheck
from .checks.pyright import PyrightCheck
from .checks.codespell import CodespellCheck
from .commands.init import init_package
from .commands.bump import bump_package_version, VersionPart
from .commands.release import release_to_pypi
from .commands.fix import apply_fixes

app = typer.Typer(
    help="Preen – an opinionated CLI for Python package hygiene and release",
    add_completion=False,
)


@app.command()
def sync(
    path: str | None = typer.Argument(
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
    only: list[str] | None = typer.Option(
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
    project_dir = Path(path) if path else Path.cwd()
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
    path: str | None = typer.Argument(
        None,
        help="Path to the project directory. Defaults to the current working directory.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit with code 1 if any issues found (for CI).",
    ),
    explain: bool = typer.Option(
        False,
        "--explain",
        help="Show explanations of why each issue matters.",
    ),
    skip: list[str] | None = typer.Option(
        None,
        "--skip",
        help="Skip specific checks.",
    ),
    only: list[str] | None = typer.Option(
        None,
        "--only",
        help="Run only specific checks.",
    ),
) -> None:
    """Run checks on the package (pure detection, no fixing).

    This command runs various checks including linting, tests, and
    configuration validation. For fixing issues, use 'preen fix'.
    For guided release workflow, use 'preen release'.
    """
    project_dir = Path(path) if path else Path.cwd()
    console = Console()

    # Header
    console.print(
        "\n[bold cyan]preen check[/bold cyan] - Package health check (detection only)\n"
    )

    # Available checks
    check_classes = [
        RuffCheck,
        TestsCheck,
        CitationCheck,
        DepsCheck,
        DeptreeCheck,
        CIMatrixCheck,
        StructureCheck,
        VersionCheck,
        LinkCheck,
        PydoclintCheck,
        PyrightCheck,
        CodespellCheck,
    ]

    # Run checks
    results = run_checks(
        project_dir,
        check_classes,
        skip=skip,
        only=only,
    )

    # Educational prompt helper
    educator = EducationalPrompt(console)

    # Display results table
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Check", style="dim", width=20)
    table.add_column("Status")
    table.add_column("Issues")
    table.add_column("Impact", width=12)

    total_issues = 0
    has_errors = False
    critical_count = 0
    important_count = 0

    for check_name, result in results.items():
        if result.passed:
            status = "[green]✓ passed[/green]"
            issue_text = ""
            impact_text = ""
        else:
            if result.has_errors:
                status = "[red]✗ failed[/red]"
                has_errors = True
            else:
                status = "[yellow]⚠ warning[/yellow]"

            issue_count = len(result.issues)
            total_issues += issue_count
            issue_text = f"{issue_count} issue{'s' if issue_count != 1 else ''}"

            # Count by impact
            critical = len(result.get_issues_by_impact(Impact.CRITICAL))
            important = len(result.get_issues_by_impact(Impact.IMPORTANT))
            critical_count += critical
            important_count += important

            impact_parts = []
            if critical > 0:
                impact_parts.append(f"[red]{critical} critical[/red]")
            if important > 0:
                impact_parts.append(f"[yellow]{important} important[/yellow]")
            impact_text = (
                ", ".join(impact_parts) if impact_parts else "[blue]info only[/blue]"
            )

        table.add_row(check_name, status, issue_text, impact_text)

    console.print(table)

    # Summary
    if total_issues == 0:
        console.print("\n[bold green]✓ All checks passed![/bold green]\n")
    else:
        console.print(f"\n[bold]Found {total_issues} issue(s)[/bold]")

        if critical_count > 0:
            console.print(f"  🚫 {critical_count} critical (blocks release)")
        if important_count > 0:
            console.print(f"  ⚠️  {important_count} important (can override)")

        # Show issues with explanations if requested
        for check_name, result in results.items():
            if not result.passed:
                if explain:
                    educator.explain_check(check_name, result.issues)
                else:
                    for issue in result.issues:
                        symbol = issue.get_impact_symbol()
                        console.print(f"  {symbol} {issue}")

        # Suggest next steps
        console.print("\n[bold blue]Next steps:[/bold blue]")
        console.print("  • Run [cyan]preen fix[/cyan] to apply automatic fixes")
        console.print("  • Run [cyan]preen release[/cyan] for guided release workflow")
        if not explain:
            console.print(
                "  • Use [cyan]--explain[/cyan] to understand why issues matter"
            )

    # Exit with error in strict mode if issues found
    if strict and (total_issues > 0 or has_errors):
        raise typer.Exit(code=1)


@app.command()
def release(
    path: str | None = typer.Option(
        None,
        "--path",
        "-p",
        help="Path to project directory. Defaults to current directory.",
    ),
    target: str = typer.Option(
        "pypi",
        "--target",
        "-t",
        help="Release target: pypi, github, or both",
    ),
    skip_checks: bool = typer.Option(
        False,
        "--skip-checks",
        help="Skip running checks (if you just ran them).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would happen without doing it.",
    ),
) -> None:
    """Interactive release workflow similar to devtools::release().

    Runs checks, asks questions, and guides you through the release process.
    Allows overriding non-critical issues with informed consent.
    """
    project_dir = Path(path) if path else Path.cwd()
    console = Console()

    release_to_pypi(
        project_dir=project_dir,
        target=target,
        skip_checks=skip_checks,
        dry_run=dry_run,
        console=console,
    )


@app.command()
def fix(
    check_name: str | None = typer.Argument(
        None,
        help="Specific check to fix (e.g., 'ruff', 'citation'). If not provided, fixes all checks.",
    ),
    path: str | None = typer.Option(
        None,
        "--path",
        "-p",
        help="Path to project directory. Defaults to current directory.",
    ),
    auto: bool = typer.Option(
        False,
        "--auto",
        "-a",
        help="Apply all fixes automatically without prompting.",
    ),
    interactive: bool = typer.Option(
        True,
        "--interactive/--batch",
        help="Ask before applying each fix (default) vs batch mode.",
    ),
) -> None:
    """Apply fixes for issues found by checks.

    This command finds and applies fixes for issues detected by preen checks.
    Use after running 'preen check' to fix detected problems.

    Examples:
        preen fix                    # Fix all issues interactively
        preen fix ruff              # Fix only ruff issues
        preen fix --auto            # Apply all fixes automatically
        preen fix citation --auto   # Auto-fix citation issues only
    """
    project_dir = Path(path) if path else Path.cwd()
    console = Console()

    apply_fixes(
        project_dir=project_dir,
        check_name=check_name,
        interactive=interactive and not auto,
        auto=auto,
        console=console,
    )


@app.command()
def init(
    package_name: str | None = typer.Argument(
        None,
        help="Name of the package to create. If not provided, will prompt interactively.",
    ),
    directory: str | None = typer.Option(
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
    path: str | None = typer.Option(
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
