"""Scaffold a new package from the py-canon copier template."""

from pathlib import Path
from typing import Any

from rich.console import Console

from ..adopt import CANON_TEMPLATE


def new_package(
    name: str,
    org: str | None = None,
    description: str | None = None,
    cli: bool | None = None,
    console: Console | None = None,
) -> Path:
    """Scaffold a new package with copier.

    Args:
        name: Distribution/project name; also the destination directory.
        org: GitHub org/owner (copier prompts if omitted).
        description: One-line description (copier prompts if omitted).
        cli: Whether to ship a console script (copier prompts if omitted).
        console: Rich console for output.

    Returns:
        Path to the created project directory.
    """
    from copier import run_copy

    console = console or Console()
    dest = Path(name)
    project_name = dest.name
    data: dict[str, Any] = {"project_name": project_name}
    if org is not None:
        data["org"] = org
    if description is not None:
        data["description"] = description
    if cli is not None:
        data["needs_cli"] = cli

    console.print(f"Scaffolding [bold]{project_name}[/bold] from {CANON_TEMPLATE} ...")
    run_copy(CANON_TEMPLATE, dest, data=data, unsafe=True)
    console.print(f"\n[green]Created {dest}/[/green]")
    console.print("Next steps: cd into it, 'git init', 'uv lock', 'uv sync'.")
    return dest
