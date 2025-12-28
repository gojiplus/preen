"""Synchronisation utilities for preen.

This module contains the implementation of the `sync_project` function, which
generates a set of standard configuration files based on the metadata found in
a project's ``pyproject.toml``.  The goal of ``sync_project`` is to treat
``pyproject.toml`` as the single source of truth and update derivative files
such as GitHub Actions workflows, documentation configuration and a
``CITATION.cff`` accordingly.

The implementation is deliberately conservative and only performs a subset of
the full functionality described in the vision document.  It is intended to
provide a working foundation for Phase 1 of the project while leaving room
for future extension.  The function will create directories as needed and
overwrite existing generated files.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

from .config import PreenConfig

try:
    # Python 3.11+ provides a built‑in TOML parser
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


def _get_project_metadata(
    pyproject: Dict[str, object],
) -> Tuple[str, str, List[Dict[str, str]], str]:
    """Extract relevant project metadata from the parsed pyproject structure.

    Returns a tuple of (name, version, authors, license).
    """
    project = pyproject.get("project", {})
    name = project.get("name", "unknown")
    version = project.get("version", "0.0.0")
    authors = project.get("authors", [])
    license_data = project.get("license", {})
    # License can be a string or dict with text key
    license_str = ""
    if isinstance(license_data, str):
        license_str = license_data
    elif isinstance(license_data, dict):
        license_str = license_data.get("text", "")
    return name, version, authors, license_str


def _extract_python_versions(pyproject: Dict[str, object]) -> List[str]:
    """Extract the list of Python versions from classifiers or requires‑python.

    Parameters
    ----------
    pyproject:
        The parsed ``pyproject.toml`` dictionary.

    Returns
    -------
    list
        A list of Python version strings such as ["3.9", "3.10", "3.11"].
    """
    project = pyproject.get("project", {})
    classifiers = project.get("classifiers", [])
    versions = []
    for classifier in classifiers:
        if classifier.startswith("Programming Language :: Python :: 3."):
            # Extract version like "3.9" from "Programming Language :: Python :: 3.9"
            parts = classifier.split(" :: ")
            if len(parts) == 4 and parts[-1][0].isdigit():
                versions.append(parts[-1])
    # If no explicit versions, generate defaults
    if not versions:
        versions = ["3.9", "3.10", "3.11", "3.12"]
    return versions


def _render_citation(
    name: str, version: str, authors: List[Dict[str, str]], license_str: str
) -> str:
    """Generate the content for a ``CITATION.cff`` file.

    Parameters
    ----------
    name:
        The project name.

    version:
        The project version string.

    authors:
        A list of author dictionaries with "name" and "email" keys.

    license_str:
        The project license string.

    Returns
    -------
    str
        YAML content for ``CITATION.cff``.
    """
    today_str = _dt.datetime.now().date().isoformat()
    lines = [
        "# Synced from pyproject.toml by preen",
        "# Regenerate with: preen sync",
        "",
        "cff-version: 1.2.0",
        'message: "If you use this software, please cite it as below."',
        f"title: {name}",
        f"version: {version}",
        f"date-released: {today_str}",
    ]
    # Add URL fields (placeholder, would need to be extracted from pyproject)
    lines.extend(
        [
            f"url: https://github.com/gojiplus/{name}",
            f"repository-code: https://github.com/gojiplus/{name}",
        ]
    )
    if license_str:
        lines.append(f"license: {license_str}")
    if authors:
        lines.append("authors:")
        for author in authors:
            author_name = author.get("name", "")
            author_email = author.get("email", "")
            if not author_name:
                continue
            # Split name into first and last
            parts = author_name.rsplit(" ", 1)
            if len(parts) == 2:
                given, family = parts
            else:
                given, family = "", author_name
            lines.append(f"  - family-names: {family}")
            if given:
                lines.append(f"    given-names: {given}")
            if author_email:
                lines.append(f"    email: {author_email}")
    return "\n".join(lines) + "\n"


def _render_docs_conf(name: str, author: str, config: PreenConfig) -> str:
    """Generate the content for a Sphinx ``conf.py`` file.

    Parameters
    ----------
    name:
        The project name.

    author:
        The primary author name.

    config:
        The preen configuration object.

    Returns
    -------
    str
        Python code for ``docs/conf.py``.
    """
    extensions = [
        '"sphinx.ext.autodoc"',
        '"sphinx.ext.napoleon"',
        '"sphinx.ext.viewcode"',
        '"sphinx.ext.intersphinx"',
    ]
    if config.use_myst:
        extensions.append('"myst_parser"')

    extensions_str = ",\n    ".join(extensions)

    conf = f'''# Generated by preen — do not edit manually
# Regenerate with: preen sync

import importlib.metadata

project = "{name}"
version = importlib.metadata.version("{name}")
author = "{author}"

extensions = [
    {extensions_str},
]

html_theme = "{config.sphinx_theme}"
'''

    if config.use_myst:
        conf += """
# MyST settings
myst_enable_extensions = [
    "colon_fence",
    "deflist",
]
"""

    conf += """
# Intersphinx
intersphinx_mapping = {{
    "python": ("https://docs.python.org/3", None),
}}

