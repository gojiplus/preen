"""Release command implementing devtools::release() pattern."""

from __future__ import annotations

import subprocess
from pathlib import Path
# from typing import List, Optional  # No longer needed with Python 3.12+

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
from ..interactive import InteractiveReleaseWorkflow


def release_to_pypi(
    project_dir: Path,
    target: str = "pypi",
    skip_checks: bool = False,
    dry_run: bool = False,
    console: Console | None = None,
) -> None:
    """
    Interactive release workflow similar to devtools::release().

    Args:
        project_dir: Path to project directory
        target: Release target (pypi, github, both)
        skip_checks: Skip running checks (if you just ran them)
        dry_run: Show what would happen without doing it
        console: Rich console for output
    """
    console = console or Console()
    workflow = InteractiveReleaseWorkflow(console)

    console.print(
        "\n🔍 [bold cyan]preen release[/bold cyan] - Interactive release workflow\n"
    )

    # Run checks unless skipped
    if not skip_checks:
        console.print("Running pre-release checks...\n")

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

        results = run_checks(project_dir, check_classes)
    else:
        console.print("⚠️  [yellow]Skipping checks as requested[/yellow]\n")
        results = {}

    # Run interactive workflow
    if not workflow.run_release_checks(results, target.upper()):
        console.print("\n❌ [red]Release cancelled[/red]")
        raise typer.Exit(1)

    # Execute release steps
    if dry_run:
        console.print("\n🔍 [yellow]DRY RUN - Would perform release steps:[/yellow]")
        _show_release_steps(target, console)
    else:
        _execute_release(project_dir, target, console)


def _show_release_steps(target: str, console: Console) -> None:
    """Show what release steps would be executed."""
    steps = _get_release_steps(target)

    for i, step in enumerate(steps, 1):
        console.print(f"  {i}. {step}")


def _get_release_steps(target: str) -> list[str]:
    """Get list of release steps for target."""
    steps = []

    if target.lower() in ["pypi", "both"]:
        steps.extend(
            [
                "Build package: python -m build",
                "Check built package: twine check dist/*",
                "Upload to PyPI: twine upload dist/*",
            ]
        )

    if target.lower() in ["github", "both"]:
        steps.extend(
            [
                "Create git tag for version",
                "Push tag to GitHub",
                "Create GitHub release with gh cli",
            ]
        )

    return steps


def _execute_release(project_dir: Path, target: str, console: Console) -> None:
    """Execute the actual release steps."""
    console.print("\n🚀 [bold green]Executing release...[/bold green]\n")

    if target.lower() in ["pypi", "both"]:
        _release_to_pypi(project_dir, console)

    if target.lower() in ["github", "both"]:
        _release_to_github(project_dir, console)

    console.print("\n🎉 [bold green]Release completed successfully![/bold green]")


def _release_to_pypi(project_dir: Path, console: Console) -> None:
    """Execute PyPI release steps."""
    console.print("📦 [bold]Building package...[/bold]")

    # Clean dist directory
    dist_dir = project_dir / "dist"
    if dist_dir.exists():
        import shutil

        shutil.rmtree(dist_dir)

    # Build package
    result = subprocess.run(
        ["python", "-m", "build"], cwd=project_dir, capture_output=True, text=True
    )

    if result.returncode != 0:
        console.print(f"❌ [red]Build failed:[/red] {result.stderr}")
        raise typer.Exit(1)

    console.print("✅ Package built successfully")

    # Check package
    console.print("🔍 [bold]Checking package...[/bold]")
    result = subprocess.run(
        ["twine", "check", "dist/*"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        shell=True,
    )

    if result.returncode != 0:
        console.print(f"❌ [red]Package check failed:[/red] {result.stderr}")
        raise typer.Exit(1)

    console.print("✅ Package check passed")

    # Upload to PyPI
    if Confirm.ask("🚀 Upload to PyPI now?"):
        console.print("📤 [bold]Uploading to PyPI...[/bold]")
        result = subprocess.run(
            ["twine", "upload", "dist/*"], cwd=project_dir, shell=True
        )

        if result.returncode != 0:
            console.print("❌ [red]Upload failed[/red]")
            raise typer.Exit(1)

        console.print("✅ [green]Successfully uploaded to PyPI![/green]")
    else:
        console.print(
            "ℹ️  [blue]Upload skipped. Run 'twine upload dist/*' manually when ready.[/blue]"
        )


def _release_to_github(project_dir: Path, console: Console) -> None:
    """Execute GitHub release steps."""
    console.print("🏷️  [bold]Creating GitHub release...[/bold]")

    # TODO: Implement GitHub release creation
    # - Read version from pyproject.toml
    # - Create git tag
    # - Push tag
    # - Create GitHub release with gh cli

    console.print("ℹ️  [blue]GitHub release creation not yet implemented[/blue]")
