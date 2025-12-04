"""Synchronisation utilities for preen.

This module contains the implementation of the `sync_project` function, which
generates a set of standard configuration files based on the metadata found in
a project's ``pyproject.toml``.  The goal of ``sync_project`` is to treat
``pyproject.toml`` as the single source of truth and update derivative files
such as GitHub Actions workflows, documentation configuration and a
``CITATION.cff`` accordingly.

The implementation is deliberately conservative and only performs a subset of
the full functionality described in the vision document.  It is intended to
provide a working foundation for Phase 1 of the project while leaving room
for future extension.  The function will create directories as needed and
overwrite existing generated files.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    # Python 3.11+ provides a built‑in TOML parser
    import tomllib  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    # Fallback to the tomli package if tomllib is unavailable
    import tomli as tomllib  # type: ignore


def _read_pyproject(path: Path) -> Dict[str, object]:
    """Read and parse a ``pyproject.toml`` file.

    Parameters
    ----------
    path:
        The path to the ``pyproject.toml`` file.

    Returns
    -------
    dict
        A nested dictionary representation of the TOML file.
    """
    with path.open("rb") as f:
        return tomllib.load(f)


def _get_project_metadata(pyproject: Dict[str, object]) -> Tuple[str, str, List[Dict[str, str]], str]:
    """Extract relevant project metadata from the parsed pyproject structure.

    Returns a tuple containing the project name, version, a list of authors and
    a license string.  Missing fields are handled gracefully by returning
    defaults.
    """
    project = pyproject.get("project", {}) or {}
    name = project.get("name", "unknown")
    version = project.get("version", "0.0.0")
    authors = project.get("authors", []) or []
    license_ = project.get("license", {})
    if isinstance(license_, dict):
        # PEP 621 license table can include a 'text' or 'file' key
        license_str = license_.get("text", "") or license_.get("file", "")
    else:
        license_str = str(license_ or "")
    license_str = license_str.strip() or "Unknown"
    return str(name), str(version), authors, license_str


def _extract_python_versions(pyproject: Dict[str, object]) -> List[str]:
    """Derive a list of Python versions from the classifiers in ``pyproject.toml``.

    If classifiers contain entries like ``Programming Language :: Python :: 3.10``
    then the suffixes (``3.10``) are collected.  The list is sorted and
    deduplicated.  If no such classifiers are found, a default list of recent
    Python versions is returned.
    """
    project = pyproject.get("project", {}) or {}
    classifiers = project.get("classifiers", []) or []
    versions = []
    for classifier in classifiers:
        if isinstance(classifier, str) and classifier.startswith("Programming Language :: Python :: "):
            parts = classifier.split("::")
            if parts:
                ver = parts[-1].strip()
                # Skip the generic 'Python' entry
                if ver and "." in ver:
                    versions.append(ver)
    # Default versions if nothing found
    if not versions:
        return ["3.9", "3.10", "3.11", "3.12"]
    # Sort versions semantically
    versions = sorted(set(versions), key=lambda v: [int(x) for x in v.split(".")])
    return versions


def _render_citation(name: str, version: str, authors: List[Dict[str, str]], license_str: str) -> str:
    """Render the contents of a ``CITATION.cff`` file.

    Parameters
    ----------
    name, version:
        The package name and version.

    authors:
        A list of author tables as specified in PEP 621.

    license_str:
        A human‑readable license identifier.

    Returns
    -------
    str
        The YAML content for ``CITATION.cff``.
    """
    today = _dt.date.today().isoformat()
    lines = [
        "# Synced from pyproject.toml by preen",
        "# Regenerate with: preen sync",
        "",
        "cff-version: 1.2.0",
        "message: \"If you use this software, please cite it as below.\"",
        f"title: {name}",
        f"version: {version}",
        f"date-released: {today}",
        f"url: https://pypi.org/project/{name}",
        f"repository-code: https://github.com/username/{name}",
        f"license: {license_str}",
        "authors:",
    ]
    for author in authors:
        name_field = author.get("name") or ""
        # Split into given and family names when possible
        given, family = ("", "")
        if name_field:
            parts = name_field.split()
            if len(parts) == 1:
                family = parts[0]
            else:
                given = " ".join(parts[:-1])
                family = parts[-1]
        entry = ["  -"]
        if family:
            entry.append(f"family-names: {family}")
        if given:
            entry.append(f"given-names: {given}")
        email = author.get("email")
        if email:
            entry.append(f"email: {email}")
        # Join keys with proper indentation
        lines.append("  - " + entry[1] if len(entry) > 1 else entry[0])
        if len(entry) > 2:
            for item in entry[2:]:
                lines.append(f"    {item}")
    return "\n".join(lines) + "\n"


def _render_docs_conf(name: str, author: str) -> str:
    """Render the contents of a Sphinx ``conf.py`` file.

    Parameters
    ----------
    name:
        The project name.

    author:
        The first author string.

    Returns
    -------
    str
        Python source code for Sphinx configuration.
    """
    return f"""# Generated by preen — do not edit manually