# Napoleon settings (Google style)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
"""

    return conf


def _render_ci_yml(python_versions: List[str], config: PreenConfig) -> str:
    """Generate the content for a CI workflow file.

    Parameters
    ----------
    python_versions:
        A list of Python versions to test against.

    config:
        The preen configuration object.

    Returns
    -------
    str
        YAML content for ``ci.yml``.
    """
    os_list = config.ci_os
    runner = config.ci_runner

    # Convert lists to YAML lists
    python_str = ", ".join(f'"{v}"' for v in python_versions)
    os_str = ", ".join(os_list)

    # Determine commands based on runner
    if runner == "uv":
        setup_step = """      - uses: astral-sh/setup-uv@v4
        with:
          python-version: ${{ matrix.python-version }}"""
        test_commands = """      - run: uv sync
      - run: uv run pytest"""
        lint_setup = "      - uses: astral-sh/setup-uv@v4"
        lint_commands = """      - run: uv sync
      - run: uv run ruff check
      - run: uv run ruff format --check"""
    else:
        setup_step = """      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e .[test]"""
        test_commands = "      - run: pytest"
        lint_setup = """      - uses: actions/setup-python@v5
        with:
          python-version: "3.12" """
        lint_commands = """      - run: pip install ruff
      - run: ruff check
      - run: ruff format --check"""

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
{setup_step}
{test_commands}

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
{lint_setup}
{lint_commands}
"""


def _render_python_publish_yml(name: str, config: PreenConfig) -> str:
    """Generate the content for a PyPI publishing workflow file.

    Parameters
    ----------
    name:
        The project name.

    config:
        The preen configuration object.

    Returns
    -------
    str
        YAML content for ``python-publish.yml``.
    """
    return f"""# Generated by preen — do not edit manually
# Regenerate with: preen sync

name: Publish Python Package

on:
  release:
    types: [published]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - name: Build package
        run: uv build
      - uses: actions/upload-artifact@v4
        with:
          name: python-package-distributions
          path: dist/

  publish-to-pypi:
    name: Publish to PyPI
    if: startsWith(github.ref, 'refs/tags/')  # only publish on tag pushes
    needs:
      - build
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/{name}
    permissions:
      id-token: write  # IMPORTANT: mandatory for trusted publishing

    steps:
      - name: Download all the dists
        uses: actions/download-artifact@v4
        with:
          name: python-package-distributions
          path: dist/
      - name: Publish distribution to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
"""


def _render_docs_yml() -> str:
    """Generate the content for a docs workflow file.

    Returns
    -------
    str
        YAML content for ``docs.yml``.
    """
    return """# Generated by preen — do not edit manually
# Regenerate with: preen sync

name: Documentation

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Setup uv
        uses: astral-sh/setup-uv@v4
      - name: Install dependencies
        run: uv sync --extra docs
      - name: Setup Pages
        uses: actions/configure-pages@v4
      - name: Build documentation
        run: |
          uv run sphinx-build -W -b html docs docs/_build/html
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: docs/_build/html

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    needs: build
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
"""


def sync_project(
    project_dir: str | Path,
    quiet: bool = False,
    check: bool = False,
    targets: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, str]]:
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

    check:
        If true, only checks if files would change without writing them.
        Returns exit code 1 if any files would change.

    targets:
        If specified, only sync these targets. Valid values:
        'ci', 'citation', 'docs', 'workflows'

    Returns
    -------
    dict
        A mapping with 'updated', 'unchanged', and 'would_change' keys.
    """
    root = Path(project_dir).resolve()
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.is_file():
        raise FileNotFoundError(f"No pyproject.toml found at {pyproject_path}")

    # Load configuration
    config = PreenConfig.from_pyproject(root)

    pyproject = _read_pyproject(pyproject_path)
    name, version, authors, license_str = _get_project_metadata(pyproject)
    python_versions = config.get_ci_python_versions(pyproject)

    # Determine primary author string for docs conf
    author_str = ""
    if authors:
        first = authors[0]
        author_str = first.get("name", "") or ""

    # Render contents
    all_outputs = {
        "citation": {
            "CITATION.cff": _render_citation(name, version, authors, license_str)
        },
        "docs": {str(Path("docs") / "conf.py"): _render_docs_conf(name, author_str, config)},
        "ci": {str(Path(".github") / "workflows" / "ci.yml"): _render_ci_yml(python_versions, config)},
        "workflows": {
            str(Path(".github") / "workflows" / "python-publish.yml"): _render_python_publish_yml(
                name, config
            ),
            str(Path(".github") / "workflows" / "docs.yml"): _render_docs_yml(),
        },
    }

    # Filter outputs based on targets
    if targets:
        outputs = {}
        for target in targets:
            if target in all_outputs:
                outputs.update(all_outputs[target])
            elif target == "ci":
                # ci is an alias for the CI workflow specifically
                outputs.update(all_outputs.get("ci", {}))
    else:
        # Flatten all outputs
        outputs = {}
        for target_outputs in all_outputs.values():
            outputs.update(target_outputs)

    # Track changes
    result = {
        "updated": {},
        "unchanged": {},
        "would_change": {},
    }

    # Check or write files to disk
    for rel_path, content in outputs.items():
        out_path = root / rel_path

        existing = ""
        try:
            if out_path.is_file():
                existing = out_path.read_text(encoding="utf-8")
        except Exception:
            existing = ""

        if existing != content:
            if check:
                result["would_change"][rel_path] = content
                if not quiet:
                    print(f"Would update: {rel_path}")
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content, encoding="utf-8")
                result["updated"][rel_path] = content
                if not quiet:
                    print(f"✓ Updated: {rel_path}")
        else:
            result["unchanged"][rel_path] = content
            if not quiet:
                print(f"○ Unchanged: {rel_path}")

    # Exit with error code if in check mode and files would change
    if check and result["would_change"]:
        if not quiet:
            print(f"\n❌ {len(result['would_change'])} file(s) would be updated")
        sys.exit(1)

    return result
