"""Tests for the pytest-runner check (test-dir/tool detection + result parsing)."""

import subprocess
from pathlib import Path

from preen.checks.base import Severity
from preen.checks.tests import TestsCheck as PytestCheck


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_uv_lock_present_uses_uv_run(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "uv.lock").write_text("")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pytest 8.0\n")
        return _completed(cmd, returncode=0, stdout="1 passed\n")

    monkeypatch.setattr("preen.checks.tests.subprocess.run", fake_run)
    result = PytestCheck(tmp_path).run()
    assert result.passed
    assert calls[0][:3] == ["uv", "run", "pytest"]


def test_no_uv_lock_uses_python3_module(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pytest 8.0\n")
        return _completed(cmd, returncode=0, stdout="1 passed\n")

    monkeypatch.setattr("preen.checks.tests.subprocess.run", fake_run)
    result = PytestCheck(tmp_path).run()
    assert result.passed
    assert calls[0][:3] == ["python3", "-m", "pytest"]


def test_pytest_not_installed(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("preen.checks.tests.subprocess.run", fake_run)
    result = PytestCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.ERROR
    assert "not installed" in result.issues[0].description


def test_test_failures_reported(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pytest 8.0\n")
        return _completed(
            cmd,
            returncode=1,
            stdout="F.\n===\n2 failed, 3 passed in 0.10s\n",
        )

    monkeypatch.setattr("preen.checks.tests.subprocess.run", fake_run)
    result = PytestCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.ERROR
    assert "2 failed, 3 passed" in result.issues[0].description


def test_failure_with_no_summary_line_falls_back(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pytest 8.0\n")
        return _completed(cmd, returncode=1, stdout="")

    monkeypatch.setattr("preen.checks.tests.subprocess.run", fake_run)
    result = PytestCheck(tmp_path).run()
    assert not result.passed
    assert "See test output for details" in result.issues[0].description


def test_can_fix_not_offered(tmp_path: Path) -> None:
    assert PytestCheck(tmp_path).can_fix() is False
