"""Template adoption and drift check against the py-canon copier template."""

import re
import subprocess

import yaml

from .base import Check, CheckResult, Impact, Issue, Severity

CANON_URL = "https://github.com/gojiplus/py-canon"
ANSWERS_FILE = ".copier-answers.yml"

_VERSION_TAG = re.compile(r"refs/tags/(v\d+(?:\.\d+)*)$")


def latest_canon_tag(url: str = CANON_URL, timeout: float = 10.0) -> str | None:
    """Return the latest ``v*`` tag of the template repo, or None if offline.

    Args:
        url: Git URL of the template repository.
        timeout: Seconds to wait for ``git ls-remote``.

    Returns:
        The highest version tag (e.g. ``v1.2.0``), or None when the remote
        cannot be reached.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    tags: list[tuple[tuple[int, ...], str]] = []
    for line in result.stdout.splitlines():
        match = _VERSION_TAG.search(line.strip())
        if match:
            tag = match.group(1)
            key = tuple(int(part) for part in tag[1:].split("."))
            tags.append((key, tag))
    if not tags:
        return None
    return max(tags)[1]


class TemplateCheck(Check):
    """Check that the repo is adopted from py-canon and tracks its latest tag."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "template"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check adoption of the py-canon template and template drift"

    def run(self) -> CheckResult:
        """Run the template adoption/drift check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        answers_path = self.project_dir / ANSWERS_FILE

        if not answers_path.exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=(
                        f"No {ANSWERS_FILE} — repo is not adopted from the "
                        "py-canon template"
                    ),
                    impact=Impact.CRITICAL,
                    explanation=(
                        "The fleet standard propagates through the copier "
                        "template; run 'preen adopt' to retrofit this repo."
                    ),
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        try:
            answers = yaml.safe_load(answers_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"{ANSWERS_FILE} is not valid YAML: {exc}",
                    impact=Impact.CRITICAL,
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        commit = answers.get("_commit")
        latest = latest_canon_tag()
        if latest is None:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=(
                        "Could not reach the py-canon remote; skipping "
                        "template-drift comparison"
                    ),
                    impact=Impact.INFORMATIONAL,
                )
            )
        elif commit != latest:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"Template drift: {ANSWERS_FILE} records "
                        f"_commit={commit!r} but the latest py-canon tag is "
                        f"{latest!r}"
                    ),
                    impact=Impact.IMPORTANT,
                    explanation="Run 'preen update' to pull template changes.",
                )
            )
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=f"Drift: {commit!r} -> {latest!r}",
                    impact=Impact.INFORMATIONAL,
                )
            )

        blocking = [i for i in issues if i.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)
