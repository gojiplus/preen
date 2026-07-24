"""Tests for the deptry-backed dependency check."""

import subprocess
from pathlib import Path

from preen.checks.base import Severity
from preen.checks.deps import DepsCheck


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_deptry_not_installed(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr("preen.checks.deps.subprocess.run", fake_run)
    result = DepsCheck(tmp_path).run()
    assert not result.passed
    assert result.issues[0].severity == Severity.ERROR
    assert "not installed" in result.issues[0].description


def test_clean_dependencies_pass(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="deptry 0.20\n")
        return _completed(cmd, returncode=0, stdout="{}")

    monkeypatch.setattr("preen.checks.deps.subprocess.run", fake_run)
    result = DepsCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_missing_and_unused_reported(tmp_path: Path, monkeypatch) -> None:
    import json

    payload = json.dumps({"missing": ["requests"], "unused": ["httpx"]})

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="deptry 0.20\n")
        return _completed(cmd, returncode=1, stdout=payload)

    monkeypatch.setattr("preen.checks.deps.subprocess.run", fake_run)
    result = DepsCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 2
    descriptions = " ".join(i.description for i in result.issues)
    assert "Missing dependencies: requests" in descriptions
    assert "Unused dependencies: httpx" in descriptions
    missing_issue = next(i for i in result.issues if "Missing" in i.description)
    assert missing_issue.severity == Severity.ERROR
    unused_issue = next(i for i in result.issues if "Unused" in i.description)
    assert unused_issue.severity == Severity.WARNING


def test_malformed_json_falls_back_to_stderr(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="deptry 0.20\n")
        return _completed(cmd, returncode=1, stdout="not json", stderr="deptry crashed")

    monkeypatch.setattr("preen.checks.deps.subprocess.run", fake_run)
    result = DepsCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert "deptry crashed" in result.issues[0].description


def test_can_fix_false(tmp_path: Path) -> None:
    assert DepsCheck(tmp_path).can_fix() is False
