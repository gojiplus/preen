"""Tests for the check runner: skip/only filtering and result aggregation."""

from pathlib import Path

import pytest

from preen.checks.base import Check, CheckResult, Issue, Severity
from preen.checks.runner import run_checks


class _PassingCheck(Check):
    """A check that always passes."""

    @property
    def name(self) -> str:
        return "passing"

    def run(self) -> CheckResult:
        return CheckResult(check=self.name, passed=True, issues=[])


class _FailingCheck(Check):
    """A check that always reports one issue."""

    @property
    def name(self) -> str:
        return "failing"

    def run(self) -> CheckResult:
        issue = Issue(check=self.name, severity=Severity.ERROR, description="broken")
        return CheckResult(check=self.name, passed=False, issues=[issue])


class _OtherCheck(Check):
    """A second passing check, distinct name, for skip/only filtering."""

    @property
    def name(self) -> str:
        return "other"

    def run(self) -> CheckResult:
        return CheckResult(check=self.name, passed=True, issues=[])


def test_runs_all_checks_by_default(tmp_path: Path) -> None:
    results = run_checks(tmp_path, [_PassingCheck, _FailingCheck, _OtherCheck])
    assert set(results) == {"passing", "failing", "other"}
    assert results["passing"].passed
    assert not results["failing"].passed
    assert results["failing"].issues[0].description == "broken"


def test_skip_excludes_named_checks(tmp_path: Path) -> None:
    results = run_checks(
        tmp_path, [_PassingCheck, _FailingCheck, _OtherCheck], skip=["failing"]
    )
    assert set(results) == {"passing", "other"}


def test_only_restricts_to_named_checks(tmp_path: Path) -> None:
    results = run_checks(
        tmp_path, [_PassingCheck, _FailingCheck, _OtherCheck], only=["other"]
    )
    assert set(results) == {"other"}


def test_only_and_skip_combine(tmp_path: Path) -> None:
    """`only` narrows the set first; `skip` still applies within it."""
    results = run_checks(
        tmp_path,
        [_PassingCheck, _FailingCheck, _OtherCheck],
        only=["passing", "other"],
        skip=["other"],
    )
    assert set(results) == {"passing"}


def test_duration_recorded(tmp_path: Path) -> None:
    results = run_checks(tmp_path, [_PassingCheck])
    assert results["passing"].duration >= 0.0


def test_empty_check_list_returns_empty_dict(tmp_path: Path) -> None:
    assert run_checks(tmp_path, []) == {}


class _RaisingCheck(Check):
    """A check whose run() raises. The runner has no try/except around

    check.run(), so the current contract is that a raising check's
    exception propagates to the caller rather than being captured into a
    CheckResult.
    """

    @property
    def name(self) -> str:
        return "raising"

    def run(self) -> CheckResult:
        raise RuntimeError("check blew up")


def test_raising_check_propagates(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="check blew up"):
        run_checks(tmp_path, [_PassingCheck, _RaisingCheck])
