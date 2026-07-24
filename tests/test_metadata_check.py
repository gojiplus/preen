"""Tests for the metadata check: requires-python cap and py.typed."""

from pathlib import Path

import pytest

from preen.checks.metadata import MetadataCheck


def _write_pyproject(
    repo: Path, requires_python: str | None, typed: str | None = None
) -> None:
    lines = ["[project]", 'name = "mypkg"']
    if requires_python is not None:
        lines.append(f'requires-python = "{requires_python}"')
    if typed == "pyright":
        lines.append("")
        lines.append("[tool.pyright]")
    elif typed == "mypy":
        lines.append("")
        lines.append("[tool.mypy]")
    (repo / "pyproject.toml").write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize("requires_python", [">=3.11,<4", "~=3.12", "==3.12"])
def test_requires_python_cap_flagged(tmp_path: Path, requires_python: str) -> None:
    _write_pyproject(tmp_path, requires_python)
    result = MetadataCheck(tmp_path).run()
    assert not result.passed
    assert any("requires-python" in i.description for i in result.issues)


def test_requires_python_uncapped_clean(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ">=3.11")
    result = MetadataCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_requires_python_absent_is_info(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, None)
    result = MetadataCheck(tmp_path).run()
    assert result.passed
    assert len(result.issues) == 1
    assert result.issues[0].severity.value == "info"


def test_py_typed_missing_flagged(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ">=3.11", typed="pyright")
    pkg = tmp_path / "src" / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    result = MetadataCheck(tmp_path).run()
    assert not result.passed
    assert any("py.typed" in i.description for i in result.issues)


def test_py_typed_present_clean(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ">=3.11", typed="mypy")
    pkg = tmp_path / "src" / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "py.typed").write_text("")
    result = MetadataCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_untyped_project_clean(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ">=3.11")
    pkg = tmp_path / "src" / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    result = MetadataCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []
