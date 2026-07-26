"""Tests for the pydoclint docstring-quality check."""

import subprocess
from pathlib import Path

from preen.checks.base import Impact, Severity
from preen.checks.pydoclint import PydoclintCheck


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_pydoclint_not_installed(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert issue.impact == Impact.CRITICAL
    assert "not installed" in issue.description


def test_no_issues_passes(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_missing_docstring_in_cli_is_error_and_critical(
    tmp_path: Path, monkeypatch
) -> None:
    cli_file = tmp_path / "cli.py"
    output = f"{cli_file}:10: DOC101 Missing docstring in public method\n"

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=1, stdout=output)

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert issue.impact == Impact.CRITICAL
    assert issue.file == Path("cli.py")
    assert issue.line == 10
    assert "DOC101" in issue.description


def test_formatting_issue_in_regular_file_is_warning_and_important(
    tmp_path: Path, monkeypatch
) -> None:
    other = tmp_path / "helpers.py"
    output = f"{other}:5: DOC101 Missing docstring in public function\n"

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=1, stdout=output)

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    issue = result.issues[0]
    assert issue.severity == Severity.WARNING
    assert issue.impact == Impact.IMPORTANT


def test_uses_repo_pyproject_config_when_present(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.pydoclint]\nstyle = "google"\n')
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    PydoclintCheck(tmp_path).run()
    run_cmd = calls[-1]
    assert "--config" in run_cmd
    assert "pyproject.toml" in run_cmd


def test_no_pyproject_falls_back_to_google_style(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    PydoclintCheck(tmp_path).run()
    assert "--style=google" in calls[-1]


def test_stderr_error_with_no_stdout_reported(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=1, stdout="", stderr="internal error")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert "internal error" in result.issues[0].description
    assert result.issues[0].impact == Impact.INFORMATIONAL


def test_can_fix_false(tmp_path: Path) -> None:
    assert PydoclintCheck(tmp_path).can_fix() is False
