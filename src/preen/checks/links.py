r"""Link validation check.

URL extraction is delegated to lychee rather than done here with a regex.

The regex this replaced used explicit character classes for the path and query
-- ``[-\\w/_.~%@+]`` and ``[-\\w&=%.]`` -- and both were missing legal URL
characters. Parentheses, semicolons, commas, exclamation marks and a colon
inside a query value all terminated the match early, so a URL was not skipped
but *truncated*, which is worse: the shortened URL is a different URL. It may
still answer 200, and the real link goes unchecked; or it may 404, and the
check reports a dead link that is perfectly healthy. Five of seven realistic
URLs truncated, including a Wikipedia article whose title ends in
``(programming_language)``.

lychee is the same checker the R half of the fleet runs via r-canon's
reusable-link-check workflow, so both halves now agree on what a URL is.
"""

import json
import shutil
import subprocess
import sysconfig
from pathlib import Path
from typing import ClassVar

from ..config import PreenConfig
from .base import Check, CheckResult, Impact, Issue, Severity


class LinkCheck(Check):
    """Check for broken or dead links in project files."""

    # File patterns to scan
    SCAN_PATTERNS: ClassVar[set[str]] = {
        "*.md",
        "*.rst",
        "*.txt",
        "*.py",
        "*.toml",
        "*.yaml",
        "*.yml",
        "*.json",
        "*.cfg",
        "*.ini",
        "*.sh",
    }

    # Hosts that are placeholders rather than destinations. Anchored so that a
    # real host merely containing one of these names is still checked.
    DEFAULT_SKIP_PATTERNS: ClassVar[tuple[str, ...]] = (
        r"^https?://localhost(:\d+)?([/?#]|$)",
        r"^https?://127\.0\.0\.1(:\d+)?([/?#]|$)",
        r"^https?://0\.0\.0\.0(:\d+)?([/?#]|$)",
        r"^https?://([^/]*\.)?example\.(com|org|net)([/?#]|$)",
        r"^https?://([^/]*\.)?test\.com([/?#]|$)",
        r"^https?://([^/]*\.)?placeholder\.com([/?#]|$)",
        r"^https?://([^/]*\.)?your-domain\.com([/?#]|$)",
        # A URL carrying a {placeholder} is a template in source, not a link:
        # this check scans .py files, so every f-string and .format() target is
        # extracted verbatim. Fetching one with the braces still in it 404s by
        # construction, which says nothing about whether the real URL works.
        # lychee percent-encodes the braces, so match both forms.
        #
        # gojiplus/get-weather-data had five of these and nothing else wrong,
        # among them .../ghcn/daily/by_year/%7Byear%7D.csv.gz -- that is
        # `{year}`.
        r"(\{|%7[Bb])",
    )

    # Anti-bot and auth responses do not mean the link is dead for a human
    # reader, so they are collected by lychee and then dropped here rather than
    # passed to --accept. Keeping lychee strict leaves the severity decision in
    # one place.
    # 400 joins them for the same reason: an API base URL answers a bare GET
    # with "you did not give me parameters", which proves the endpoint is alive
    # rather than dead. gojiplus/get-weather-data documents three NOAA bases
    # that each 400 on their own and return 200 with the query the code
    # actually sends:
    #
    #   .../access/services/data/v1                                    -> 400
    #   .../access/services/data/v1?dataset=daily-summaries&stations=.. -> 200
    IGNORED_STATUS_CODES: ClassVar[frozenset[int]] = frozenset(
        {400, 401, 403, 405, 429}
    )

    NETWORK_TIMEOUT_SECONDS: ClassVar[int] = 300

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "links"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check for broken or dead links in project files"

    def _lychee_binary(self) -> str | None:
        """Locate the lychee executable.

        Returns:
            Path to the binary, or None if it cannot be found.
        """
        found = shutil.which("lychee")
        if found:
            return found
        # lychee-bin installs into the interpreter's scripts directory, which is
        # not necessarily on PATH when preen is invoked via its own entry point.
        scripts = Path(sysconfig.get_path("scripts"))
        for candidate in (scripts / "lychee", scripts / "lychee.exe"):
            if candidate.is_file():
                return str(candidate)
        return None

    def _collect_files(self) -> list[Path]:
        """Gather the project files whose links should be checked.

        Returns:
            Sorted list of absolute paths.
        """
        files: set[Path] = set()
        for pattern in self.SCAN_PATTERNS:
            for file_path in self.project_dir.glob(f"**/{pattern}"):
                if any(part.startswith(".") for part in file_path.parts):
                    continue
                if self.is_excluded(file_path.relative_to(self.project_dir)):
                    continue
                files.add(file_path)
        return sorted(files)

    def _run_lychee(self, files: list[Path]) -> dict:
        """Run lychee over the given files and return its parsed JSON report.

        Args:
            files: Files to scan.

        Returns:
            The parsed report, or an empty dict if lychee could not be run.
        """
        binary = self._lychee_binary()
        if binary is None:
            return {}

        # --scheme keeps this to web URLs. lychee will otherwise resolve
        # relative markdown links against the filesystem and report missing
        # files, which the regex this replaced never looked at. That may be
        # worth turning on, but it is a change of scope rather than a fix to
        # extraction, and it belongs in its own change.
        cmd = [
            binary,
            "--no-progress",
            "--format",
            "json",
            "--max-retries",
            "3",
            "--scheme",
            "http",
            "--scheme",
            "https",
        ]
        for pattern in self.DEFAULT_SKIP_PATTERNS:
            cmd += ["--exclude", pattern]
        # A repo's own known-good endpoints, from [tool.preen] link_ignore.
        for pattern in PreenConfig.from_pyproject(self.project_dir).link_ignore:
            cmd += ["--exclude", pattern]
        cmd += [str(f) for f in files]

        try:
            # lychee exits non-zero when it finds broken links, so the exit code
            # is a result rather than a failure; the report is on stdout either
            # way.
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.NETWORK_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return {}

        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {}

    def _get_impact_for_file(self, file_path: Path) -> Impact:
        """Determine impact level based on file location.

        Args:
            file_path: Path the link was found in.

        Returns:
            The impact level for issues in that file.
        """
        file_str = str(file_path).lower()

        # Critical files
        if any(
            critical in file_str for critical in ["readme", "docs/", "documentation"]
        ):
            return Impact.CRITICAL

        # Important files
        if (
            file_path.suffix in [".md", ".rst", ".yml", ".yaml"]
            or file_path.name == "pyproject.toml"
        ):
            return Impact.IMPORTANT

        # Everything else
        return Impact.INFORMATIONAL

    def _issue_for(self, rel_path: Path, entry: dict) -> Issue | None:
        """Turn one lychee error entry into an Issue.

        Args:
            rel_path: Project-relative path of the file the link appears in.
            entry: One element of a lychee ``error_map`` list.

        Returns:
            The Issue, or None if this status should not be reported.
        """
        url = entry.get("url", "")
        status = entry.get("status") or {}
        code = status.get("code")
        line = (entry.get("span") or {}).get("line")
        impact = self._get_impact_for_file(rel_path)

        if code is None:
            # No HTTP status at all: DNS failure, TLS failure, connection
            # refused, timeout.
            detail = status.get("details") or status.get("text") or "unreachable"
            return Issue(
                check=self.name,
                severity=Severity.ERROR,
                description=f"Dead link: {url} - {detail}",
                file=rel_path,
                line=line,
                impact=impact,
                explanation=f"Link appears to be dead or unreachable: {detail}",
            )

        if code in self.IGNORED_STATUS_CODES:
            return None

        if 400 <= code < 500:
            return Issue(
                check=self.name,
                severity=Severity.WARNING,
                description=f"Broken link: {url} (HTTP {code})",
                file=rel_path,
                line=line,
                impact=impact,
                explanation=(
                    f"Link returns HTTP {code}, indicating a client error "
                    "(page not found, forbidden, etc.)"
                ),
            )

        if 500 <= code < 600:
            return Issue(
                check=self.name,
                severity=Severity.WARNING,
                description=f"Server error for link: {url} (HTTP {code})",
                file=rel_path,
                line=line,
                impact=impact,
                explanation=f"Link returns HTTP {code}, indicating a server error",
            )

        return None

    def run(self) -> CheckResult:
        """Run the link check.

        Returns:
            The check result.
        """
        files = self._collect_files()
        if not files:
            return CheckResult(check=self.name, passed=True, issues=[])

        report = self._run_lychee(files)
        error_map = report.get("error_map") or {}

        issues = []
        for raw_path, entries in error_map.items():
            path = Path(raw_path)
            try:
                rel_path = path.relative_to(self.project_dir)
            except ValueError:
                rel_path = path
            for entry in entries:
                issue = self._issue_for(rel_path, entry)
                if issue is not None:
                    issues.append(issue)

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues.

        Returns:
            False; broken links have no mechanical fix.
        """
        return False
