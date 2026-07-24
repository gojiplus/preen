"""Project metadata checks: requires-python upper bound, py.typed marker.

Two independent findings live here because both are small, pyproject.toml-only
metadata checks that don't fit the scope of any existing check module.
"""

import re
import tomllib
from typing import Any

from ..adopt import detect_package_name
from .base import Check, CheckResult, Impact, Issue, Severity

# Any of these operators in a requires-python specifier caps the ceiling:
# <, <= directly bound it; ==, === pin an exact version; ~=X.Y is shorthand
# for ">=X.Y, ==X.*" which caps at the next major version.
_CAP_PATTERN = re.compile(r"~=|===|<=|==|<")


class MetadataCheck(Check):
    """Check requires-python has no upper cap and typed projects ship py.typed."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "metadata"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check requires-python has no upper cap and typed projects ship py.typed"

    def run(self) -> CheckResult:
        """Run the metadata checks.

        Returns:
            CheckResult containing any issues found.
        """
        if not (self.project_dir / "pyproject.toml").exists():
            # No pyproject at all is another check's problem; stay silent
            # like the sibling checks do.
            return CheckResult(check=self.name, passed=True, issues=[])

        data = self._load_pyproject()
        issues = self._check_requires_python(data) + self._check_py_typed(data)

        blocking = [i for i in issues if i.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)

    def _load_pyproject(self) -> dict[str, Any]:
        """Return the parsed pyproject.toml, or {} if missing/unparsable."""
        pyproject_path = self.project_dir / "pyproject.toml"
        if not pyproject_path.exists():
            return {}
        try:
            with pyproject_path.open("rb") as f:
                return tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return {}

    def _check_requires_python(self, data: dict[str, Any]) -> list[Issue]:
        """Flag an upper-bounded requires-python, or note if it's absent."""
        requires = data.get("project", {}).get("requires-python", "")
        if not requires:
            return [
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description="No requires-python declared in pyproject.toml",
                    impact=Impact.INFORMATIONAL,
                    explanation=(
                        "Declaring requires-python tells resolvers and tooling "
                        "which Python versions the project supports."
                    ),
                )
            ]
        if _CAP_PATTERN.search(requires):
            return [
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=f"requires-python '{requires}' has an upper bound",
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "Upper caps on requires-python cascade into resolvers "
                        "and block installs on future Pythons for no benefit "
                        "(sp-repo-review PP004)."
                    ),
                )
            ]
        return []

    def _check_py_typed(self, data: dict[str, Any]) -> list[Issue]:
        """Flag a typed project (pyright/mypy configured) missing py.typed."""
        tool = data.get("tool", {})
        if "pyright" not in tool and "mypy" not in tool:
            return []

        project_name = data.get("project", {}).get("name", "")
        if not project_name:
            return []

        package_name = detect_package_name(self.project_dir, project_name)
        for base in (self.project_dir / "src", self.project_dir):
            package_dir = base / package_name
            if not package_dir.is_dir():
                continue
            if (package_dir / "py.typed").exists():
                return []
            return [
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"Project uses type checking but "
                        f"{package_dir.relative_to(self.project_dir)}/py.typed "
                        "is missing"
                    ),
                    file=package_dir.relative_to(self.project_dir),
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "PEP 561 requires a py.typed marker for type checkers "
                        "to trust the package's inline types."
                    ),
                )
            ]
        return []

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False
