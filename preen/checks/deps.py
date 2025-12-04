"""Dependencies check using deptry."""

from __future__ import annotations

import subprocess

from .base import Check, CheckResult, Issue, Fix, Severity


class DepsCheck(Check):
    """Check for unused/missing dependencies using deptry."""

    @property
    def name(self) -> str:
        return "deps"

    @property
    def description(self) -> str:
        return "Check for unused and missing dependencies with deptry"

    def run(self) -> CheckResult:
        """Run deptry to check dependencies."""
        issues = []

        # Check if deptry is available
        try:
            subprocess.run(
                ["deptry", "--version"],
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
                        description="deptry is not installed. Install with: pip install deptry",
                    )
                ],
            )

        # Run deptry
        result = subprocess.run(
            ["deptry", ".", "--json"],
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        if result.returncode != 0:
            # Parse JSON output if available
            import json

            try:
                output_data = json.loads(result.stdout) if result.stdout else {}
                missing = output_data.get("missing", [])
                unused = output_data.get("unused", [])

                if missing:
                    missing_deps = ", ".join(missing)
                    issues.append(
                        Issue(
                            check=self.name,
                            severity=Severity.ERROR,
                            description=f"Missing dependencies: {missing_deps}",
                            proposed_fix=Fix(
                                description="Add missing dependencies to pyproject.toml",
                                diff=f"Add to [project.dependencies]:\n{chr(10).join(missing)}",
                                apply=lambda: None,  # Manual fix required
                            ),
                        )
                    )

                if unused:
                    unused_deps = ", ".join(unused)
                    issues.append(
                        Issue(
                            check=self.name,
                            severity=Severity.WARNING,
                            description=f"Unused dependencies: {unused_deps}",
                            proposed_fix=Fix(
                                description="Remove unused dependencies from pyproject.toml",
                                diff=f"Remove from [project.dependencies]:\n{chr(10).join(unused)}",
                                apply=lambda: None,  # Manual fix required
                            ),
                        )
                    )
            except json.JSONDecodeError:
                # Fall back to parsing stderr for general error message
                error_msg = (
                    result.stderr.strip()
                    if result.stderr
                    else "Unknown dependency issues"
                )
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=f"Dependency check failed: {error_msg}",
                    )
                )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return False  # Dependencies require manual intervention
