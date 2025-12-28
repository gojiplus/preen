"""Fix command for applying targeted fixes."""

from __future__ import annotations

from pathlib import Path
# from typing import Optional  # No longer needed with Python 3.12+

import typer
from rich.console import Console
from rich.prompt import Confirm

from ..checks import run_checks
from ..checks.ruff import RuffCheck
from ..checks.tests import TestsCheck
from ..checks.citation import CitationCheck
from ..checks.deps import DepsCheck
from ..checks.deptree import DeptreeCheck
from ..checks.ci_matrix import CIMatrixCheck
from ..checks.structure import StructureCheck
from ..checks.version import VersionCheck


def apply_fixes(
    project_dir: Path,
    check_name: str | None = None,
    interactive: bool = True,
    auto: bool = False,
    console: Console | None = None,
) -> None:
    """
    Apply fixes for specific check or all checks.

    Args:
        project_dir: Path to project directory
        check_name: Specific check to fix, or None for all
        interactive: Ask before applying each fix
        auto: Apply all fixes automatically
        console: Rich console for output
    """
    console = console or Console()

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
    ]

    # Filter to specific check if requested
    if check_name:
        check_classes = [
            cls
            for cls in check_classes
            if cls.__name__.lower().replace("check", "") == check_name.lower()
        ]
        if not check_classes:
            console.print(f"❌ [red]Unknown check: {check_name}[/red]")
            available = [
                cls.__name__.lower().replace("check", "") for cls in check_classes
            ]
            console.print(f"Available checks: {', '.join(available)}")
            raise typer.Exit(1)

    # Run checks to find issues
    results = run_checks(project_dir, check_classes)

    # Collect fixable issues
    fixable_issues = []
    for result in results.values():
        for issue in result.issues:
            if issue.proposed_fix:
                fixable_issues.append(issue)

    if not fixable_issues:
        scope = f"for {check_name}" if check_name else ""
        console.print(f"✅ [green]No fixable issues found {scope}[/green]")
        return

    console.print(
        f"\n🔧 [bold cyan]preen fix[/bold cyan] - Found {len(fixable_issues)} fixable issue(s)\n"
    )

    # Apply fixes
    fixed_count = 0
    skipped_count = 0

    for issue in fixable_issues:
        console.print(f"[bold]Issue:[/bold] {issue.description}")
        if issue.explanation:
            console.print(f"[dim]{issue.explanation}[/dim]")

        if auto:
            # Apply automatically
            console.print("  🔧 Auto-applying fix...")
            issue.proposed_fix.apply()
            console.print("  ✅ [green]Fixed[/green]")
            fixed_count += 1

        elif interactive:
            # Ask user
            console.print("\n[dim]Proposed fix:[/dim]")
            console.print(issue.proposed_fix.preview())

            if Confirm.ask("\nApply this fix?", default=True):
                console.print("  🔧 Applying fix...")
                issue.proposed_fix.apply()
                console.print("  ✅ [green]Fixed[/green]")
                fixed_count += 1
            else:
                console.print("  ⏭️  [yellow]Skipped[/yellow]")
                skipped_count += 1
        else:
            # Non-interactive mode, apply all
            console.print("  🔧 Applying fix...")
            issue.proposed_fix.apply()
            console.print("  ✅ [green]Fixed[/green]")
            fixed_count += 1

        console.print()  # Blank line between fixes

    # Summary
    console.print("🎉 [bold green]Fix Summary:[/bold green]")
    console.print(f"  ✅ {fixed_count} issue(s) fixed")
    if skipped_count > 0:
        console.print(f"  ⏭️  {skipped_count} issue(s) skipped")

    if fixed_count > 0:
        console.print("\n💡 [blue]Run [cyan]preen check[/cyan] to verify fixes[/blue]")
