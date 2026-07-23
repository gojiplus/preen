"""Command-line interface for preen.

Preen is the conformance-and-adoption CLI for the py-canon fleet standard:
scaffold new packages (``new``), retrofit existing ones (``adopt``), pull
template updates (``update``), check conformance (``check``), apply fixes
(``fix``), and cut tag-driven releases (``release``).
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .checks import ALL_CHECKS, Impact, run_checks
from .commands.adopt import run_adopt
from .commands.fix import apply_fixes
from .commands.new import new_package
from .commands.release import release_package
from .commands.update import run_update
from .interactive import EducationalPrompt

app = typer.Typer(
    help="Preen — conformance and adoption CLI for the py-canon fleet standard",
    add_completion=False,
)


@app.command()
def new(
    name: str = typer.Argument(..., help="Project name (also the directory created)."),
    org: str | None = typer.Option(
        None, "--org", help="GitHub org/owner (copier prompts if omitted)."
    ),
    description: str | None = typer.Option(
        None, "--description", help="One-line description (copier prompts if omitted)."
    ),
    cli: bool | None = typer.Option(
        None,
        "--cli/--no-cli",
        help="Ship a console script (copier prompts if omitted).",
    ),
) -> None:
    """Scaffold a new package from the py-canon copier template."""
    new_package(name, org=org, description=description, cli=cli)


@app.command()
def adopt(
    path: str | None = typer.Argument(
        None, help="Path to the repo to adopt. Defaults to the current directory."
    ),
    release_migration: bool = typer.Option(
        False,
        "--release-migration",
        help="Also convert the build backend to hatchling + uv-dynamic-versioning "
        "(tag-derived version).",
    ),
) -> None:
    """Retrofit an existing package repo onto the py-canon template.

    Mines copier answers from the repo (pyproject, git remote), renders the
    template, copies in only the managed files, and rewrites the [tool.*]
    sections of pyproject.toml to the fleet standard.
    """
    repo = Path(path) if path else Path.cwd()
    run_adopt(repo, release_migration=release_migration)


@app.command()
def update(
    path: str | None = typer.Argument(
        None, help="Path to the adopted repo. Defaults to the current directory."
    ),
) -> None:
    """Update an adopted repo to the latest py-canon template version."""
    repo = Path(path) if path else Path.cwd()
    run_update(repo)


@app.command()
def check(
    path: str | None = typer.Argument(
        None,
        help="Path to the project directory. Defaults to the current directory.",
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit with code 1 if any issues found (for CI)."
    ),
    explain: bool = typer.Option(
        False, "--explain", help="Show explanations of why each issue matters."
    ),
    skip: list[str] | None = typer.Option(None, "--skip", help="Skip specific checks."),
    only: list[str] | None = typer.Option(
        None, "--only", help="Run only specific checks."
    ),
) -> None:
    """Run conformance checks on the package (pure detection, no fixing)."""
    project_dir = Path(path) if path else Path.cwd()
    console = Console()

    console.print(
        "\n[bold cyan]preen check[/bold cyan] — package health check (detection only)\n"
    )

    results = run_checks(project_dir, ALL_CHECKS, skip=skip, only=only)
    educator = EducationalPrompt(console)

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Check", style="dim", width=20)
    table.add_column("Status")
    table.add_column("Issues")
    table.add_column("Impact", width=16)

    total_issues = 0
    has_errors = False
    critical_count = 0
    important_count = 0

    for check_name, result in results.items():
        if result.passed:
            status = "[green]passed[/green]"
            issue_text = ""
            impact_text = ""
        else:
            if result.has_errors:
                status = "[red]failed[/red]"
                has_errors = True
            else:
                status = "[yellow]warning[/yellow]"

            issue_count = len(result.issues)
            total_issues += issue_count
            issue_text = f"{issue_count} issue{'s' if issue_count != 1 else ''}"

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

    if total_issues == 0:
        console.print("\n[bold green]All checks passed.[/bold green]\n")
    else:
        console.print(f"\n[bold]Found {total_issues} issue(s)[/bold]")
        if critical_count > 0:
            console.print(f"  {critical_count} critical (blocks release)")
        if important_count > 0:
            console.print(f"  {important_count} important (can override)")

        for check_name, result in results.items():
            if not result.passed:
                if explain:
                    educator.explain_check(check_name, result.issues)
                else:
                    for issue in result.issues:
                        console.print(f"  {issue}")

        console.print("\n[bold blue]Next steps:[/bold blue]")
        console.print("  - Run [cyan]preen fix[/cyan] to apply automatic fixes")
        console.print("  - Run [cyan]preen release[/cyan] for the guided release flow")
        if not explain:
            console.print(
                "  - Use [cyan]--explain[/cyan] to understand why issues matter"
            )

    if strict and (total_issues > 0 or has_errors):
        raise typer.Exit(code=1)


@app.command()
def fix(
    check_name: str | None = typer.Argument(
        None,
        help="Specific check to fix (e.g. 'ruff', 'citation'). Default: all checks.",
    ),
    path: str | None = typer.Option(
        None, "--path", "-p", help="Path to project directory. Defaults to cwd."
    ),
    auto: bool = typer.Option(
        False, "--auto", "-a", help="Apply all fixes automatically without prompting."
    ),
    interactive: bool = typer.Option(
        True,
        "--interactive/--batch",
        help="Ask before applying each fix (default) vs batch mode.",
    ),
) -> None:
    """Apply fixes for issues found by checks."""
    project_dir = Path(path) if path else Path.cwd()
    apply_fixes(
        project_dir=project_dir,
        check_name=check_name,
        interactive=interactive and not auto,
        auto=auto,
    )


@app.command()
def release(
    version: str | None = typer.Argument(
        None, help="Version to release (X.Y.Z). Prompted if omitted."
    ),
    path: str | None = typer.Option(
        None, "--path", "-p", help="Path to project directory. Defaults to cwd."
    ),
    skip_checks: bool = typer.Option(
        False, "--skip-checks", help="Skip running checks (if you just ran them)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen without doing it."
    ),
) -> None:
    """Interactive tag-driven release: run checks, confirm, tag, push.

    The pushed vX.Y.Z tag triggers the repo's release workflow (build,
    attestations, trusted publishing, GitHub Release).
    """
    project_dir = Path(path) if path else Path.cwd()
    release_package(
        project_dir=project_dir,
        version=version,
        skip_checks=skip_checks,
        dry_run=dry_run,
    )


def run() -> None:  # pragma: no cover
    """Entry point for console scripts created by the build backend."""
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
