"""Tests for adopt's tomlkit pyproject surgery."""

import subprocess
import tomllib
from pathlib import Path

import pytest

from preen.adopt import CANON_TOOL_TOML, rewrite_pyproject

# Derived rather than duplicated, so extending the standard's rule set does
# not mean restating it in every assertion here.
CANON = tomllib.loads(CANON_TOOL_TOML)["tool"]
CANON_IGNORE = CANON["ruff"]["lint"]["ignore"]
CANON_TEST_IGNORES = CANON["ruff"]["lint"]["per-file-ignores"]["tests/**"]

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
    changes, _ = rewrite_pyproject(legacy_repo)
    data = _load(legacy_repo)
    ruff = data["tool"]["ruff"]
    assert ruff["line-length"] == 88
    assert "D" in ruff["lint"]["select"]
    assert ruff["lint"]["pydocstyle"]["convention"] == "google"
    assert ruff["lint"]["per-file-ignores"]["tests/**"] == CANON_TEST_IGNORES
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
    assert data["build-system"]["requires"] == ["uv_build>=0.12.5,<0.13"]
    assert data["build-system"]["build-backend"] == "uv_build"
    assert data["project"]["version"] == "1.2.3"
    assert "dynamic" not in data["project"]
    # Flat layout detected.
    assert data["tool"]["uv"]["build-backend"] == {
        "module-name": "legacy_pkg",
        "module-root": "",
    }


def test_release_migration_removes_stale_backend_path(legacy_repo: Path) -> None:
    pyproject = legacy_repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            'build-backend = "setuptools.build_meta"',
            'build-backend = "setuptools.build_meta"\nbackend-path = ["backend"]',
        )
    )

    rewrite_pyproject(legacy_repo, release_migration=True)

    assert "backend-path" not in _load(legacy_repo)["build-system"]


def test_release_migration_replaces_malformed_build_system(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        'build-system = "setuptools"\n\n[project]\nname = "pkg"\nversion = "0.1.0"\n'
    )
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")

    rewrite_pyproject(tmp_path, release_migration=True)

    data = _load(tmp_path)
    assert data["build-system"] == {
        "requires": ["uv_build>=0.12.5,<0.13"],
        "build-backend": "uv_build",
    }


def test_release_migration_src_layout(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "srcpkg"\nversion = "0.1.0"\n'
    )
    pkg = tmp_path / "src" / "srcpkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    rewrite_pyproject(tmp_path, release_migration=True)
    data = _load(tmp_path)
    assert data["tool"]["uv"]["build-backend"] == {"module-name": "srcpkg"}


def test_release_migration_recovers_dynamic_version_from_tag(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "tagged"\ndynamic = ["version"]\n'
    )
    package = tmp_path / "src" / "tagged"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "init"],
        ["git", "tag", "v2.4.0"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True)

    rewrite_pyproject(tmp_path, release_migration=True)

    data = _load(tmp_path)
    assert data["project"]["version"] == "2.4.0"
    assert "dynamic" not in data["project"]


def test_release_migration_refuses_to_invent_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "untagged"\ndynamic = ["version"]\n'
    )
    package = tmp_path / "src" / "untagged"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")

    with pytest.raises(ValueError, match=r"needs project\.version"):
        rewrite_pyproject(tmp_path, release_migration=True)


def test_release_migration_does_not_use_parent_repository_tag(tmp_path: Path) -> None:
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(command, cwd=tmp_path, check=True)
    (tmp_path / "tracked").write_text("parent repository\n")
    subprocess.run(["git", "add", "tracked"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "parent"], cwd=tmp_path, check=True)
    subprocess.run(["git", "tag", "v9.9.9"], cwd=tmp_path, check=True)

    package_repo = tmp_path / "package"
    package_repo.mkdir()
    (package_repo / "pyproject.toml").write_text(
        '[project]\nname = "untagged"\ndynamic = ["version"]\n'
    )
    package = package_repo / "src" / "untagged"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")

    with pytest.raises(ValueError, match=r"needs project\.version"):
        rewrite_pyproject(package_repo, release_migration=True)


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
    _, preserved = rewrite_pyproject(repo)
    data = _load(repo)
    ignore = data["tool"]["ruff"]["lint"]["ignore"]
    # Canon codes first (in canon order), then extra repo codes, sorted.
    assert ignore == [*CANON_IGNORE, "S603", "S607"]
    assert any("S603" in p and "S607" in p for p in preserved)


def test_ruff_legacy_top_level_ignore_preserved(tmp_path: Path) -> None:
    repo = _write_pyproject(
        tmp_path,
        '[tool.ruff]\nline-length = 100\nignore = ["S603"]\n',
    )
    rewrite_pyproject(repo)
    data = _load(repo)
    assert data["tool"]["ruff"]["lint"]["ignore"] == [*CANON_IGNORE, "S603"]
    # Hoisted out of the deprecated top-level location, not left in both.
    assert "ignore" not in data["tool"]["ruff"]


def test_ruff_no_existing_section_ignore_is_canon_only(tmp_path: Path) -> None:
    repo = _write_pyproject(tmp_path, "")
    rewrite_pyproject(repo)
    data = _load(repo)
    assert data["tool"]["ruff"]["lint"]["ignore"] == CANON_IGNORE


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
    assert ignore == [*CANON_IGNORE, "S603", "S607"]


