"""Citation file check: CITATION.cff exists, parses, and matches the version."""

import re
from pathlib import Path

import yaml

from .base import Check, CheckResult, Fix, Impact, Issue, Severity
from .version import static_pyproject_version

REQUIRED_KEYS = ("cff-version", "title", "authors")

_VERSION_LINE = re.compile(
    r"^(?P<prefix>version:\s*)(?P<value>.+?)(?P<trail>\s*)$", re.MULTILINE
)


class CitationCheck(Check):
    """Check that CITATION.cff exists and parses as a plausible CFF file."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "citation"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check CITATION.cff exists and is valid YAML"

    def run(self) -> CheckResult:
        """Run the citation check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        citation_path = self.project_dir / "CITATION.cff"

        if not citation_path.exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description="CITATION.cff is missing",
                    file=Path("CITATION.cff"),
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "Every fleet repo ships a CITATION.cff; 'preen adopt' "
                        "creates one from the template."
                    ),
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        try:
            data = yaml.safe_load(citation_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"CITATION.cff is not valid YAML: {exc}",
                    file=Path("CITATION.cff"),
                    impact=Impact.IMPORTANT,
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        if not isinstance(data, dict):
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description="CITATION.cff does not contain a YAML mapping",
                    file=Path("CITATION.cff"),
                    impact=Impact.IMPORTANT,
                )
            )
        else:
            missing = [key for key in REQUIRED_KEYS if key not in data]
            if missing:
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=(
                            f"CITATION.cff is missing keys: {', '.join(missing)}"
                        ),
                        file=Path("CITATION.cff"),
                        impact=Impact.IMPORTANT,
                    )
                )
            issues.extend(self._version_issues(citation_path, data))

        blocking = [issue for issue in issues if issue.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)

    def _version_issues(self, citation_path: Path, data: dict) -> list[Issue]:
        """Compare the recorded citation version against project.version.

        A CITATION.cff that parses and carries every required key can still
        cite a release from a decade ago: get-weather-data passed this check
        while its file said 0.1.31, dated 2016, against an actual 6.1.0. Anyone
        who cites the package copies that number (issue #50).

        Args:
            citation_path: Path to CITATION.cff.
            data: The parsed citation mapping.

        Returns:
            At most one issue.
        """
        project_version = static_pyproject_version(self.project_dir)
        if project_version is None:
            return []

        if "version" not in data:
            return [
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=(
                        "CITATION.cff has no version key, so it cites the "
                        f"package without saying which release ({project_version})"
                    ),
                    file=Path("CITATION.cff"),
                    impact=Impact.INFORMATIONAL,
                )
            ]

        cited = str(data["version"])
        if cited == project_version:
            return []

        return [
            Issue(
                check=self.name,
                severity=Severity.WARNING,
                description=(
                    f"CITATION.cff cites version {cited} but project.version "
                    f"is {project_version}"
                ),
                file=Path("CITATION.cff"),
                impact=Impact.IMPORTANT,
                explanation=(
                    "Whoever cites this package copies the number in "
                    "CITATION.cff; 'preen fix citation' syncs it."
                ),
                proposed_fix=self._sync_fix(citation_path, cited, project_version),
            )
        ]

    def _sync_fix(self, citation_path: Path, cited: str, wanted: str) -> Fix:
        """Build a fix that rewrites the citation's version line.

        A targeted substitution rather than a YAML round-trip: re-emitting the
        document would reorder keys and drop comments from a file a human wrote.

        Args:
            citation_path: Path to CITATION.cff.
            cited: The version currently recorded.
            wanted: The project version to write.

        Returns:
            The fix.
        """

        def apply() -> None:
            """Rewrite the first version line in place."""
            text = citation_path.read_text(encoding="utf-8")
            citation_path.write_text(
                _VERSION_LINE.sub(
                    lambda m: f"{m.group('prefix')}{wanted}{m.group('trail')}",
                    text,
                    count=1,
                ),
                encoding="utf-8",
            )

        return Fix(
            description=f"Set CITATION.cff version to {wanted}",
            diff=f"-version: {cited}\n+version: {wanted}\n",
            apply=apply,
        )

    def can_fix(self) -> bool:
        """Return True: a stale citation version can be rewritten.

        Returns:
            True.
        """
        return True
