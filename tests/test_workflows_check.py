"""Tests for the canon-owned workflow check."""

from pathlib import Path

from preen.checks.base import Impact, Severity
from preen.checks.workflows import WorkflowsCheck

CALLER = """\
name: Dependabot auto-merge
on:
  pull_request:
  schedule:
    - cron: "37 */3 * * *"
jobs:
  auto-merge:
    uses: gojiplus/py-canon/.github/workflows/reusable-dependabot-auto-merge.yml@v1
"""

# What 22 of the fleet's 26 repos were actually holding: the logic inlined,
# and -- the part that mattered -- no schedule, so nothing re-armed the
# auto-merge GitHub silently disarms.
STALE_COPY = """\
name: Dependabot auto-merge
on:
  pull_request:
jobs:
  auto-merge:
    runs-on: ubuntu-latest
    steps:
      - uses: dependabot/fetch-metadata@v3
      - run: gh pr merge --auto --squash "$PR_URL"
"""


def _workflow(tmp_path: Path, name: str, body: str) -> None:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)


def test_no_workflows_passes(tmp_path: Path) -> None:
    """Absence is the template/files checks' business, not this one."""
    assert WorkflowsCheck(tmp_path).run().passed


def test_caller_passes(tmp_path: Path) -> None:
    _workflow(tmp_path, "dependabot-auto-merge.yml", CALLER)
    assert WorkflowsCheck(tmp_path).run().passed


def test_stale_copy_is_flagged(tmp_path: Path) -> None:
    """The finding this check exists for.

    py-canon#19 replaced the copied auto-merge workflow with a caller and
    distributed it through the template, which reaches existing repos never.
    22 of 26 repos kept the copy, 21 of those without a schedule block, and no
    check said anything: `template` only compares the recorded _commit string
    against canon's latest tag.
    """
    _workflow(tmp_path, "dependabot-auto-merge.yml", STALE_COPY)
    result = WorkflowsCheck(tmp_path).run()

    assert not result.passed
    issue = result.issues[0]
    assert issue.severity == Severity.WARNING
    assert issue.impact == Impact.IMPORTANT
    assert "copy rather than a caller" in issue.description
    assert "skip_checks" in issue.description
    assert issue.file == Path(".github/workflows/dependabot-auto-merge.yml")


def test_self_reference_passes(tmp_path: Path) -> None:
    """py-canon itself calls by path, so a PR tests the branch under review."""
    _workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  ci:\n    uses: ./.github/workflows/reusable-ci.yml\n",
    )
    assert WorkflowsCheck(tmp_path).run().passed


def test_each_canon_workflow_is_checked(tmp_path: Path) -> None:
    for name in ("ci.yml", "docs.yml", "release.yml", "dependabot-auto-merge.yml"):
        _workflow(tmp_path, name, "jobs:\n  x:\n    runs-on: ubuntu-latest\n")
    result = WorkflowsCheck(tmp_path).run()
    assert len(result.issues) == 4


def test_a_repos_own_extra_workflow_is_none_of_our_business(tmp_path: Path) -> None:
    _workflow(tmp_path, "e2e.yml", "jobs:\n  x:\n    runs-on: ubuntu-latest\n")
    assert WorkflowsCheck(tmp_path).run().passed


def test_can_fix_false(tmp_path: Path) -> None:
    """A copy may be deliberate; replacing CI is not a lint fix."""
    assert WorkflowsCheck(tmp_path).can_fix() is False
