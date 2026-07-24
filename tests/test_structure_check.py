"""Tests for the project structure check."""

import subprocess
from pathlib import Path

from preen.checks.base import Severity
from preen.checks.structure import StructureCheck


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


def _git_commit_all(repo: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def test_clean_src_layout_passes(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mypkg").mkdir(parents=True)
    (tmp_path / "src" / "mypkg" / "__init__.py").write_text("")
    result = StructureCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_tests_inside_package_flagged(tmp_path: Path) -> None:
    pkg_tests = tmp_path / "src" / "mypkg" / "tests"
    pkg_tests.mkdir(parents=True)
    (pkg_tests / "test_x.py").write_text("")
    result = StructureCheck(tmp_path).run()
    assert not result.passed
    assert any("tests/" in issue.description for issue in result.issues)
    issue = result.issues[0]
    assert issue.proposed_fix is not None
    assert issue.severity == Severity.WARNING


def test_examples_inside_package_flagged(tmp_path: Path) -> None:
    pkg_examples = tmp_path / "src" / "mypkg" / "examples"
    pkg_examples.mkdir(parents=True)
    (pkg_examples / "demo.py").write_text("")
    result = StructureCheck(tmp_path).run()
    assert not result.passed
    assert any("examples/" in issue.description for issue in result.issues)


def test_flat_layout_is_informational(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "mypkg"\n')
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("")
    result = StructureCheck(tmp_path).run()
    # Flat layout is informational, not blocking; `passed` still flips
    # False because informational issues are still `issues`.
    assert not result.passed
    assert result.issues[0].severity == Severity.INFO


def test_no_pycache_or_pyc_tracked_passes(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mypkg").mkdir(parents=True)
    (tmp_path / "src" / "mypkg" / "__init__.py").write_text("")
    _git_commit_all(tmp_path)
    result = StructureCheck(tmp_path).run()
    assert result.passed


def test_tracked_pycache_flagged(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mypkg").mkdir(parents=True)
    (tmp_path / "src" / "mypkg" / "__init__.py").write_text("")
    pycache = tmp_path / "src" / "mypkg" / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.cpython-312.pyc").write_text("")
    _git_commit_all(tmp_path)
    result = StructureCheck(tmp_path).run()
    assert not result.passed
    assert any("__pycache__" in issue.description for issue in result.issues)


def test_tracked_pyc_file_flagged(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mypkg").mkdir(parents=True)
    (tmp_path / "src" / "mypkg" / "__init__.py").write_text("")
    (tmp_path / "src" / "mypkg" / "stale.pyc").write_text("")
    _git_commit_all(tmp_path)
    result = StructureCheck(tmp_path).run()
    assert not result.passed
    assert any(".pyc files" in issue.description for issue in result.issues)


def test_gitignored_pycache_not_flagged(tmp_path: Path) -> None:
    """Untracked (git-ignored) __pycache__ dirs are not the antipattern --

    only committed ones are.
    """
    _git_init(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mypkg").mkdir(parents=True)
    (tmp_path / "src" / "mypkg" / "__init__.py").write_text("")
    _git_commit_all(tmp_path)
    pycache = tmp_path / "src" / "mypkg" / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.cpython-312.pyc").write_text("")
    result = StructureCheck(tmp_path).run()
    assert result.passed


def test_can_fix_true(tmp_path: Path) -> None:
    assert StructureCheck(tmp_path).can_fix() is True


def test_fix_moves_tests_to_root(tmp_path: Path) -> None:
    pkg_tests = tmp_path / "src" / "mypkg" / "tests"
    pkg_tests.mkdir(parents=True)
    (pkg_tests / "test_x.py").write_text("x = 1\n")
    result = StructureCheck(tmp_path).run()
    issue = result.issues[0]
    issue.proposed_fix.apply()
    assert (tmp_path / "tests" / "test_x.py").exists()
    assert not pkg_tests.exists()


def test_fix_updates_gitignore(tmp_path: Path) -> None:
    _git_init(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "mypkg").mkdir(parents=True)
    (tmp_path / "src" / "mypkg" / "__init__.py").write_text("")
    pycache = tmp_path / "src" / "mypkg" / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.cpython-312.pyc").write_text("")
    _git_commit_all(tmp_path)
    result = StructureCheck(tmp_path).run()
    pycache_issue = next(i for i in result.issues if "__pycache__" in i.description)
    pycache_issue.proposed_fix.apply()
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "__pycache__" in gitignore
