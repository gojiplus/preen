"""Citation file check: CITATION.cff exists, parses, and matches the version."""

import re
import subprocess
from pathlib import Path

import yaml

from .base import Check, CheckResult, Fix, Impact, Issue, Severity
from .version import static_pyproject_version

REQUIRED_KEYS = ("cff-version", "title", "authors")

#: GitHub reads this exact name and no other spelling.
CITATION_NAME = "CITATION.cff"

# The quote group is kept separate so a rewrite preserves how the repo wrote
# it: `version: "0.6.0"` must not become `version: 0.9.0`.
_VERSION_LINE = re.compile(
    r"^(?P<prefix>version:[ \t]*)(?P<quote>[\"\']?)(?P<value>.*?)(?P=quote)"
    r"(?P<trail>[ \t]*)$",
    re.MULTILINE,
)
_DATE_LINE = re.compile(
    r"^(?P<prefix>date-released:[ \t]*)(?P<quote>[\"\']?)(?P<value>.*?)(?P=quote)"
    r"(?P<trail>[ \t]*)$",
    re.MULTILINE,
)


def _tag_date(project_dir: Path, version: str) -> str | None:
    """Return the commit date of the tag naming `version`, if there is one.

    Args:
        project_dir: Repository directory.
        version: The version being cited.

    Returns:
        An ISO date, or None when no tag matches or git cannot answer.
    """
    for tag in (f"v{version}", version):
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%cs", tag],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _replacement(value: str):
    """Build a re.sub replacement that rewrites a value and keeps its quoting.

    Args:
        value: The new value to write.

    Returns:
        A callable suitable for ``re.sub``.
    """
    return lambda match: (
        f"{match.group('prefix')}{match.group('quote')}{value}"
        f"{match.group('quote')}{match.group('trail')}"
    )


def citation_path(project_dir: Path) -> Path | None:
    """Return the repo's CITATION.cff, however it is spelled.

    Matched case-insensitively on purpose: a macOS checkout resolves
    ``CITATION.cff`` to a file named ``citation.cff``, so an existence test
    alone reports a file that GitHub -- and a Linux CI runner -- never sees.

    Args:
        project_dir: Repository directory.

    Returns:
        The path as it is actually spelled on disk, or None.
    """
    exact = project_dir / CITATION_NAME
    try:
        entries = list(project_dir.iterdir())
    except OSError:
        return exact if exact.is_file() else None
    for entry in entries:
        if entry.name == CITATION_NAME:
            return entry
    for entry in entries:
        if entry.name.lower() == CITATION_NAME.lower():
            return entry
    return None


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
        found = citation_path(self.project_dir)

        if found is not None and found.name != CITATION_NAME:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"Citation file is named {found.name!r}; GitHub reads "
                        f"{CITATION_NAME!r} and no other spelling"
                    ),
                    file=Path(found.name),
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "The 'Cite this repository' button never appears, and "
                        "a case-sensitive checkout does not see the file at "
                        f"all. Rename it with 'git mv {found.name} "
                        f"{CITATION_NAME}'."
                    ),
                )
            )

        if found is None:
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
            data = yaml.safe_load(found.read_text(encoding="utf-8"))
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
            issues.extend(self._version_issues(found, data))

        blocking = [issue for issue in issues if issue.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)

    def _version_issues(self, path: Path, data: dict) -> list[Issue]:
        """Compare the recorded citation version against project.version.

        A CITATION.cff that parses and carries every required key can still
        cite a release from a decade ago: get-weather-data passed this check
        while its file said 0.1.31, dated 2016, against an actual 6.1.0. Anyone
        who cites the package copies that number (issue #50).

        Args:
            path: Path to the citation file.
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
                proposed_fix=self._sync_fix(path, cited, project_version),
            )
        ]

    def _sync_fix(self, path: Path, cited: str, wanted: str) -> Fix:
        """Build a fix that rewrites the citation's version, and its date.

        A targeted substitution rather than a YAML round-trip: re-emitting the
        document would reorder keys and drop comments from a file a human wrote.
        The quoting is preserved for the same reason -- ``version: "0.6.0"``
        must not come back as ``version: 0.9.0``.

        ``date-released`` moves with the version when a tag names it. Syncing
        the number alone leaves a record that is internally false: on
        get-weather-data it would have claimed 6.1.0 was released on
        2016-07-17, when the tag is dated 2026-07-25. A wrong date beside a
        right version is not an improvement.

        Args:
            path: Path to the citation file, however it is spelled.
            cited: The version currently recorded.
            wanted: The project version to write.

        Returns:
            The fix.
        """
        released = _tag_date(self.project_dir, wanted)
        text = path.read_text(encoding="utf-8")
        dated = _DATE_LINE.search(text)
        stale_date = (
            released is not None
            and dated is not None
            and dated.group("value") != released
        )

        def apply() -> None:
            """Rewrite the version line, and the release date when it is known."""
            current = path.read_text(encoding="utf-8")
            updated = _VERSION_LINE.sub(_replacement(wanted), current, count=1)
            if stale_date and released is not None:
                updated = _DATE_LINE.sub(_replacement(released), updated, count=1)
            path.write_text(updated, encoding="utf-8")

        diff = f"-version: {cited}\n+version: {wanted}\n"
        description = f"Set {path.name} version to {wanted}"
        if stale_date:
            assert dated is not None  # noqa: S101 -- implied by stale_date
            diff += f"-date-released: {dated.group('value')}\n"
            diff += f"+date-released: {released}\n"
            description += f" and its release date to {released}"

        return Fix(description=description, diff=diff, apply=apply)

    def can_fix(self) -> bool:
        """Return True: a stale citation version can be rewritten.

        Returns:
            True.
        """
        return True
