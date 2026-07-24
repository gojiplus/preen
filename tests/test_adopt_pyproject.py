"""Tests for adopt's tomlkit pyproject surgery."""

import tomllib
from pathlib import Path

import pytest

from preen.adopt import rewrite_pyproject

LEGACY_PYPROJECT = """\
# top-of-file comment that must survive
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "legacy-pkg"
version = "1.2.3"
description = "A legacy package"
requires-python = ">=3.9"
authors = [{ name = "Alice Example", email = "alice@example.com" }]
dependencies = ["requests"]

[project.scripts]
legacy-pkg = "legacy_pkg.cli:main"

[tool.black]
line-length = 100

[tool.isort]
profile = "black"

[tool.flake8]
max-line-length = 100

[tool.mypy]
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]

[dependency-groups]
docs = ["sphinx>=7"]
"""


@pytest.fixture
def legacy_repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(LEGACY_PYPROJECT)
    pkg = tmp_path / "legacy_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    return tmp_path


def _load(repo: Path) -> dict:
    with (repo / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_legacy_tool_sections_removed(legacy_repo: Path) -> None:
    rewrite_pyproject(legacy_repo)
    data = _load(legacy_repo)
    tool = data["tool"]
    for legacy in ("black", "isort", "flake8", "mypy"):
        assert legacy not in tool


def test_standard_tool_sections_set(legacy_repo: Path) -> None:
    changes = rewrite_pyproject(legacy_repo)
    data = _load(legacy_repo)
    ruff = data["tool"]["ruff"]
    assert ruff["line-length"] == 88
    assert "D" in ruff["lint"]["select"]
    assert ruff["lint"]["pydocstyle"]["convention"] == "google"
    assert ruff["lint"]["per-file-ignores"]["tests/**"] == ["S101", "D"]
    assert data["tool"]["pyright"] == {
        "include": ["legacy_pkg"],
        "typeCheckingMode": "standard",
    }
    assert data["tool"]["pydoclint"] == {
        "style": "google",
        "arg-type-hints-in-docstring": False,
        "check-return-types": False,
        "check-class-attributes": False,
        "allow-init-docstring": True,
        "exclude": "\\.venv|tests|docs",
    }
    assert any("[tool.ruff]" in c for c in changes)


def test_docs_group_updated(legacy_repo: Path) -> None:
    rewrite_pyproject(legacy_repo)
    data = _load(legacy_repo)
    docs = data["dependency-groups"]["docs"]
    # Existing sphinx pin is kept, missing entries appended.
    assert "sphinx>=7" in docs
    assert "furo" in docs
    assert "myst-parser" in docs
    assert "sphinx-copybutton" in docs
    assert "py-canon @ git+https://github.com/gojiplus/py-canon@v1" in docs
    # No duplicate sphinx entry.
    assert sum(1 for d in docs if d.startswith("sphinx>")) == 1


def test_docs_group_created_when_absent(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "bare"\nversion = "0.1.0"\n'
    )
    rewrite_pyproject(tmp_path)
    data = _load(tmp_path)
    docs = data["dependency-groups"]["docs"]
    assert "sphinx>=8" in docs


def test_comments_and_untouched_sections_survive(legacy_repo: Path) -> None:
    rewrite_pyproject(legacy_repo)
    text = (legacy_repo / "pyproject.toml").read_text()
    assert "# top-of-file comment that must survive" in text
    data = _load(legacy_repo)
    assert data["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    assert data["project"]["version"] == "1.2.3"
    assert data["build-system"]["build-backend"] == "setuptools.build_meta"


def test_release_migration_converts_build_system(legacy_repo: Path) -> None:
    rewrite_pyproject(legacy_repo, release_migration=True)
    data = _load(legacy_repo)
    assert data["build-system"]["requires"] == ["hatchling", "uv-dynamic-versioning"]
    assert data["build-system"]["build-backend"] == "hatchling.build"
    assert "version" not in data["project"]
    assert "version" in data["project"]["dynamic"]
    assert data["tool"]["hatch"]["version"]["source"] == "uv-dynamic-versioning"
    assert data["tool"]["uv-dynamic-versioning"]["vcs"] == "git"
    # Flat layout detected.
    assert data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "legacy_pkg"
    ]


def test_release_migration_src_layout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "srcpkg"\nversion = "0.1.0"\n'
    )
    pkg = tmp_path / "src" / "srcpkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    rewrite_pyproject(tmp_path, release_migration=True)
    data = _load(tmp_path)
    assert data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/srcpkg"
    ]


