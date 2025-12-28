"""CI matrix validation check."""

from __future__ import annotations

import yaml
from pathlib import Path

from ..config import PreenConfig
from ..syncer import _read_pyproject
from .base import Check, CheckResult, Issue, Fix, Severity


class CIMatrixCheck(Check):
    """Check if CI matrix covers all declared Python versions."""

    @property
    def name(self) -> str:
        return "ci-matrix"

    @property
    def description(self) -> str:
        return "Check if CI matrix tests all declared Python versions"

    def run(self) -> CheckResult:
        """Check CI matrix against declared Python versions."""
        issues = []

        # Load project configuration
        try:
            config = PreenConfig.from_pyproject(self.project_dir)
            pyproject = _read_pyproject(self.project_dir / "pyproject.toml")
            declared_versions = config.get_ci_python_versions(pyproject)
        except Exception as e:
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=f"Failed to read project metadata: {e}",
                    )
                ],
            )

        # Check if CI workflow exists
        ci_path = self.project_dir / ".github" / "workflows" / "ci.yml"
        if not ci_path.exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description="No CI workflow found at .github/workflows/ci.yml",
                    proposed_fix=Fix(
                        description="Generate CI workflow from pyproject.toml",
                        diff="Run: preen sync --only ci",
                        apply=self._fix_ci_workflow,
                    ),
                )
            )
            return CheckResult(
                check=self.name,
                passed=False,
                issues=issues,
            )

        # Parse CI workflow
        try:
            with ci_path.open("r", encoding="utf-8") as f:
                ci_content = yaml.safe_load(f)
        except Exception as e:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"Failed to parse CI workflow: {e}",
                )
            )
            return CheckResult(
                check=self.name,
                passed=False,
                issues=issues,
            )

        # Extract Python versions from CI matrix
        ci_versions = set()
        try:
            jobs = ci_content.get("jobs", {})
            test_job = jobs.get("test", {})
            strategy = test_job.get("strategy", {})
            matrix = strategy.get("matrix", {})
            python_versions = matrix.get("python-version", [])

            # Handle both list format and string format
            if isinstance(python_versions, list):
                ci_versions.update(python_versions)
            elif isinstance(python_versions, str):
                ci_versions.add(python_versions)
        except Exception:
            pass

        # Compare versions
        declared_set = set(declared_versions)
        missing_in_ci = declared_set - ci_versions
        extra_in_ci = ci_versions - declared_set

        if missing_in_ci:
            missing_versions = ", ".join(sorted(missing_in_ci))
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=f"CI matrix missing Python versions: {missing_versions}",
                    file=Path(".github/workflows/ci.yml"),
                    proposed_fix=Fix(
                        description="Update CI matrix to include all declared Python versions",
                        diff=f"Add Python versions to CI matrix: {missing_versions}",
                        apply=self._fix_ci_workflow,
                    ),
                )
            )

        if extra_in_ci and not missing_in_ci:
            # Only warn about extra versions if we're not missing any
            extra_versions = ", ".join(sorted(extra_in_ci))
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=f"CI matrix has extra Python versions not declared in classifiers: {extra_versions}",
                    file=Path(".github/workflows/ci.yml"),
                )
            )

        return CheckResult(
            check=self.name,
            passed=len([issue for issue in issues if issue.severity != Severity.INFO])
            == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return True

    def _fix_ci_workflow(self) -> None:
        """Regenerate CI workflow to fix matrix issues."""
        from ..syncer import sync_project

        sync_project(
            self.project_dir,
            quiet=True,
            check=False,
            targets={"ci"},
        )
