"""Test runner check."""

import subprocess

from .base import Check, CheckResult, Issue, Severity


class TestsCheck(Check):
    """Run pytest and report results."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "tests"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Run pytest test suite"

    def run(self) -> CheckResult:
        """Run pytest and report results."""
        issues = []

        # Run inside the project's uv environment when available
        if (self.project_dir / "uv.lock").exists():
            pytest_cmd = ["uv", "run", "pytest"]
        else:
            pytest_cmd = ["python3", "-m", "pytest"]

        missing = self.missing_tool([*pytest_cmd, "--version"], "pytest")
        if missing is not None:
            return missing

        # Run pytest
        result = subprocess.run(
            [*pytest_cmd, "--tb=short", "-q"],
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
                    description=(
                        "Tests failed: "
                        + (summary_line or "See test output for details")
                    ),
                )
            )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )
