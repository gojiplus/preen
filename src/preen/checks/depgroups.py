"""PEP 735 `depgroups` check.

Flags dev-type dependencies (test/lint/docs/etc.) that live in
`[project.optional-dependencies]` instead of `[dependency-groups]`, and a
missing or dev-less `[dependency-groups]` section.
"""

import re
import tomllib
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

# Extra names that indicate dev-type dependencies rather than a real
# optional feature. Matched case-insensitively (and normalized like PEP 685
# extra names) against [project.optional-dependencies] keys.
DEV_TYPE_EXTRAS = frozenset(
    {
        "dev",
        "develop",
        "development",
        "test",
        "tests",
        "testing",
        "docs",
        "doc",
        "documentation",
        "lint",
        "linting",
        "typecheck",
        "typing",
        "quality",
        "ci",
    }
)

_NORMALIZE_RE = re.compile(r"[-_.]+")


def _normalize(name: str) -> str:
    """Normalize an extra/group name for case- and separator-insensitive comparison."""
    return _NORMALIZE_RE.sub("-", name.lower())


class DepgroupsCheck(Check):
    """Check dev-type dependencies live in `[dependency-groups]` (PEP 735)."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "depgroups"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check PEP 735 dependency-groups usage for dev/test/docs deps"

    def run(self) -> CheckResult:
        """Run the depgroups check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        pyproject_path = self.project_dir / "pyproject.toml"
        if not pyproject_path.exists():
            return CheckResult(check=self.name, passed=True, issues=issues)

        try:
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            # Malformed TOML is another check's concern.
            return CheckResult(check=self.name, passed=True, issues=issues)

        has_dependency_groups = "dependency-groups" in data
        dependency_groups = data.get("dependency-groups", {})
        if not isinstance(dependency_groups, dict):
            dependency_groups = {}
        group_names = {_normalize(name) for name in dependency_groups}

        if not has_dependency_groups:
            issues.append(self._missing_dependency_groups_issue(pyproject_path))
        elif "dev" not in group_names:
            issues.append(self._missing_dev_group_issue(pyproject_path))

        project = data.get("project", {})
        optional_deps = project.get("optional-dependencies", {})
        if not isinstance(optional_deps, dict):
            optional_deps = {}

        for extra_name in optional_deps:
            normalized_extra = _normalize(extra_name)
            if normalized_extra in DEV_TYPE_EXTRAS:
                issues.append(self._dev_type_extra_issue(extra_name, pyproject_path))
            if normalized_extra in group_names:
                issues.append(self._duplicate_group_issue(extra_name, pyproject_path))

        return CheckResult(check=self.name, passed=not issues, issues=issues)

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False

    # -- finding builders --------------------------------------------------

    def _missing_dependency_groups_issue(self, pyproject_path: Path) -> Issue:
        """Build the issue for a pyproject.toml with no `[dependency-groups]`."""
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description="pyproject.toml has no [dependency-groups] section",
            file=pyproject_path.relative_to(self.project_dir),
            impact=Impact.IMPORTANT,
            explanation=(
                "PEP 735 dependency-groups are the standard for dev/test/docs "
                "dependencies (pip >=25.1 --group, uv, RTD all support them)."
            ),
        )

    def _missing_dev_group_issue(self, pyproject_path: Path) -> Issue:
        """Build the issue for `[dependency-groups]` with no `dev` group."""
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description="[dependency-groups] has no `dev` group",
            file=pyproject_path.relative_to(self.project_dir),
            impact=Impact.IMPORTANT,
            explanation=(
                "The fleet standard's entry point is `uv sync --all-groups`; "
                "a `dev` group is the canonical umbrella."
            ),
        )

    def _dev_type_extra_issue(self, extra_name: str, pyproject_path: Path) -> Issue:
        """Build the issue for a dev-type extra in `[project.optional-dependencies]`."""
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description=(
                f"[project.optional-dependencies] extra {extra_name!r} looks "
                "like a dev-type dependency, not an optional feature"
            ),
            file=pyproject_path.relative_to(self.project_dir),
            impact=Impact.IMPORTANT,
            explanation=(
                "Dev/test/docs/lint dependencies belong in [dependency-groups] "
                "(PEP 735), not [project.optional-dependencies], which is for "
                "installable end-user features. Move it manually or with "
                "`uv add --group`."
            ),
        )

    def _duplicate_group_issue(self, extra_name: str, pyproject_path: Path) -> Issue:
        """Build the issue for a name present in both extras and dependency-groups."""
        return Issue(
            check=self.name,
            severity=Severity.INFO,
            description=(
                f"{extra_name!r} is defined in both [project.optional-dependencies] "
                "and [dependency-groups]"
            ),
            file=pyproject_path.relative_to(self.project_dir),
            impact=Impact.INFORMATIONAL,
            explanation=(
                "Having the same name in both sections is redundant; drop the "
                "[project.optional-dependencies] entry and keep the "
                "[dependency-groups] one."
            ),
        )