# Regenerate with: preen sync

import importlib.metadata

project = "{name}"
version = importlib.metadata.version("{name}")
author = "{author}"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

html_theme = "furo"

# MyST settings
myst_enable_extensions = ["colon_fence", "deflist"]

# Intersphinx mapping
intersphinx_mapping = {{
    "python": ("https://docs.python.org/3", None),
}}

# Napoleon settings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
"""


def _render_ci_yml(python_versions: List[str], os_list: Optional[List[str]] = None) -> str:
    """Render a GitHub Actions workflow for continuous integration.

    Parameters
    ----------
    python_versions:
        A list of Python versions to test against.

    os_list:
        Optional list of GitHub runner names.  Defaults to ["ubuntu-latest"].

    Returns
    -------
    str
        YAML content for ``ci.yml``.
    """
    os_list = os_list or ["ubuntu-latest"]
    # Convert lists to YAML lists
    python_str = ", ".join(f'"{v}"' for v in python_versions)
    os_str = ", ".join(os_list)
    return f"""# Generated by preen — do not edit manually
# Regenerate with: preen sync

name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ${{{{ matrix.os }}}}
    strategy:
      fail-fast: false
      matrix:
        python-version: [{python_str}]
        os: [{os_str}]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          python-version: ${{{{ matrix.python-version }}}}
      - run: uv sync --extra test
      - run: uv run pytest

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run ruff check
      - run: uv run ruff format --check
"""


def _render_release_yml(name: str) -> str:
    """Render a GitHub Actions workflow for releases.

    Parameters
    ----------
    name:
        The project name.

    Returns
    -------
    str
        YAML content for ``release.yml``.
    """
    return f"""# Generated by preen — do not edit manually
# Regenerate with: preen sync

name: Release

on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Version to release (must match pyproject.toml)'
        required: true

jobs:
  release:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - name: Verify version matches
        run: |
          TOML_VERSION=$(grep '^version = ' pyproject.toml | sed 's/version = \"\(.*\)\"/\1/')
          if [ "$TOML_VERSION" != "${{ inputs.version }}" ]; then
            echo "Version mismatch: pyproject.toml has $TOML_VERSION, input has ${{ inputs.version }}"
            exit 1
          fi
      - name: Build
        run: uv build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
      - name: Create Git tag
        run: |
          git tag v${{ inputs.version }}
          git push origin v${{ inputs.version }}
"""


def _render_docs_yml() -> str:
    """Render a GitHub Actions workflow for building documentation.

    Returns
    -------
    str
        YAML content for ``docs.yml``.
    """
    return """# Generated by preen — do not edit manually
# Regenerate with: preen sync

name: Docs

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --extra docs
      - run: uv run sphinx-build -b html docs docs/_build
      - name: Deploy to GitHub Pages
        if: github.ref == 'refs/heads/main'
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: docs/_build
"""


def sync_project(project_dir: str | Path, quiet: bool = False) -> Dict[str, str]:
    """Synchronise derived files based on ``pyproject.toml``.

    This function reads the project's ``pyproject.toml`` and writes a set of
    files that are derived from its metadata.  It always overwrites existing
    generated files and returns a mapping of relative file paths to the
    generated content.

    Parameters
    ----------
    project_dir:
        The root directory of the project.

    quiet:
        If true, suppresses printing informational messages.  The function
        always returns the mapping irrespective of this flag.

    Returns
    -------
    dict
        A mapping from the string path of each generated file to its contents.
    """
    root = Path(project_dir).resolve()
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        raise FileNotFoundError(f"No pyproject.toml found at {pyproject_path}")
    pyproject = _read_pyproject(pyproject_path)
    name, version, authors, license_str = _get_project_metadata(pyproject)
    python_versions = _extract_python_versions(pyproject)
    # Determine primary author string for docs conf
    author_str = ""
    if authors:
        first = authors[0]
        author_str = first.get("name", "") or ""
    # Render contents
    citation = _render_citation(name, version, authors, license_str)
    docs_conf = _render_docs_conf(name, author_str)
    ci_yml = _render_ci_yml(python_versions)
    release_yml = _render_release_yml(name)
    docs_yml = _render_docs_yml()
    # Prepare file mapping
    outputs = {
        "CITATION.cff": citation,
        "docs/conf.py": docs_conf,
        ".github/workflows/ci.yml": ci_yml,
        ".github/workflows/release.yml": release_yml,
        ".github/workflows/docs.yml": docs_yml,
    }
    # Write files to disk
    for rel_path, content in outputs.items():
        out_path = root / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        try:
            if out_path.is_file():
                existing = out_path.read_text(encoding="utf-8")
        except Exception:
            existing = ""
        if existing != content:
            out_path.write_text(content, encoding="utf-8")
            if not quiet:
                print(f"Updated {rel_path}")
        else:
            if not quiet:
                print(f"No changes for {rel_path}")
    return outputs