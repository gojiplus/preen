"""Tests for the ci-matrix and citation checks, and answer mining."""

from pathlib import Path

from preen.adopt import detect_package_name, mine_answers
from preen.checks.ci_matrix import CIMatrixCheck
from preen.checks.citation import CitationCheck

CANON_SHIM = """\
name: CI
on: [push]
jobs:
  ci:
    uses: gojiplus/py-canon/.github/workflows/reusable-ci.yml@v1
    with:
      wheel-import: mypkg
"""

CUSTOM_MATRIX = """\
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["{versions}"]
    steps: []
"""


def _write_ci(repo: Path, content: str) -> None:
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(content)


def _write_pyproject(repo: Path, floor: str = "3.11") -> None:
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "mypkg"\nrequires-python = ">={floor}"\n'
    )


def test_ci_matrix_shim_passes(tmp_path: Path) -> None:
    _write_pyproject(tmp_path)
    _write_ci(tmp_path, CANON_SHIM)
    result = CIMatrixCheck(tmp_path).run()
    assert result.passed


def test_ci_matrix_covering_floor_passes(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, floor="3.11")
    _write_ci(tmp_path, CUSTOM_MATRIX.format(versions='3.11", "3.14'))
    result = CIMatrixCheck(tmp_path).run()
    assert result.passed


def test_ci_matrix_missing_floor_fails(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, floor="3.11")
    _write_ci(tmp_path, CUSTOM_MATRIX.format(versions="3.14"))
    result = CIMatrixCheck(tmp_path).run()
    assert not result.passed
    assert any("3.11" in issue.description for issue in result.issues)


def test_ci_matrix_missing_workflow(tmp_path: Path) -> None:
    _write_pyproject(tmp_path)
    result = CIMatrixCheck(tmp_path).run()
    assert not result.passed


def test_citation_missing(tmp_path: Path) -> None:
    result = CitationCheck(tmp_path).run()
    assert not result.passed


def test_citation_valid(tmp_path: Path) -> None:
    (tmp_path / "CITATION.cff").write_text(
        'cff-version: 1.2.0\ntitle: "x"\nauthors:\n  - family-names: "Y"\n'
    )
    result = CitationCheck(tmp_path).run()
    assert result.passed


def test_citation_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "CITATION.cff").write_text("title: [unclosed\n")
    result = CitationCheck(tmp_path).run()
    assert not result.passed


def test_citation_missing_keys(tmp_path: Path) -> None:
    (tmp_path / "CITATION.cff").write_text("title: only-a-title\n")
    result = CitationCheck(tmp_path).run()
    assert not result.passed


def test_mine_answers(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "my-pkg"\n'
        'description = "Does a thing"\n'
        'authors = [{ name = "Alice", email = "alice@example.com" }]\n'
        "\n"
        "[project.scripts]\n"
        'my-pkg = "my_pkg.cli:main"\n'
    )
    pkg = tmp_path / "src" / "my_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")

    answers = mine_answers(tmp_path)
    assert answers["project_name"] == "my-pkg"
    assert answers["package_name"] == "my_pkg"
    assert answers["description"] == "Does a thing"
    assert answers["author_name"] == "Alice"
    assert answers["author_email"] == "alice@example.com"
    assert answers["needs_cli"] is True
    assert answers["coverage_floor"] == 0
    assert answers["default_branch"]


def test_detect_package_name_single_src_package(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "othername"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    assert detect_package_name(tmp_path, "my-pkg") == "othername"
