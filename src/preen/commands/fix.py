"""Fix command for applying targeted fixes."""

from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm

from ..checks import ALL_CHECKS, run_checks


def apply_fixes(
    project_dir: Path,
    check_name: str | None = None,
    interactive: bool = True,
    auto: bool = False,
    console: Console | None = None,
) -> None:
    """Apply fixes for a specific check or all checks.

    Args:
        project_dir: Path to project directory.
        check_name: Specific check to fix, or None for all.
        interactive: Ask before applying each fix.
        auto: Apply all fixes automatically.
        console: Rich console for output.

    Raises:
        typer.Exit: If an unknown check name is given.
    """
    console = console or Console()
    check_classes = ALL_CHECKS

    if check_name:
        available = {cls(project_dir).name: cls for cls in ALL_CHECKS}
        if check_name not in available:
            console.print(f"[red]Unknown check: {check_name}[/red]")
            console.print(f"Available checks: {', '.join(sorted(available))}")
            raise typer.Exit(1)
        check_classes = [available[check_name]]

    results = run_checks(project_dir, check_classes)

    fixable_issues = [
        issue
        for result in results.values()
        for issue in result.issues
        if issue.proposed_fix
    ]

    if not fixable_issues:
        scope = f" for {check_name}" if check_name else ""
        console.print(f"[green]No fixable issues found{scope}[/green]")
        return

    console.print(
        f"\n[bold cyan]preen fix[/bold cyan] — found "
        f"{len(fixable_issues)} fixable issue(s)\n"
    )

    fixed_count = 0
    skipped_count = 0

    for issue in fixable_issues:
        fix = issue.proposed_fix
        assert fix is not None  # noqa: S101 — filtered above
        console.print(f"[bold]Issue:[/bold] {issue.description}")
        if issue.explanation:
            console.print(f"[dim]{issue.explanation}[/dim]")

        if auto or not interactive:
            console.print("  Applying fix...")
            fix.apply()
            console.print("  [green]Fixed[/green]")
            fixed_count += 1
        else:
            console.print("\n[dim]Proposed fix:[/dim]")
            console.print(fix.preview())
            if Confirm.ask("\nApply this fix?", default=True):
                console.print("  Applying fix...")
                fix.apply()
                console.print("  [green]Fixed[/green]")
                fixed_count += 1
            else:
                console.print("  [yellow]Skipped[/yellow]")
                skipped_count += 1

        console.print()

    console.print("[bold green]Fix summary:[/bold green]")
    console.print(f"  {fixed_count} issue(s) fixed")
    if skipped_count > 0:
        console.print(f"  {skipped_count} issue(s) skipped")

    if fixed_count > 0:
        console.print("\nRun [cyan]preen check[/cyan] to verify fixes")
