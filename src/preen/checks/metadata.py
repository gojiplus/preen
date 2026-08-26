"""Project metadata checks: build backend, Python support, and typing marker.

These findings are small, pyproject.toml-only metadata checks that don't fit the
scope of any existing check module.
"""

import re
import tomllib
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from validate_pyproject import api as validate_api
from validate_pyproject import errors as validate_errors

from ..adopt import UV_BUILD_REQUIREMENT, detect_package_name
from .base import Check, CheckResult, Impact, Issue, Severity

# Any of these operators in a requires-python specifier caps the ceiling:
# <, <= directly bound it; ==, === pin an exact version; ~=X.Y is shorthand
# for ">=X.Y, ==X.*" which caps at the next major version.
_CAP_PATTERN = re.compile(r"~=|===|<=|==|<")


def _same_requirement(declared: Any, expected: str) -> bool:
    """Report whether a `requires` list pins exactly the expected requirement.

    Compared as a parsed specifier rather than as a string. ``<0.13`` and
    ``<0.13.0`` admit precisely the same versions, and gojiplus/uijudge-bench
    writes the second -- so a string comparison told a repo with a correct,
    current build backend to migrate it.

    Args:
        declared: The ``build-system.requires`` value.
        expected: The requirement the standard specifies.

    Returns:
        True when the list holds one requirement equivalent to `expected`.
    """
    if not isinstance(declared, list) or len(declared) != 1:
        return False
    try:
        found = Requirement(str(declared[0]))
        wanted = Requirement(expected)
    except InvalidRequirement:
        return False
    return (
        found.name == wanted.name
        and set(found.specifier) == set(wanted.specifier)
        and found.extras == wanted.extras
        and found.marker is None
        and wanted.marker is None
    )


class MetadataCheck(Check):
    """Check build, Python, and typing metadata against the fleet standard."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "metadata"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check build, Python, and typing metadata"

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
        # Reported alongside the semantic findings rather than instead of them:
        # the checks below read by `.get()` and degrade to "absent", so a schema
        # violation should not hide a build-system that is also wrong.
        issues = (
            self._check_schema()
            + self._check_build_system(data)
            + self._check_requires_python(data)
            + self._check_py_typed(data)
        )

        blocking = [i for i in issues if i.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)

    def _check_schema(self) -> list[Issue]:
        """Validate pyproject.toml against the PyPA schemas.

        Every other check reads this file by ``.get()``, which cannot tell a
        key that is absent from one that is misspelled or the wrong type. A
        schema pass names the difference before anything reasons about it.

        Returns:
            At most one issue, naming the first schema violation.
        """
        pyproject_path = self.project_dir / "pyproject.toml"
        try:
            with pyproject_path.open("rb") as handle:
                data = tomllib.load(handle)
        except OSError:
            return []
        except tomllib.TOMLDecodeError as exc:
            return [
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"pyproject.toml is not valid TOML: {exc}",
                    file=Path("pyproject.toml"),
                    impact=Impact.CRITICAL,
                    explanation="No tool in the standard can read the project.",
                )
            ]

        try:
            validate_api.Validator()(data)
        except validate_errors.ValidationError as exc:
            return [
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"pyproject.toml fails its schema: {exc.summary}",
                    file=Path("pyproject.toml"),
                    impact=Impact.CRITICAL,
                    explanation=(
                        "Validated with validate-pyproject against PyPA's own "
                        "schemas. Build backends and installers read this file "
                        "the same way, so the error surfaces at publish time "
                        "if not here."
                    ),
                )
            ]
        return []

    def _check_build_system(self, data: dict[str, Any]) -> list[Issue]:
        """Flag an existing build system that differs from the fleet standard."""
        if "build-system" not in data:
            return []
        build = data["build-system"]
        if (
            isinstance(build, dict)
            and set(build) == {"requires", "build-backend"}
            and build.get("build-backend") == "uv_build"
            and _same_requirement(build.get("requires"), UV_BUILD_REQUIREMENT)
        ):
            return []
        return [
            Issue(
                check=self.name,
                severity=Severity.WARNING,
                description=(
                    "build-system must use "
                    f'{UV_BUILD_REQUIREMENT!r} with backend "uv_build"'
                ),
                file=Path("pyproject.toml"),
                impact=Impact.IMPORTANT,
                explanation=(
                    "The py-canon fleet uses one current uv_build requirement so "
                    "backend upgrades are deliberate and stale build shims cannot "
                    "linger unnoticed. Run preen adopt --release-migration to migrate."
                ),
            )
        ]

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