def test_missing_pyproject_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        rewrite_pyproject(tmp_path)


def _write_pyproject(tmp_path: Path, body: str, package: str = "pkg") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{package}"\nversion = "0.1.0"\n\n{body}'
    )
    pkg = tmp_path / package
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    return tmp_path


def test_ruff_extra_ignores_preserved(tmp_path: Path) -> None:
    repo = _write_pyproject(
        tmp_path,
        "[tool.ruff]\nline-length = 100\n\n"
        '[tool.ruff.lint]\nselect = ["E"]\nignore = ["S603", "S607"]\n',
    )
    changes = rewrite_pyproject(repo)
    data = _load(repo)
    ignore = data["tool"]["ruff"]["lint"]["ignore"]
    # Canon codes first (in canon order), then extra repo codes, sorted.
    assert ignore == ["D203", "D213", "S603", "S607"]
    assert any("preserved" in c and "S603" in c and "S607" in c for c in changes)


def test_ruff_legacy_top_level_ignore_preserved(tmp_path: Path) -> None:
    repo = _write_pyproject(
        tmp_path,
        '[tool.ruff]\nline-length = 100\nignore = ["S603"]\n',
    )
    rewrite_pyproject(repo)
    data = _load(repo)
    assert data["tool"]["ruff"]["lint"]["ignore"] == ["D203", "D213", "S603"]


def test_ruff_no_existing_section_ignore_is_canon_only(tmp_path: Path) -> None:
    repo = _write_pyproject(tmp_path, "")
    rewrite_pyproject(repo)
    data = _load(repo)
    assert data["tool"]["ruff"]["lint"]["ignore"] == ["D203", "D213"]


def test_ruff_ignore_merge_is_idempotent(tmp_path: Path) -> None:
    repo = _write_pyproject(
        tmp_path,
        "[tool.ruff]\nline-length = 100\n\n"
        '[tool.ruff.lint]\nselect = ["E"]\nignore = ["S603", "S607"]\n',
    )
    rewrite_pyproject(repo)
    rewrite_pyproject(repo)
    data = _load(repo)
    ignore = data["tool"]["ruff"]["lint"]["ignore"]
    assert ignore == ["D203", "D213", "S603", "S607"]


def _write_pyproject_with_requires(
    tmp_path: Path, requires_python: str | None, package: str = "pkg"
) -> Path:
    requires_line = ""
    if requires_python:
        requires_line = f'requires-python = "{requires_python}"\n'
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{package}"\nversion = "0.1.0"\n{requires_line}'
    )
    pkg = tmp_path / package
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    return tmp_path


def test_target_version_derived_from_requires_python_floor(tmp_path: Path) -> None:
    repo = _write_pyproject_with_requires(tmp_path, ">=3.12")
    rewrite_pyproject(repo)
    data = _load(repo)
    assert data["tool"]["ruff"]["target-version"] == "py312"


def test_target_version_falls_back_without_requires_python(tmp_path: Path) -> None:
    repo = _write_pyproject_with_requires(tmp_path, None)
    rewrite_pyproject(repo)
    data = _load(repo)
    assert data["tool"]["ruff"]["target-version"] == "py311"


def test_target_version_uses_actual_floor_below_fleet_standard(tmp_path: Path) -> None:
    repo = _write_pyproject_with_requires(tmp_path, ">=3.10")
    rewrite_pyproject(repo)
    data = _load(repo)
    assert data["tool"]["ruff"]["target-version"] == "py310"