def test_repo_specific_ruff_settings_survive(tmp_path: Path) -> None:
    """Settings canon says nothing about must not be dropped (issue #13)."""
    repo = _write_pyproject(
        tmp_path,
        "[tool.ruff]\n"
        'exclude = ["notebooks", "scripts"]\n\n'
        "[tool.ruff.lint.flake8-bugbear]\n"
        'extend-immutable-calls = ["typer.Option"]\n\n'
        "[tool.ruff.lint.per-file-ignores]\n"
        '"scripts/**" = ["T201"]\n'
        '"tests/**" = ["ANN"]\n\n'
        "[tool.pyright]\nreportMissingImports = false\n",
    )
    _, preserved = rewrite_pyproject(repo)
    ruff = _load(repo)["tool"]["ruff"]

    assert ruff["exclude"] == ["notebooks", "scripts"]
    assert ruff["lint"]["flake8-bugbear"]["extend-immutable-calls"] == ["typer.Option"]
    assert ruff["lint"]["per-file-ignores"]["scripts/**"] == ["T201"]
    # Repo codes union onto canon's for a pattern canon also defines.
    assert ruff["lint"]["per-file-ignores"]["tests/**"] == [*CANON_TEST_IGNORES, "ANN"]
    assert _load(repo)["tool"]["pyright"]["reportMissingImports"] is False
    # Canon still wins where it has an opinion.
    assert ruff["line-length"] == 88
    assert _load(repo)["tool"]["pyright"]["typeCheckingMode"] == "standard"

    assert any("exclude" in p for p in preserved)
    assert any("flake8-bugbear" in p for p in preserved)


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


@pytest.mark.parametrize(
    ("requires_python", "expected"),
    [
        (">=3.12", "py312"),
        ("~=3.12", "py312"),
        ("==3.12.*", "py312"),
        (">3.11", "py311"),
        (">=3.11,<4", "py311"),
    ],
)
def test_target_version_handles_every_floor_specifier(
    tmp_path: Path, requires_python: str, expected: str
) -> None:
    """~= and == pin a floor just as >= does (issue #15)."""
    repo = _write_pyproject_with_requires(tmp_path, requires_python)
    rewrite_pyproject(repo)
    assert _load(repo)["tool"]["ruff"]["target-version"] == expected


def test_dev_group_does_not_duplicate_included_group(tmp_path: Path) -> None:
    """A requirement reached via include-group is already present (issue #18)."""
    repo = _write_pyproject(
        tmp_path,
        "[dependency-groups]\n"
        'dev = [{ include-group = "test" }]\n'
        'test = ["pytest>=9"]\n',
    )
    rewrite_pyproject(repo)
    dev = _load(repo)["dependency-groups"]["dev"]
    assert not any(isinstance(e, str) and e.startswith("pytest") for e in dev)


def test_dev_group_include_cycle_terminates(tmp_path: Path) -> None:
    repo = _write_pyproject(
        tmp_path,
        "[dependency-groups]\n"
        'dev = [{ include-group = "a" }]\n'
        'a = [{ include-group = "dev" }, "pytest>=9"]\n',
    )
    rewrite_pyproject(repo)
    dev = _load(repo)["dependency-groups"]["dev"]
    assert not any(isinstance(e, str) and e.startswith("pytest") for e in dev)


def test_a_test_group_is_created_for_the_reusable_ci(tmp_path: Path) -> None:
    """The wheel job installs it by name, and exits 2 when it is absent.

    `uv pip install dist/*.whl --group test` against a clean environment is
    what py-canon's reusable CI runs, so a flat `dev` group sent every
    release-migration adoption red on its first push (issue #54).
    """
    repo = _write_pyproject(tmp_path, '[dependency-groups]\ndev = ["ruff>=0.14"]\n')
    rewrite_pyproject(repo)

    groups = _load(repo)["dependency-groups"]
    assert "pytest>=8" in groups["test"]
    assert "pytest-cov>=6" in groups["test"]
    assert {"include-group": "test"} in groups["dev"]


def test_pytest_is_pinned_once_not_twice(tmp_path: Path) -> None:
    """A direct pin in `dev` is superseded by the include, not kept beside it."""
    repo = _write_pyproject(
        tmp_path, '[dependency-groups]\ndev = ["pytest>=7", "pytest-cov>=5"]\n'
    )
    rewrite_pyproject(repo)

    groups = _load(repo)["dependency-groups"]
    assert not [
        entry
        for entry in groups["dev"]
        if isinstance(entry, str) and entry.startswith("pytest")
    ]
    assert groups["test"] == ["pytest>=8", "pytest-cov>=6"]


def test_an_existing_test_group_is_left_pinned_as_it_is(tmp_path: Path) -> None:
    """adopt adds what is missing; it does not re-pin what a repo chose."""
    repo = _write_pyproject(
        tmp_path,
        "[dependency-groups]\n"
        'dev = [{ include-group = "test" }]\n'
        'test = ["pytest>=9.1"]\n',
    )
    rewrite_pyproject(repo)

    groups = _load(repo)["dependency-groups"]
    assert "pytest>=9.1" in groups["test"]
    assert "pytest>=8" not in groups["test"]
    assert "pytest-cov>=6" in groups["test"]
    assert groups["dev"].count({"include-group": "test"}) == 1


def test_the_dev_group_carries_pre_commit(tmp_path: Path) -> None:
    """The precommit check expects a config; the hook runner has to install."""
    repo = _write_pyproject(tmp_path, "[dependency-groups]\ndev = []\n")
    rewrite_pyproject(repo)

    assert "pre-commit>=4" in _load(repo)["dependency-groups"]["dev"]
