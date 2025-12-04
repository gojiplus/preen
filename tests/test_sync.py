"""Tests for the sync functionality of preen.

These tests exercise the ``sync_project`` function by creating temporary
projects with minimal ``pyproject.toml`` files and verifying that the
generated files contain expected values.  The tests use ``tempfile.TemporaryDirectory``
to ensure isolation and avoid polluting the working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from preen.syncer import sync_project


def write_pyproject(
    directory: Path, name: str = "mypackage", version: str = "0.1.0"
) -> None:
    """Helper to write a minimal pyproject.toml into the temporary directory."""
    content = f"""
[project]
name = "{name}"
version = "{version}"
authors = [{{ name = "Alice Example", email = "alice@example.com" }}]
classifiers = [
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
]
license = {{text = "MIT"}}
"""
    (directory / "pyproject.toml").write_text(content.strip() + "\n", encoding="utf-8")


def test_sync_creates_files(tmp_path: Path) -> None:
    """Ensure that sync_project generates all expected files."""
    write_pyproject(tmp_path)
    result = sync_project(tmp_path, quiet=True)

    # Get all files that were processed (updated + unchanged)
    all_files = set()
    all_files.update(result.get("updated", {}).keys())
    all_files.update(result.get("unchanged", {}).keys())

    # Expected files
    expected = {
        "CITATION.cff",
        "docs/conf.py",
        ".github/workflows/ci.yml",
        ".github/workflows/python-publish.yml",
        ".github/workflows/docs.yml",
    }
    assert all_files == expected

    # Verify files exist on disk
    for rel in expected:
        assert (tmp_path / rel).is_file()


def test_citation_contains_version_and_title(tmp_path: Path) -> None:
    """Check that the generated citation file contains the correct title and version."""
    name = "examplepkg"
    version = "0.2.1"
    write_pyproject(tmp_path, name=name, version=version)
    sync_project(tmp_path, quiet=True)
    citation_text = (tmp_path / "CITATION.cff").read_text(encoding="utf-8")
    assert f"title: {name}" in citation_text
    assert f"version: {version}" in citation_text


def test_missing_pyproject_raises(tmp_path: Path) -> None:
    """If no pyproject.toml exists in the directory, sync_project should raise."""
    with pytest.raises(FileNotFoundError):
        sync_project(tmp_path, quiet=True)
