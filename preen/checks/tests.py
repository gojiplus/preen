"""Test runner check."""

from __future__ import annotations

import subprocess

from .base import Check, CheckResult, Issue, Severity


class TestsCheck(Check):
    """Run pytest and report results."""

    @property
    def name(self) -> str:
        return "tests"

    @property
    def description(self) -> str:
        return "Run pytest test suite"

    def run(self) -> CheckResult:
        """Run pytest and report results."""
        issues = []

        # Check if pytest is available
        try:
            subprocess.run(
                ["python3", "-m", "pytest", "--version"],
                capture_output=True,
                check=True,
                cwd=self.project_dir,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description="pytest is not installed. Install with: pip install pytest",
                    )
                ],
            )

        # Run pytest
        result = subprocess.run(
            ["python3", "-m", "pytest", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        if result.returncode != 0:
            # Parse output for number of failures
            output_lines = result.stdout.split("\n")
            summary_line = ""
            for line in output_lines:
                if "failed" in line or "error" in line:
                    summary_line = line.strip()
                    break

            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"Tests failed: {summary_line if summary_line else 'See test output for details'}",
                )
            )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )
