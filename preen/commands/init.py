"""Init command for creating new packages."""

from __future__ import annotations

import re
from pathlib import Path
# from typing import Any, Dict  # No longer needed with Python 3.12+
from typing import Any

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from ..templates import TemplateManager
from ..syncer import sync_project


def is_valid_package_name(name: str) -> bool:
    """Check if package name follows Python naming conventions."""
    # Must be valid Python identifier and follow PEP 508
    return (
        name.isidentifier()
        and not name.startswith("_")
        and re.match(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", name) is not None
    )


def get_package_metadata() -> dict[str, Any]:
    """Collect package metadata from user input."""
    console = Console()

    # Package name
    while True:
        package_name = (
            Prompt.ask(
                "Package name",
                default="",
            )
            .strip()
            .lower()
        )

        if not package_name:
            console.print("[red]Package name is required[/red]")
            continue

        if not is_valid_package_name(package_name):
            console.print(
                "[red]Package name must be a valid Python identifier "
                "(lowercase, no dashes, underscores only)[/red]"
            )
            continue

        break

    # Other metadata
    description = Prompt.ask(
        "Description",
        default="A Python package",
    ).strip()

    author_name = Prompt.ask(
        "Author name",
        default="Your Name",
    ).strip()

    author_email = Prompt.ask(
        "Author email",
        default="you@example.com",
    ).strip()

    version = Prompt.ask(
        "Initial version",
        default="0.1.0",
    ).strip()

    min_python = Prompt.ask(
        "Minimum Python version",
        default="3.9",
        choices=["3.9", "3.10", "3.11", "3.12"],
    )

    license_name = Prompt.ask(
        "License",
        default="MIT",
        choices=["MIT", "Apache-2.0", "GPL-3.0", "BSD-3-Clause"],
    )

    # URLs
    github_username = Prompt.ask(
        "GitHub username/organization",
        default="yourname",
    ).strip()

    repository_url = f"https://github.com/{github_username}/{package_name}"
    homepage_url = repository_url

    # CLI option
    has_cli = Confirm.ask("Include CLI command?", default=False)

    return {
        "package_name": package_name,
        "description": description,
        "author_name": author_name,
        "author_email": author_email,
        "version": version,
        "min_python_version": min_python,
        "license": license_name,
        "repository_url": repository_url,
        "homepage_url": homepage_url,
        "github_username": github_username,
        "has_cli": has_cli,
    }


def create_package_structure(
    target_dir: Path, metadata: dict[str, Any], src_layout: bool = True
) -> None:
    """Create the package directory structure."""
    console = Console()
    package_name = metadata["package_name"]

    # Create directories
    target_dir.mkdir(parents=True, exist_ok=True)

    if src_layout:
        package_dir = target_dir / "src" / package_name
    else:
        package_dir = target_dir / package_name

    package_dir.mkdir(parents=True, exist_ok=True)

    tests_dir = target_dir / "tests"
    tests_dir.mkdir(exist_ok=True)

    # Create package files
    template_manager = TemplateManager()

    # pyproject.toml
    pyproject_content = template_manager.render("pyproject.toml.tmpl", metadata)
    (target_dir / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")
    console.print("[green]✓[/green] Created pyproject.toml")

    # Package __init__.py
    init_content = template_manager.render("__init__.py.tmpl", metadata)
    (package_dir / "__init__.py").write_text(init_content, encoding="utf-8")
    console.print(f"[green]✓[/green] Created {package_dir / '__init__.py'}")

    # CLI if requested
    if metadata["has_cli"]:
        cli_content = template_manager.render("cli.py.tmpl", metadata)
        (package_dir / "cli.py").write_text(cli_content, encoding="utf-8")
        console.print(f"[green]✓[/green] Created {package_dir / 'cli.py'}")

    # Basic test
    test_content = template_manager.render("test_basic.py.tmpl", metadata)
    (tests_dir / "test_basic.py").write_text(test_content, encoding="utf-8")
    console.print("[green]✓[/green] Created tests/test_basic.py")

    # README.md
    readme_content = template_manager.render("README.md.tmpl", metadata)
    (target_dir / "README.md").write_text(readme_content, encoding="utf-8")
    console.print("[green]✓[/green] Created README.md")

    # .gitignore
    gitignore_content = template_manager.render(".gitignore.tmpl", metadata)
    (target_dir / ".gitignore").write_text(gitignore_content, encoding="utf-8")
    console.print("[green]✓[/green] Created .gitignore")

    # Create LICENSE file
    create_license_file(target_dir, metadata["license"])
    console.print("[green]✓[/green] Created LICENSE")


def create_license_file(target_dir: Path, license_name: str) -> None:
    """Create LICENSE file based on license type."""
    license_texts = {
        "MIT": """MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.""",
        "Apache-2.0": """Apache License
Version 2.0, January 2004
http://www.apache.org/licenses/

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.""",
    }

    license_text = license_texts.get(license_name, f"See {license_name} license terms.")
    (target_dir / "LICENSE").write_text(license_text + "\n", encoding="utf-8")


def init_package(
    package_name: str | None = None,
    target_dir: Path | None = None,
) -> None:
    """Initialize a new package."""
    console = Console()

    if package_name:
        # Non-interactive mode
        if not is_valid_package_name(package_name):
            console.print("[red]Invalid package name[/red]")
            raise typer.Exit(1)

        # Use defaults for non-interactive
        metadata = {
            "package_name": package_name,
            "description": "A Python package",
            "author_name": "Your Name",
            "author_email": "you@example.com",
            "version": "0.1.0",
            "min_python_version": "3.9",
            "license": "MIT",
            "repository_url": f"https://github.com/yourname/{package_name}",
            "homepage_url": f"https://github.com/yourname/{package_name}",
            "github_username": "yourname",
            "has_cli": False,
        }
    else:
        # Interactive mode
        console.print(
            "\n[bold cyan]preen init[/bold cyan] - Create a new Python package\n"
        )
        metadata = get_package_metadata()

    if target_dir is None:
        target_dir = Path.cwd() / metadata["package_name"]

    # Check if target directory exists and is not empty
    if target_dir.exists() and any(target_dir.iterdir()):
        if not Confirm.ask(
            f"Directory {target_dir} exists and is not empty. Continue?"
        ):
            console.print("Aborted.")
            raise typer.Exit(0)

    # Create package structure
    console.print(f"\n[bold]Creating package: {metadata['package_name']}[/bold]")
    console.print(f"[dim]Location: {target_dir}[/dim]\n")

    create_package_structure(target_dir, metadata)

    # Generate derived files with preen sync
    console.print("\n[bold]Generating project files...[/bold]")
    try:
        sync_project(target_dir, quiet=False)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not generate all files: {e}[/yellow]")

    # Success message
    console.print(
        f"\n[bold green]✓ Package '{metadata['package_name']}' created successfully![/bold green]"
    )
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  cd {target_dir.name}")
    console.print("  pip install -e .[dev]")
    console.print("  preen check")

    if metadata["has_cli"]:
        console.print(f"  {metadata['package_name']} --help")
