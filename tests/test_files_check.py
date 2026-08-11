"""Tests for the required-files check."""

from pathlib import Path

from preen.checks.base import Severity
from preen.checks.files import README_NAMES, RequiredFilesCheck


def test_readme_and_gitignore_present_passes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# hi\n")
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    result = RequiredFilesCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_missing_readme_flagged(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    result = RequiredFilesCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert "No README" in result.issues[0].description


def test_missing_gitignore_flagged(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# hi\n")
    result = RequiredFilesCheck(tmp_path).run()
    assert not result.passed
    assert "No .gitignore" in result.issues[0].description


def test_alternative_readme_spellings_accepted(tmp_path: Path) -> None:
    """Any of the accepted spellings counts, not just README.md."""
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    for name in README_NAMES:
        target = tmp_path / name
        target.write_text("hi\n")
        assert RequiredFilesCheck(tmp_path).run().passed, name
        target.unlink()


def test_gitignore_fix_writes_a_usable_file(tmp_path: Path) -> None:
    """The offered fix must actually resolve the issue it is attached to.

    A fix that leaves the check still failing is worse than none: it reports
    success and changes nothing.
    """
    (tmp_path / "README.md").write_text("# hi\n")
    issue = RequiredFilesCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    assert (tmp_path / ".gitignore").exists()
    assert "__pycache__" in (tmp_path / ".gitignore").read_text()
    assert RequiredFilesCheck(tmp_path).run().passed


def test_both_missing_reports_both(tmp_path: Path) -> None:
    result = RequiredFilesCheck(tmp_path).run()
    assert len(result.issues) == 2
    assert all(i.severity == Severity.WARNING for i in result.issues)
