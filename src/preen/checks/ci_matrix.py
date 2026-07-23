"""CI workflow validation: canon shim, or a matrix covering the Python floor."""

import re
import tomllib
from pathlib import Path

import yaml

from .base import Check, CheckResult, Impact, Issue, Severity

CANON_SHIM_MARKER = "gojiplus/py-canon/.github/workflows/reusable-ci.yml@"

_FLOOR = re.compile(r">=\s*(\d+)\.(\d+)")


class CIMatrixCheck(Check):
    """Check that ci.yml is a py-canon shim or covers the requires-python floor."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "ci-matrix"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check ci.yml is a canon shim or its matrix covers the Python floor"

    def run(self) -> CheckResult:
        """Run the CI workflow check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        ci_path = self.project_dir / ".github" / "workflows" / "ci.yml"

        if not ci_path.exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description="No CI workflow found at .github/workflows/ci.yml",
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "Every fleet repo calls the reusable py-canon CI "
                        "workflow; run 'preen adopt' to add the shim."
                    ),
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        content = ci_path.read_text(encoding="utf-8")

        # A canon shim delegates the matrix to the reusable workflow.
        if CANON_SHIM_MARKER in content:
            return CheckResult(check=self.name, passed=True, issues=[])

        floor = self._requires_python_floor()
        if floor is None:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=(
                        "ci.yml is not a py-canon shim and no requires-python "
                        "floor could be determined"
                    ),
                    impact=Impact.INFORMATIONAL,
                )
            )
            return CheckResult(check=self.name, passed=True, issues=issues)

        ci_versions = self._matrix_python_versions(ci_path, issues)
        if issues and any(i.severity == Severity.ERROR for i in issues):
            return CheckResult(check=self.name, passed=False, issues=issues)

        if floor not in ci_versions:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"ci.yml is not a py-canon shim and its matrix "
                        f"{sorted(ci_versions) or '(empty)'} does not test the "
                        f"requires-python floor {floor}"
                    ),
                    file=Path(".github/workflows/ci.yml"),
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "The standard tests the floor and the ceiling; either "
                        "adopt the canon shim ('preen adopt') or add the floor "
                        "to the matrix."
                    ),
                )
            )

        blocking = [i for i in issues if i.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)

    def _requires_python_floor(self) -> str | None:
        """Return the requires-python floor (e.g. '3.11'), or None if unknown."""
        pyproject_path = self.project_dir / "pyproject.toml"
        if not pyproject_path.exists():
            return None
        try:
            with pyproject_path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return None
        requires = data.get("project", {}).get("requires-python", "")
        match = _FLOOR.search(requires)
        if not match:
            return None
        return f"{match.group(1)}.{match.group(2)}"

    def _matrix_python_versions(self, ci_path: Path, issues: list[Issue]) -> set[str]:
        """Extract all python-version matrix entries from the workflow.

        Args:
            ci_path: Path to the ci.yml workflow file.
            issues: Issue list to append parse errors to.

        Returns:
            Set of python versions found in any job's matrix.
        """
        versions: set[str] = set()
        try:
            with ci_path.open("r", encoding="utf-8") as f:
                workflow = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"Failed to parse CI workflow: {exc}",
                    impact=Impact.CRITICAL,
                )
            )
            return versions

        for job in (workflow.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            matrix = ((job.get("strategy") or {}).get("matrix")) or {}
            raw = matrix.get("python-version", [])
            if isinstance(raw, list):
                versions.update(str(v) for v in raw)
            elif raw:
                versions.add(str(raw))
        return versions
