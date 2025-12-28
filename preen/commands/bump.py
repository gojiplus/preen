"""Version bump command."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.prompt import Confirm

from ..syncer import sync_project

VersionPart = Literal["major", "minor", "patch"]


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse a semantic version string into components.

    Args:
        version_str: Version string like "1.2.3"

    Returns:
        Tuple of (major, minor, patch) integers

    Raises:
        ValueError: If version string is invalid
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[.-].*)?$", version_str)
    if not match:
        raise ValueError(f"Invalid version format: {version_str}")

    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def format_version(major: int, minor: int, patch: int) -> str:
    """Format version components into a string."""
    return f"{major}.{minor}.{patch}"


def bump_version(current_version: str, part: VersionPart) -> str:
    """Bump version according to semantic versioning rules.

    Args:
        current_version: Current version string
        part: Which part to bump ('major', 'minor', or 'patch')

    Returns:
        New version string
    """
    major, minor, patch = parse_version(current_version)

    match part:
        case "major":
            return format_version(major + 1, 0, 0)
        case "minor":
            return format_version(major, minor + 1, 0)
        case "patch":
            return format_version(major, minor, patch + 1)
        case _:
            raise ValueError(f"Invalid version part: {part}")


def get_current_version(project_dir: Path) -> str:
    """Get current version from pyproject.toml.

    Args:
        project_dir: Project directory path

    Returns:
        Current version string

    Raises:
        FileNotFoundError: If pyproject.toml doesn't exist
        ValueError: If version is not found or invalid
    """
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError("pyproject.toml not found")

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore

    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    version = data.get("project", {}).get("version")
    if not version:
        raise ValueError("Version not found in pyproject.toml [project] section")

    return version


def update_pyproject_version(project_dir: Path, new_version: str) -> None:
    """Update version in pyproject.toml.

    Args:
        project_dir: Project directory path
        new_version: New version string
    """
    pyproject_path = project_dir / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")

    # Find and replace version line
    pattern = r'^(version\s*=\s*["\'])([^"\']+)(["\'])'

    def replace_version(match):
        return f"{match.group(1)}{new_version}{match.group(3)}"

    new_content = re.sub(pattern, replace_version, content, flags=re.MULTILINE)

    if new_content == content:
        raise ValueError("Could not find version line in pyproject.toml")

    pyproject_path.write_text(new_content, encoding="utf-8")


def is_git_repo(project_dir: Path) -> bool:
    """Check if directory is a git repository."""
    return (project_dir / ".git").exists()


def is_git_clean(project_dir: Path) -> bool:
    """Check if git working directory is clean."""
    if not is_git_repo(project_dir):
        return True

    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=project_dir,
    )
    return result.returncode == 0 and not result.stdout.strip()


def commit_version_bump(project_dir: Path, new_version: str) -> None:
    """Commit the version bump to git.

    Args:
        project_dir: Project directory path
        new_version: New version string
    """
    if not is_git_repo(project_dir):
        return

    # Add changed files
    subprocess.run(["git", "add", "."], cwd=project_dir, check=True)

    # Commit
    commit_message = f"Bump version to {new_version}"
    subprocess.run(
        ["git", "commit", "-m", commit_message],
        cwd=project_dir,
        check=True,
    )


def bump_package_version(
    part: VersionPart,
    project_dir: Path | None = None,
    commit: bool = True,
    dry_run: bool = False,
) -> None:
    """Bump package version and sync derived files.

    Args:
        part: Which part of version to bump
        project_dir: Project directory (defaults to current)
        commit: Whether to commit changes to git
        dry_run: Show what would be done without making changes
    """
    console = Console()

    if project_dir is None:
        project_dir = Path.cwd()

    # Get current version
    try:
        current_version = get_current_version(project_dir)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # Calculate new version
    try:
        new_version = bump_version(current_version, part)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"\\n[bold]Version bump:[/bold] {current_version} → {new_version}")

    if dry_run:
        console.print("\\n[dim]Dry run - no changes will be made[/dim]")
        console.print("\\n[bold]Would update:[/bold]")
        console.print("  • pyproject.toml")
        console.print("  • Derived files (CITATION.cff, workflows, etc.)")
        if commit and is_git_repo(project_dir):
            console.print("  • Git commit")
        return

    # Check git status if committing
    if commit and is_git_repo(project_dir) and not is_git_clean(project_dir):
        console.print("\\n[yellow]Warning: Git working directory is not clean[/yellow]")
        if not Confirm.ask("Continue anyway?"):
            console.print("Aborted.")
            raise typer.Exit(0)

    # Update pyproject.toml
    try:
        update_pyproject_version(project_dir, new_version)
        console.print("[green]✓[/green] Updated pyproject.toml")
    except Exception as e:
        console.print(f"[red]Error updating pyproject.toml: {e}[/red]")
        raise typer.Exit(1)

    # Sync derived files
    console.print("\\n[bold]Syncing derived files...[/bold]")
    try:
        sync_result = sync_project(project_dir, quiet=True)
        updated_count = len(sync_result["updated"])
        if updated_count > 0:
            console.print(f"[green]✓[/green] Updated {updated_count} derived files")
        else:
            console.print("[dim]○[/dim] No derived files needed updating")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not sync all files: {e}[/yellow]")

    # Commit changes
    if commit and is_git_repo(project_dir):
        try:
            commit_version_bump(project_dir, new_version)
            console.print("[green]✓[/green] Committed version bump to git")
        except subprocess.CalledProcessError as e:
            console.print(f"[yellow]Warning: Could not commit to git: {e}[/yellow]")

    console.print(f"\\n[bold green]✓ Version bumped to {new_version}![/bold green]")
