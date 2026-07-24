"""Tests for interactive.py: EducationalPrompt and InteractiveReleaseWorkflow."""

import io

import rich.prompt
from rich.console import Console

from preen.checks.base import CheckResult, Fix, Impact, Issue, Severity
from preen.interactive import EducationalPrompt, InteractiveReleaseWorkflow


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, no_color=True)


# --- EducationalPrompt -------------------------------------------------


def test_explain_check_passed_prints_checkmark() -> None:
    console = _console()
    EducationalPrompt(console).explain_check("ruff", [])
    output = console.file.getvalue()
    assert "ruff passed" in output


def test_explain_check_groups_unique_explanations_and_lists_issues() -> None:
    issues = [
        Issue(
            check="ruff",
            severity=Severity.WARNING,
            description="lint problem A",
            explanation="Shared explanation.",
            impact=Impact.IMPORTANT,
        ),
        Issue(
            check="ruff",
            severity=Severity.WARNING,
            description="lint problem B",
            explanation="Shared explanation.",  # duplicate on purpose
            impact=Impact.CRITICAL,
        ),
    ]
    console = _console()
    EducationalPrompt(console).explain_check("ruff", issues)
    output = console.file.getvalue()
    assert "About ruff check" in output
    # The shared explanation appears once, not twice.
    assert output.count("Shared explanation.") == 1
    assert "Found 2 issue(s)" in output
    assert "lint problem A" in output
    assert "lint problem B" in output
    # Impact symbols rendered per issue.
    assert "🚫" in output  # critical
    assert "⚠️" in output  # important


def test_explain_check_skips_empty_explanations() -> None:
    issues = [
        Issue(check="ruff", severity=Severity.WARNING, description="no explanation")
    ]
    console = _console()
    EducationalPrompt(console).explain_check("ruff", issues)
    output = console.file.getvalue()
    assert "Found 1 issue(s)" in output


# --- InteractiveReleaseWorkflow -----------------------------------------


def _make_result(check: str, issues: list[Issue]) -> CheckResult:
    return CheckResult(check=check, passed=not issues, issues=issues)


def test_no_issues_goes_straight_to_final_confirmation(monkeypatch) -> None:
    console = _console()
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    workflow = InteractiveReleaseWorkflow(console)
    assert workflow.run_release_checks({}, target="PyPI") is True
    assert "Ready for Release" in console.file.getvalue()


def test_critical_issue_blocks_release_without_prompting(monkeypatch) -> None:
    console = _console()

    def fail_confirm(*a, **k):
        raise AssertionError("must not prompt when a critical issue blocks release")

    monkeypatch.setattr(rich.prompt.Confirm, "ask", fail_confirm)
    issue = Issue(
        check="deptree",
        severity=Severity.ERROR,
        description="circular import",
        explanation="Breaks at runtime.",
        impact=Impact.CRITICAL,
    )
    workflow = InteractiveReleaseWorkflow(console)
    result = workflow.run_release_checks({"deptree": _make_result("deptree", [issue])})
    assert result is False
    output = console.file.getvalue()
    assert "Critical Issues Found" in output
    assert "circular import" in output
    assert "Cannot proceed with release" in output


def test_important_issue_declined_override_cancels(monkeypatch) -> None:
    console = _console()
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: False)
    issue = Issue(
        check="ruff",
        severity=Severity.WARNING,
        description="style nit",
        impact=Impact.IMPORTANT,
    )
    workflow = InteractiveReleaseWorkflow(console)
    result = workflow.run_release_checks({"ruff": _make_result("ruff", [issue])})
    assert result is False
    assert "cancelled by user" in console.file.getvalue()


def test_important_issue_override_accepted_proceeds(monkeypatch) -> None:
    console = _console()
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    issue = Issue(
        check="ruff",
        severity=Severity.WARNING,
        description="style nit",
        impact=Impact.IMPORTANT,
    )
    workflow = InteractiveReleaseWorkflow(console)
    result = workflow.run_release_checks({"ruff": _make_result("ruff", [issue])})
    assert result is True
    output = console.file.getvalue()
    assert "Proceeding despite issue" in output
    assert "Summary of overrides" in output
    assert workflow.overrides == {"ruff:style nit": True}


def test_important_issue_fix_choice_applies_fix(monkeypatch) -> None:
    console = _console()
    applied = {}
    fix = Fix(
        description="autofix",
        diff="- a\n+ b\n",
        apply=lambda: applied.setdefault("done", True),
    )
    issue = Issue(
        check="ruff",
        severity=Severity.WARNING,
        description="style nit",
        impact=Impact.IMPORTANT,
        proposed_fix=fix,
    )
    monkeypatch.setattr(rich.prompt.Prompt, "ask", lambda *a, **k: "yes")
    workflow = InteractiveReleaseWorkflow(console)
    result = workflow._handle_important_issues([issue])
    assert result is True
    assert applied == {"done": True}
    assert "Fixed" in console.file.getvalue()


def test_important_issue_fix_choice_skip_continues(monkeypatch) -> None:
    console = _console()
    fix = Fix(
        description="autofix",
        diff="d",
        apply=lambda: (_ for _ in ()).throw(
            AssertionError("apply must not be called when skipped")
        ),
    )
    issue = Issue(
        check="ruff",
        severity=Severity.WARNING,
        description="style nit",
        impact=Impact.IMPORTANT,
        proposed_fix=fix,
    )
    monkeypatch.setattr(rich.prompt.Prompt, "ask", lambda *a, **k: "skip")
    workflow = InteractiveReleaseWorkflow(console)
    result = workflow._handle_important_issues([issue])
    assert result is True


def test_informational_issues_offer_optional_fix(monkeypatch) -> None:
    console = _console()
    applied = {}
    fix = Fix(
        description="improve",
        diff="d",
        apply=lambda: applied.setdefault("done", True),
    )
    issue = Issue(
        check="structure",
        severity=Severity.INFO,
        description="consider src layout",
        impact=Impact.INFORMATIONAL,
        proposed_fix=fix,
    )
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    workflow = InteractiveReleaseWorkflow(console)
    workflow._handle_informational_issues([issue])
    assert applied == {"done": True}
    assert "Applied" in console.file.getvalue()


def test_informational_issues_declined_does_not_apply(monkeypatch) -> None:
    console = _console()
    fix = Fix(
        description="improve",
        diff="d",
        apply=lambda: (_ for _ in ()).throw(AssertionError("must not apply")),
    )
    issue = Issue(
        check="structure",
        severity=Severity.INFO,
        description="consider src layout",
        impact=Impact.INFORMATIONAL,
        proposed_fix=fix,
    )
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: False)
    workflow = InteractiveReleaseWorkflow(console)
    workflow._handle_informational_issues([issue])
    assert "Applied" not in console.file.getvalue()


def test_empty_informational_issues_no_output() -> None:
    console = _console()
    workflow = InteractiveReleaseWorkflow(console)
    workflow._handle_informational_issues([])
    assert console.file.getvalue() == ""
