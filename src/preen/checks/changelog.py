"""Keep a Changelog `changelog` check.

Flags a missing CHANGELOG.md, a CHANGELOG.md with no recognizable Keep a
Changelog structure, and one with version headings but no `[Unreleased]`
section. `preen release` reuses the heading-parsing helpers here to decide
whether a release has a changelog entry.
"""

import re
from pathlib import Path

from packaging.version import InvalidVersion, Version

from .base import Check, CheckResult, Impact, Issue, Severity

# A level-2 markdown heading, e.g. "## [Unreleased]" or "## 1.2.3 (2026-01-01)".
_HEADING_RE = re.compile(r"^##\s+(.*?)\s*$")

# Tolerates "[Unreleased]" and "Unreleased", case-insensitive.
_UNRELEASED_RE = re.compile(r"^\[?unreleased\]?$", re.IGNORECASE)

# Tolerates "[1.2.3] - 2026-01-01", "1.2.3 (2026-01-01)", and "v1.2.3". The
# candidate must run to a word boundary: matching a bare X.Y.Z prefix would
# let a "[1.2.3rc1]" heading satisfy the release gate for 1.2.3.
_VERSION_RE = re.compile(r"^\[?v?([^\[\]\s]+?)\]?(?=[\s(]|$)")


def parse_headings(text: str) -> list[tuple[int, str]]:
    """Return (line_index, heading_text) for each level-2 markdown heading."""
    headings = []
    for i, line in enumerate(text.splitlines()):
        match = _HEADING_RE.match(line)
        if match:
            headings.append((i, match.group(1)))
    return headings


def is_unreleased_heading(heading_text: str) -> bool:
    """Return True if `heading_text` is a Keep a Changelog Unreleased heading."""
    return bool(_UNRELEASED_RE.match(heading_text.strip()))


def heading_version(heading_text: str) -> str | None:
    """Return the PEP 440 version a heading names, or None if it doesn't.

    Accepts pre/post/dev releases ("1.2.3rc1", "1.2.3.post1") as well as
    plain X.Y.Z, and rejects anything `packaging` won't parse as a version.
    """
    match = _VERSION_RE.match(heading_text.strip())
    if not match:
        return None
    candidate = match.group(1)
    try:
        Version(candidate)
    except InvalidVersion:
        return None
    return candidate


def has_version_entry(text: str, version: str) -> bool:
    """Return True if `text` has a version heading matching `version`.

    Compares normalized PEP 440 versions, so "1.2.3" matches a "1.2.3.0"
    heading but not a "1.2.3rc1" one.
    """
    try:
        wanted = Version(version)
    except InvalidVersion:
        return False
    for _, heading_text in parse_headings(text):
        found = heading_version(heading_text)
        if found is not None and Version(found) == wanted:
            return True
    return False


def unreleased_section_text(text: str) -> str | None:
    """Return the raw content under the Unreleased heading, or None if absent."""
    lines = text.splitlines()
    headings = parse_headings(text)
    for index, (line_no, heading_text) in enumerate(headings):
        if not is_unreleased_heading(heading_text):
            continue
        start = line_no + 1
        end = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        return "\n".join(lines[start:end])
    return None


def rename_unreleased_heading(text: str, version: str, date: str) -> str:
    """Return `text` with the Unreleased heading renamed to a version heading."""
    lines = text.splitlines(keepends=True)
    for line_no, heading_text in parse_headings(text):
        if is_unreleased_heading(heading_text):
            ending = "\n" if lines[line_no].endswith("\n") else ""
            lines[line_no] = f"## [{version}] - {date}{ending}"
            break
    return "".join(lines)


class ChangelogCheck(Check):
    """Check CHANGELOG.md follows Keep a Changelog structure."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "changelog"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check CHANGELOG.md follows Keep a Changelog structure"

    def run(self) -> CheckResult:
        """Run the changelog check.

        Returns:
            CheckResult containing any issues found.
        """
        changelog_path = self.project_dir / "CHANGELOG.md"
        if not changelog_path.exists():
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[self._missing_changelog_issue(changelog_path)],
            )

        text = changelog_path.read_text(encoding="utf-8")
        headings = parse_headings(text)
        has_unreleased = any(is_unreleased_heading(h) for _, h in headings)
        has_version = any(heading_version(h) is not None for _, h in headings)

        if not has_unreleased and not has_version:
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[self._no_structure_issue(changelog_path)],
            )

        if has_version and not has_unreleased:
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[self._missing_unreleased_issue(changelog_path)],
            )

        return CheckResult(check=self.name, passed=True, issues=[])

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False

    # -- finding builders --------------------------------------------------

    def _missing_changelog_issue(self, changelog_path: Path) -> Issue:
        """Build the issue for a repo with no CHANGELOG.md at all."""
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description="No CHANGELOG.md at repo root",
            file=changelog_path.relative_to(self.project_dir),
            impact=Impact.IMPORTANT,
            explanation=(
                "Keep a Changelog format expected; `preen release` will "
                "refuse to tag without it."
            ),
        )

    def _no_structure_issue(self, changelog_path: Path) -> Issue:
        """Build the issue for a CHANGELOG.md with no recognizable structure."""
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description=(
                "CHANGELOG.md has no `## [Unreleased]` section or version headings"
            ),
            file=changelog_path.relative_to(self.project_dir),
            impact=Impact.IMPORTANT,
            explanation=(
                "This isn't a recognizable Keep a Changelog structure. Add "
                "an `## [Unreleased]` section and/or `## [X.Y.Z] - "
                "YYYY-MM-DD` version headings."
            ),
        )

    def _missing_unreleased_issue(self, changelog_path: Path) -> Issue:
        """Build the issue for a CHANGELOG.md with versions but no Unreleased."""
        return Issue(
            check=self.name,
            severity=Severity.INFO,
            description="CHANGELOG.md has no `## [Unreleased]` section",
            file=changelog_path.relative_to(self.project_dir),
            impact=Impact.INFORMATIONAL,
            explanation=(
                "Keep an Unreleased section for accumulating changes between releases."
            ),
        )
