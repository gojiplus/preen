"""Tests for the pyright static type-checking check."""

import json
import subprocess
from pathlib import Path

from preen.checks.base import Impact, Severity
from preen.checks.pyright import PyrightCheck


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_pyright_not_installed(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr("preen.checks.pyright.subprocess.run", fake_run)
    result = PyrightCheck(tmp_path).run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert issue.impact == Impact.CRITICAL
    assert "not installed" in issue.description


def test_no_errors_passes(tmp_path: Path, monkeypatch) -> None:
    report = json.dumps({"generalDiagnostics": []})

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pyright 1.1\n")
        return _completed(cmd, returncode=0, stdout=report)

    monkeypatch.setattr("preen.checks.pyright.subprocess.run", fake_run)
    result = PyrightCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_error_diagnostic_parsed(tmp_path: Path, monkeypatch) -> None:
    report = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(tmp_path / "mod.py"),
                    "severity": "error",
                    "message": "Type mismatch",
                    "rule": "reportGeneralTypeIssues",
                    "range": {"start": {"line": 4, "character": 0}},
                }
            ]
        }
    )

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pyright 1.1\n")
        return _completed(cmd, returncode=1, stdout=report)

    monkeypatch.setattr("preen.checks.pyright.subprocess.run", fake_run)
    result = PyrightCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert issue.impact == Impact.CRITICAL
    assert issue.file == Path("mod.py")
    assert issue.line == 5  # 0-based -> 1-based
    assert "reportGeneralTypeIssues" in issue.description
    assert "Type mismatch" in issue.description


def test_warning_diagnostic_is_important(tmp_path: Path, monkeypatch) -> None:
    report = json.dumps(
        {
            "generalDiagnostics": [
                {
                    "file": str(tmp_path / "mod.py"),
                    "severity": "warning",
                    "message": "Unused import",
                    "rule": "reportUnusedImport",
                }
            ]
        }
    )

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pyright 1.1\n")
        return _completed(cmd, returncode=1, stdout=report)

    monkeypatch.setattr("preen.checks.pyright.subprocess.run", fake_run)
    result = PyrightCheck(tmp_path).run()
    issue = result.issues[0]
    assert issue.severity == Severity.WARNING
    assert issue.impact == Impact.IMPORTANT
    assert issue.line is None


def test_invalid_json_output_reports_parse_failure(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pyright 1.1\n")
        return _completed(cmd, returncode=0, stdout="not json{{")

    monkeypatch.setattr("preen.checks.pyright.subprocess.run", fake_run)
    result = PyrightCheck(tmp_path).run()
    assert not result.passed
    assert "Failed to parse pyright JSON" in result.issues[0].description


def test_fatal_error_reported(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pyright 1.1\n")
        return _completed(cmd, returncode=2, stdout="", stderr="config error")

    monkeypatch.setattr("preen.checks.pyright.subprocess.run", fake_run)
    result = PyrightCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert "config error" in result.issues[0].description


def test_uv_lock_uses_uv_run(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "uv.lock").write_text("")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed(cmd, returncode=0, stdout='{"generalDiagnostics": []}')

    monkeypatch.setattr("preen.checks.pyright.subprocess.run", fake_run)
    PyrightCheck(tmp_path).run()
    assert calls[0][:3] == ["uv", "run", "pyright"]


def test_can_fix_false(tmp_path: Path) -> None:
    assert PyrightCheck(tmp_path).can_fix() is False
