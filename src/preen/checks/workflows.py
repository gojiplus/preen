"""Canon-owned workflow check: is this repo wired to py-canon, or holding a copy?

Adoption is a one-time event. `preen adopt` and `preen new` write the template's
files into a repo and stop; `.copier-answers.yml` records `_commit: v1`, and
because v1 is a *moving* tag `copier update` compares "v1" against "v1" and
reports "Keeping template version 1" without looking at what it now points to.
So a repo adopts once and then drifts, and nothing notices.

Nothing noticed. py-canon#19 replaced the copied Dependabot auto-merge workflow
with a five-line caller, and it was distributed through the template -- which
reaches existing repos never. Measured across the 26 repos in py-canon's FLEET
some weeks later: **22 still held the old copy, and 21 of those had no
`schedule` block**, so no sweep re-armed the auto-merge GitHub silently
disarms. 57 Dependabot PRs were open, 37 of them green and simply never merged,
one as old as 469 hours.

The `template` check could not have caught this: it compares the recorded
`_commit` string against canon's latest tag, which says nothing about whether
the workflow files are still the ones canon publishes. This check asks the
question directly -- does the file reference py-canon, or is it a copy of it?

A copy is not automatically wrong. A repo may have a real reason to run its own
CI, and `finite-sample/rmcp` does: its pipeline builds a Docker image and runs R
integration tests inside it. That is what `skip_checks` is for, and the finding
names it.
"""

import re
from pathlib import Path
from typing import ClassVar

from .base import Check, CheckResult, Impact, Issue, Severity

# Workflow file -> the reusable workflow a caller should name. Only files that
# py-canon actually publishes a reusable counterpart for: a repo's own extra
# workflows are its own business.
CANON_WORKFLOWS: dict[str, str] = {
    "ci.yml": "reusable-ci.yml",
    "docs.yml": "reusable-docs.yml",
    "release.yml": "reusable-release.yml",
    "dependabot-auto-merge.yml": "reusable-dependabot-auto-merge.yml",
}

WORKFLOW_DIR = Path(".github/workflows")


class WorkflowsCheck(Check):
    """Check canon-owned workflows are callers rather than stale copies."""

    # `uses: gojiplus/py-canon/.github/workflows/<name>@<ref>` is the caller
    # form. `uses: ./.github/workflows/<name>` is py-canon itself, which must
    # run the version on the branch under review rather than the released tag.
    CALLER_PATTERNS: ClassVar[tuple[str, ...]] = (
        r"uses:\s*\S*py-canon/\.github/workflows/{name}@",
        r"uses:\s*\./\.github/workflows/{name}",
    )

    @property
    def name(self) -> str:
        """Return the name of this check.

        Returns:
            The check name.
        """
        return "workflows"

    @property
    def description(self) -> str:
        """Return a description of what this check does.

        Returns:
            The check description.
        """
        return "Check canon-owned workflows reference py-canon rather than copy it"

    def _references_canon(self, text: str, reusable: str) -> bool:
        """Report whether `text` calls the named reusable workflow.

        Args:
            text: Contents of the workflow file.
            reusable: Filename of the reusable workflow it should call.

        Returns:
            True when the file is a caller rather than a copy.
        """
        stem = re.escape(reusable)
        return any(
            re.search(pattern.format(name=stem), text)
            for pattern in self.CALLER_PATTERNS
        )

    def run(self) -> CheckResult:
        """Run the canon-owned workflow check.

        Returns:
            The check result.
        """
        issues = []
        for filename, reusable in sorted(CANON_WORKFLOWS.items()):
            path = self.project_dir / WORKFLOW_DIR / filename
            if not path.exists():
                # Absence is the `template`/`files` checks' business, not this
                # one. Here the question is only whether a file that exists is
                # wired up.
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if self._references_canon(text, reusable):
                continue
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"{filename} is a copy rather than a caller: it does not "
                        f"reference py-canon's {reusable}, so fixes published "
                        "there never reach this repo. Replace it with the "
                        "template's caller, or record the reason with "
                        '`skip_checks = ["workflows"]` if this repo has to run '
                        "its own."
                    ),
                    file=WORKFLOW_DIR / filename,
                    impact=Impact.IMPORTANT,
                )
            )

        return CheckResult(check=self.name, passed=not issues, issues=issues)

    def can_fix(self) -> bool:
        """Report whether this check can fix what it finds.

        Returns:
            False. Replacing a workflow is a decision about how the repo builds,
            and a copy may be deliberate; the finding says what to do instead.
        """
        return False
