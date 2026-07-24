"""Dependency vulnerability check using pip-audit.

Complements the `deps` check (unused/missing dependencies via deptry):
deptry doesn't look at known CVEs, pip-audit does. This check exports the
project's locked, pinned dependency set with `uv export` and scans it with
pip-audit.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

#: No existing subprocess check in this project sets an explicit timeout;
#: fall back to a generous 120s so a hung network call can't wedge `preen check`.
TIMEOUT_SECONDS = 120


class AuditCheck(Check):
    """Check locked dependencies for known vulnerabilities using pip-audit."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "audit"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check locked dependencies for known vulnerabilities with pip-audit"

    def run(self) -> CheckResult:
        """Run pip-audit over the project's exported, locked dependencies."""
        if not (self.project_dir / "uv.lock").exists():
            return self._skip(
                "No uv.lock found; pip-audit needs a locked, pinned "
                "dependency set to scan. Skipping audit."
            )

        requirements = self._export_requirements()
        if requirements is None:
            return self._skip(
                "Could not export requirements with `uv export`; skipping audit."
            )

        pip_audit_cmd = self._find_pip_audit()
        if pip_audit_cmd is None:
            return self._skip(
                "pip-audit is not installed. Install with: pip install pip-audit"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            requirements_path = Path(tmpdir) / "requirements.txt"
            requirements_path.write_text(requirements)

            try:
                result = subprocess.run(
                    [
                        *pip_audit_cmd,
                        "-r",
                        str(requirements_path),
                        "--disable-pip",
                        "--format",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=self.project_dir,
                    timeout=TIMEOUT_SECONDS,
                )
            except (subprocess.SubprocessError, OSError):
                return self._skip("pip-audit could not complete; skipping audit.")

        # 0: no vulnerabilities. 1: vulnerabilities found (with valid JSON on
        # stdout). Anything else is a genuine failure (network, bad
        # invocation) -- degrade gracefully rather than crash.
        if result.returncode not in (0, 1):
            return self._skip("pip-audit could not complete; skipping audit.")

        # A real report is always non-empty JSON (pip-audit prints
        # `{"dependencies": [...], "fixes": []}` even when there's nothing to
        # flag). Empty or unparsable stdout means pip-audit errored before
        # producing a report (e.g. a requirement it couldn't resolve).
        if not result.stdout.strip():
            return self._skip("pip-audit could not complete; skipping audit.")
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            return self._skip("pip-audit could not complete; skipping audit.")

        if not isinstance(report, dict):
            return self._skip("pip-audit could not complete; skipping audit.")

        issues = self._issues_from_report(report)
        return CheckResult(check=self.name, passed=len(issues) == 0, issues=issues)

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False  # Bumping a vulnerable dependency requires manual review

    def _export_requirements(self) -> str | None:
        """Export the project's locked dependencies as pinned requirements.

        Returns:
            The exported requirements-txt content, or None if `uv` is
            unavailable or the export fails.
        """
        try:
            result = subprocess.run(
                [
                    "uv",
                    "export",
                    "--format",
                    "requirements-txt",
                    "--no-emit-project",
                    "--all-groups",
                ],
                capture_output=True,
                text=True,
                cwd=self.project_dir,
                timeout=TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        if result.returncode != 0:
            return None
        return result.stdout

    def _find_pip_audit(self) -> list[str] | None:
        """Locate a runnable pip-audit command, trying `uvx` as a fallback.

        Returns:
            The command prefix to invoke pip-audit with, or None if it
            can't be found or run either directly or via `uvx`.
        """
        try:
            subprocess.run(
                ["pip-audit", "--version"],
                capture_output=True,
                check=True,
                cwd=self.project_dir,
                timeout=TIMEOUT_SECONDS,
            )
            return ["pip-audit"]
        except (subprocess.SubprocessError, OSError):
            pass

        try:
            subprocess.run(
                ["uvx", "--version"],
                capture_output=True,
                check=True,
                cwd=self.project_dir,
                timeout=TIMEOUT_SECONDS,
            )
            return ["uvx", "pip-audit"]
        except (subprocess.SubprocessError, OSError):
            return None

    def _issues_from_report(self, report: dict) -> list[Issue]:
        """Build an Issue per vulnerable dependency from a pip-audit JSON report."""
        issues = []
        for dependency in report.get("dependencies", []):
            vulns = dependency.get("vulns", [])
            if not vulns:
                continue

            name = dependency.get("name", "<unknown>")
            version = dependency.get("version", "<unknown>")
            vuln_ids = ", ".join(vuln.get("id", "") for vuln in vulns if vuln.get("id"))
            fix_versions = sorted(
                {fv for vuln in vulns for fv in vuln.get("fix_versions", [])}
            )

            description = f"{name} {version} has known vulnerabilities: {vuln_ids}"
            if fix_versions:
                description += f" (fix available: {', '.join(fix_versions)})"

            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=description,
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "pip-audit found known vulnerabilities in a locked "
                        "dependency. Bump the dependency to a fixed version "
                        "and re-lock (`uv lock --upgrade-package "
                        f"{name}`)."
                    ),
                )
            )
        return issues

    def _skip(self, message: str) -> CheckResult:
        """Build a CheckResult for a graceful no-op with a single info issue."""
        return CheckResult(
            check=self.name,
            passed=False,
            issues=[
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=message,
                    impact=Impact.INFORMATIONAL,
                )
            ],
        )
