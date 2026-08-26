"""Tests for the metadata check: requires-python cap and py.typed."""

from pathlib import Path

import pytest

from preen.checks.metadata import MetadataCheck


def _write_pyproject(
    repo: Path, requires_python: str | None, typed: str | None = None
) -> None:
    # A version, because these fixtures now go through validate-pyproject and
    # `[project]` without one is not a file any real repo ships.
    lines = ["[project]", 'name = "mypkg"', 'version = "0.1.0"']
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


def test_missing_pyproject_passes_silently(tmp_path):
    result = MetadataCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_current_uv_build_backend_clean(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ">=3.11")
    with (tmp_path / "pyproject.toml").open("a") as pyproject:
        pyproject.write(
            '\n[build-system]\nrequires = ["uv_build>=0.12.5,<0.13"]\n'
            'build-backend = "uv_build"\n'
        )
    result = MetadataCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


@pytest.mark.parametrize(
    ("requires", "backend"),
    [
        (["uv_build>=0.11.32,<0.12"], "uv_build"),
        (["hatchling"], "hatchling.build"),
        (["uv_build>=0.12.5,<0.13", "setuptools"], "uv_build"),
    ],
)
def test_nonstandard_build_backend_flagged(
    tmp_path: Path, requires: list[str], backend: str
) -> None:
    _write_pyproject(tmp_path, ">=3.11")
    requires_toml = ", ".join(f'"{requirement}"' for requirement in requires)
    with (tmp_path / "pyproject.toml").open("a") as pyproject:
        pyproject.write(
            f"\n[build-system]\nrequires = [{requires_toml}]\n"
            f'build-backend = "{backend}"\n'
        )
    result = MetadataCheck(tmp_path).run()
    assert not result.passed
    assert any("uv_build" in issue.description for issue in result.issues)


def test_stale_backend_path_flagged(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, ">=3.11")
    with (tmp_path / "pyproject.toml").open("a") as pyproject:
        pyproject.write(
            '\n[build-system]\nrequires = ["uv_build>=0.12.5,<0.13"]\n'
            'build-backend = "uv_build"\nbackend-path = ["backend"]\n'
        )

    result = MetadataCheck(tmp_path).run()

    assert not result.passed
    assert any("uv_build" in issue.description for issue in result.issues)


@pytest.mark.parametrize("build_system", ["[build-system]\n", 'build-system = "uv"\n'])
def test_malformed_build_system_flagged(tmp_path: Path, build_system: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'{build_system}\n[project]\nname = "mypkg"\nrequires-python = ">=3.11"\n'
    )
    result = MetadataCheck(tmp_path).run()
    assert not result.passed
    assert any("uv_build" in issue.description for issue in result.issues)


def test_pyproject_failing_its_schema_is_critical(tmp_path: Path) -> None:
    """Every other check reads this file by `.get()`.

    That cannot tell a key that is absent from one that is misspelled or the
    wrong type, so a schema pass names the difference before anything reasons
    about it (issue #17). Validated against PyPA's own schemas, which is what
    build backends and installers use.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "mypkg"\nversion = 1\n')

    result = MetadataCheck(tmp_path).run()

    assert not result.passed
    assert "fails its schema" in result.issues[0].description
    assert result.issues[0].is_blocking()


def test_schema_failure_does_not_hide_the_other_findings(tmp_path: Path) -> None:
    """One problem must not suppress the rest; the checks below are defensive."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = 1\nrequires-python = ">=3.11,<4"\n'
    )

    result = MetadataCheck(tmp_path).run()

    assert any("fails its schema" in i.description for i in result.issues)
    assert any("requires-python" in i.description for i in result.issues)


def test_invalid_toml_is_named_as_such(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("this is not = valid toml [[[\n")

    result = MetadataCheck(tmp_path).run()

    assert not result.passed
    assert "not valid TOML" in result.issues[0].description


@pytest.mark.parametrize(
    "requires",
    ['["uv_build>=0.12.5,<0.13"]', '["uv_build>=0.12.5,<0.13.0"]'],
)
def test_equivalent_spellings_of_the_build_requirement_pass(
    tmp_path: Path, requires: str
) -> None:
    """`<0.13` and `<0.13.0` admit precisely the same versions.

    Compared as strings, the second failed — so gojiplus/uijudge-bench, whose
    build backend is correct and current, was told to migrate it.
    """
    _write_pyproject(tmp_path, ">=3.11")
    with (tmp_path / "pyproject.toml").open("a") as pyproject:
        pyproject.write(
            f'\n[build-system]\nrequires = {requires}\nbuild-backend = "uv_build"\n'
        )

    result = MetadataCheck(tmp_path).run()

    assert not [i for i in result.issues if "build-system" in i.description]


@pytest.mark.parametrize(
    "requires",
    [
        '["uv_build>=0.12.4,<0.13"]',
        '["uv_build>=0.12.5"]',
        '["uv_build>=0.12.5,<0.13", "wheel"]',
        '["hatchling"]',
    ],
)
def test_a_genuinely_different_requirement_is_still_flagged(
    tmp_path: Path, requires: str
) -> None:
    """Equivalence, not laxity: a different floor or an extra pin still fails."""
    _write_pyproject(tmp_path, ">=3.11")
    with (tmp_path / "pyproject.toml").open("a") as pyproject:
        pyproject.write(
            f'\n[build-system]\nrequires = {requires}\nbuild-backend = "uv_build"\n'
        )

    result = MetadataCheck(tmp_path).run()

    assert [i for i in result.issues if "build-system" in i.description]
