"""Tests for the `preen fix` dispatcher.

Covers check routing, interactive vs --auto/--batch modes, and the
unknown-check-name error path.
"""

import io

import pytest
import rich.prompt
import typer
from rich.console import Console

from preen.checks.base import Check, CheckResult, Fix, Issue, Severity
from preen.commands.fix import apply_fixes


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, no_color=True)


class _FixableCheck(Check):
    """A check with one fixable issue, for dispatcher tests."""

    applied = False

    @property
    def name(self) -> str:
        return "fixable"

    def run(self) -> CheckResult:
        def _apply():
            type(self).applied = True

        issue = Issue(
            check=self.name,
            severity=Severity.WARNING,
            description="something to fix",
            proposed_fix=Fix(description="fix it", diff="- old\n+ new\n", apply=_apply),
        )
        return CheckResult(check=self.name, passed=False, issues=[issue])


class _CleanCheck(Check):
    """A check with no issues at all."""

    @property
    def name(self) -> str:
        return "clean"

    def run(self) -> CheckResult:
        return CheckResult(check=self.name, passed=True, issues=[])


@pytest.fixture(autouse=True)
def _reset_applied():
    _FixableCheck.applied = False
    yield
    _FixableCheck.applied = False


def test_unknown_check_name_exits_and_lists_available(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("preen.commands.fix.ALL_CHECKS", [_FixableCheck, _CleanCheck])
    console = _console()
    with pytest.raises(typer.Exit):
        apply_fixes(tmp_path, check_name="nope", console=console)
    output = console.file.getvalue()
    assert "Unknown check: nope" in output
    assert "clean" in output
    assert "fixable" in output


def test_no_fixable_issues_reports_and_returns(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("preen.commands.fix.ALL_CHECKS", [_CleanCheck])
    console = _console()
    apply_fixes(tmp_path, console=console)
    assert "No fixable issues found" in console.file.getvalue()


def test_named_check_routes_to_only_that_check(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("preen.commands.fix.ALL_CHECKS", [_FixableCheck, _CleanCheck])
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    apply_fixes(tmp_path, check_name="fixable", auto=False, console=console)

    assert _FixableCheck.applied is True


def test_auto_mode_applies_without_prompting(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("preen.commands.fix.ALL_CHECKS", [_FixableCheck])

    def fail_confirm(*a, **k):
        raise AssertionError("Confirm.ask must not be called in --auto mode")

    monkeypatch.setattr(rich.prompt.Confirm, "ask", fail_confirm)
    console = _console()

    apply_fixes(tmp_path, auto=True, console=console)

    assert _FixableCheck.applied is True
    assert "1 issue(s) fixed" in console.file.getvalue()


def test_interactive_decline_skips_fix(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("preen.commands.fix.ALL_CHECKS", [_FixableCheck])
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: False)
    console = _console()

    apply_fixes(tmp_path, interactive=True, auto=False, console=console)

    assert _FixableCheck.applied is False
    output = console.file.getvalue()
    assert "Skipped" in output
    assert "1 issue(s) skipped" in output


def test_batch_mode_applies_without_prompting(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("preen.commands.fix.ALL_CHECKS", [_FixableCheck])

    def fail_confirm(*a, **k):
        raise AssertionError("Confirm.ask must not be called in batch mode")

    monkeypatch.setattr(rich.prompt.Confirm, "ask", fail_confirm)
    console = _console()

    apply_fixes(tmp_path, interactive=False, auto=False, console=console)

    assert _FixableCheck.applied is True


class _ConfirmOnlyCheck(Check):
    """A check whose fix must never be applied unattended."""

    applied = False

    @property
    def name(self) -> str:
        return "confirm-only"

    def run(self) -> CheckResult:
        def _apply():
            type(self).applied = True

        issue = Issue(
            check=self.name,
            severity=Severity.WARNING,
            description="rewrites content preen cannot judge",
            proposed_fix=Fix(
                description="risky",
                diff="- Denis Leary\n+ Denis Leery\n",
                apply=_apply,
                requires_confirmation=True,
            ),
        )
        return CheckResult(check=self.name, passed=False, issues=[issue])


def test_auto_defers_fixes_requiring_confirmation(tmp_path, monkeypatch) -> None:
    """--auto must not silently rewrite data fixtures (issue #19)."""
    _ConfirmOnlyCheck.applied = False
    monkeypatch.setattr("preen.commands.fix.ALL_CHECKS", [_ConfirmOnlyCheck])
    console = _console()
    apply_fixes(tmp_path, auto=True, console=console)

    assert _ConfirmOnlyCheck.applied is False
    output = console.file.getvalue()
    assert "Deferred" in output
    assert "1 issue(s) deferred for review" in output
    assert "0 issue(s) fixed" in output


def test_interactive_can_still_apply_confirmed_fix(tmp_path, monkeypatch) -> None:
    """Deferral is about unattended runs, not a blanket refusal."""
    _ConfirmOnlyCheck.applied = False
    monkeypatch.setattr("preen.commands.fix.ALL_CHECKS", [_ConfirmOnlyCheck])
    monkeypatch.setattr(rich.prompt.Confirm, "ask", staticmethod(lambda *a, **k: True))
    apply_fixes(tmp_path, interactive=True, console=_console())
    assert _ConfirmOnlyCheck.applied is True
