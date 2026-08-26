"""Tests for the hardcoded-version-string check."""

# Fixture versions are deliberately implausible. preen's own release bumped
# project.version to 0.5.0, which these fixtures happened to use, and the
# version check -- correctly, on the evidence available to it -- reported five
# hardcoded copies of the project version in its own test suite.

from pathlib import Path

from preen.checks.version import VersionCheck


def test_no_pyproject_no_version_files_passes(tmp_path: Path) -> None:
    result = VersionCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_literal_dunder_version_flagged(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n')
    result = VersionCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert "Literal __version__" in issue.description
    assert issue.line == 1
    assert issue.file == Path("src/mypkg/__init__.py")


def test_dunder_version_with_importlib_metadata_is_exempt(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        'from importlib.metadata import version\n__version__ = version("mypkg")\n'
    )
    result = VersionCheck(tmp_path).run()
    assert result.passed


def test_static_pyproject_version_copy_flagged(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "9.9.9"\n'
    )
    (tmp_path / "setup.cfg.py").write_text('version = "9.9.9"\n')
    result = VersionCheck(tmp_path).run()
    assert not result.passed
    assert any("9.9.9" in issue.description for issue in result.issues)


def test_static_version_in_pyproject_itself_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "9.9.9"\n'
    )
    result = VersionCheck(tmp_path).run()
    assert result.passed


def test_dynamic_version_pyproject_skips_copy_check(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\ndynamic = ["version"]\n'
    )
    (tmp_path / "workflow.yml").write_text('version = "1.0.0"\n')
    result = VersionCheck(tmp_path).run()
    assert result.passed


def test_commented_version_copy_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "9.9.9"\n'
    )
    (tmp_path / "notes.py").write_text('# version = "9.9.9"\n')
    result = VersionCheck(tmp_path).run()
    assert result.passed


def test_malformed_pyproject_treated_as_no_static_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not valid toml [[[")
    result = VersionCheck(tmp_path).run()
    assert result.passed


def test_can_fix_false(tmp_path: Path) -> None:
    assert VersionCheck(tmp_path).can_fix() is False
