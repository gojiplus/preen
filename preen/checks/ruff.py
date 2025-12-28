"""Ruff linting and formatting check."""

from __future__ import annotations

import subprocess

from .base import Check, CheckResult, Issue, Fix, Severity, Impact


class RuffCheck(Check):
    """Check for linting and formatting issues using ruff."""

    @property
    def name(self) -> str:
        return "ruff"

    @property
    def description(self) -> str:
        return "Check code linting and formatting with ruff"

    def run(self) -> CheckResult:
        """Run ruff check and ruff format."""
        issues = []

        # Check if ruff is available
        try:
            subprocess.run(
                ["ruff", "--version"],
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
                        description="ruff is not installed. Install with: pip install ruff",
                    )
                ],
            )

        # Run ruff check
        lint_result = subprocess.run(
            ["ruff", "check", "--quiet"],
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        if lint_result.returncode != 0:
            # Try to get fixable issues
            fix_result = subprocess.run(
                ["ruff", "check", "--quiet", "--fix", "--diff"],
                capture_output=True,
                text=True,
                cwd=self.project_dir,
            )

            def apply_lint_fix():
                subprocess.run(
                    ["ruff", "check", "--fix"],
                    cwd=self.project_dir,
                    check=False,
                )

            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=f"Linting issues found ({lint_result.stdout.count(chr(10))} problems)",
                    impact=Impact.IMPORTANT,
                    explanation="Linting issues can indicate potential bugs, code style problems, or maintainability concerns. While not blocking, they should be addressed for code quality.",
                    override_question="Continue with release despite linting issues?",
                    proposed_fix=Fix(
                        description="Apply ruff automatic fixes",
                        diff=fix_result.stdout
                        if fix_result.stdout
                        else "No automatic fixes available",
                        apply=apply_lint_fix,
                    )
                    if fix_result.stdout
                    else None,
                )
            )

        # Run ruff format check
        format_result = subprocess.run(
            ["ruff", "format", "--check", "--quiet"],
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        if format_result.returncode != 0:
            # Get formatting diff
            diff_result = subprocess.run(
                ["ruff", "format", "--diff"],
                capture_output=True,
                text=True,
                cwd=self.project_dir,
            )

            def apply_format_fix():
                subprocess.run(
                    ["ruff", "format"],
                    cwd=self.project_dir,
                    check=False,
                )

            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description="Code formatting issues found",
                    impact=Impact.IMPORTANT,
                    explanation="Consistent code formatting improves readability and reduces diff noise in version control. Consider fixing before release.",
                    override_question="Continue with release despite formatting issues?",
                    proposed_fix=Fix(
                        description="Apply ruff formatting",
                        diff=diff_result.stdout,
                        apply=apply_format_fix,
                    ),
                )
            )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return True
