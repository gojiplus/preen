"""Tests for the ruff lint/format check: subprocess boundary + a live integration."""

import subprocess
from pathlib import Path

from preen.checks.base import Impact, Severity
from preen.checks.ruff import RuffCheck


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_ruff_not_installed(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr("preen.checks.ruff.subprocess.run", fake_run)
    result = RuffCheck(tmp_path).run()
    assert not result.passed
    assert result.issues[0].severity == Severity.ERROR
    assert "not installed" in result.issues[0].description


def test_clean_project_passes(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="ruff 0.15\n")
        if "check" in cmd:
            return _completed(cmd, returncode=0)
        if "format" in cmd:
            return _completed(cmd, returncode=0)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.ruff.subprocess.run", fake_run)
    result = RuffCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_lint_issues_with_fixable_diff(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="ruff 0.15\n")
        if cmd[1:3] == ["check", "--quiet"] and "--fix" not in cmd:
            return _completed(
                cmd, returncode=1, stdout="f.py:1:1: F401\nf.py:2:1: E501\n"
            )
        if "--fix" in cmd:
            return _completed(cmd, returncode=0, stdout="--- a/f.py\n+++ b/f.py\n")
        if "format" in cmd and "--check" in cmd:
            return _completed(cmd, returncode=0)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.ruff.subprocess.run", fake_run)
    result = RuffCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.WARNING
    assert issue.impact == Impact.IMPORTANT
    assert "2 problems" in issue.description
    assert issue.proposed_fix is not None
    assert "a/f.py" in issue.proposed_fix.diff


def test_lint_issues_with_no_fix_available(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="ruff 0.15\n")
        if cmd[1:3] == ["check", "--quiet"] and "--fix" not in cmd:
            return _completed(cmd, returncode=1, stdout="f.py:1:1: F401\n")
        if "--fix" in cmd:
            return _completed(cmd, returncode=0, stdout="")
        if "format" in cmd and "--check" in cmd:
            return _completed(cmd, returncode=0)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.ruff.subprocess.run", fake_run)
    result = RuffCheck(tmp_path).run()
    assert result.issues[0].proposed_fix is None


def test_format_issues_flagged(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="ruff 0.15\n")
        if cmd[1:3] == ["check", "--quiet"]:
            return _completed(cmd, returncode=0)
        if "format" in cmd and "--check" in cmd:
            return _completed(cmd, returncode=1)
        if "format" in cmd and "--diff" in cmd:
            return _completed(cmd, returncode=1, stdout="--- diff ---\n")
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.ruff.subprocess.run", fake_run)
    result = RuffCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert "formatting issues" in issue.description.lower()
    assert issue.proposed_fix is not None
    assert issue.proposed_fix.diff == "--- diff ---\n"


def test_uv_lock_uses_uv_run_ruff(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "uv.lock").write_text("")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed(cmd, returncode=0)

    monkeypatch.setattr("preen.checks.ruff.subprocess.run", fake_run)
    RuffCheck(tmp_path).run()
    assert calls[0][:3] == ["uv", "run", "ruff"]


def test_can_fix_true(tmp_path: Path) -> None:
    assert RuffCheck(tmp_path).can_fix() is True


def test_live_ruff_on_clean_and_dirty_fixture(tmp_path: Path) -> None:
    """Real ruff binary against a tmp fixture -- no network, fast."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fx"\n')
    (tmp_path / "clean.py").write_text('"""Doc."""\n\nCONST = 1\n')
    result = RuffCheck(tmp_path).run()
    assert result.passed

    (tmp_path / "dirty.py").write_text("import os\nx=1\n")
    result = RuffCheck(tmp_path).run()
    assert not result.passed
    assert any("Linting issues" in i.description for i in result.issues)
