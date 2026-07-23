"""Version hardcoding detection check.

Under the fleet standard the git tag is the version (uv-dynamic-versioning),
so no version string belongs in source. This check flags literal
``__version__ = "..."`` assignments and, for repos that still declare a static
``project.version``, copies of that string sprinkled through the tree.
"""

import re
import tomllib
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

_LITERAL_VERSION = re.compile(
    r"""^\s*__version__\s*=\s*["']\d+[^"']*["']""", re.MULTILINE
)

EXCLUDE_PARTS = {
    ".git",
    "__pycache__",
    ".venv",
    ".env",
    "build",
    "dist",
    "node_modules",
    ".eggs",
}


class VersionCheck(Check):
    """Check for hardcoded version strings outside pyproject.toml."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "version"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check for hardcoded version strings"

    def run(self) -> CheckResult:
        """Run the version hardcoding check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []

        static_version = self._static_pyproject_version()
        issues.extend(self._check_literal_dunder_versions())
        if static_version:
            issues.extend(self._check_static_version_copies(static_version))

        return CheckResult(check=self.name, passed=not issues, issues=issues)

    def _iter_files(self, patterns: tuple[str, ...]) -> list[Path]:
        """Collect files matching patterns, excluding vendored/build dirs.

        Args:
            patterns: Glob patterns relative to the project directory.

        Returns:
            Matching file paths.
        """
        files: set[Path] = set()
        for pattern in patterns:
            files.update(self.project_dir.glob(pattern))
        return [
            f
            for f in sorted(files)
            if f.is_file()
            and not any(part in EXCLUDE_PARTS for part in f.parts)
            and not f.name.endswith(".egg-info")
            and ".egg-info" not in f.parts[:-1]
        ]

    def _static_pyproject_version(self) -> str | None:
        """Return the static project.version, or None when dynamic/absent."""
        pyproject_path = self.project_dir / "pyproject.toml"
        if not pyproject_path.exists():
            return None
        try:
            with pyproject_path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return None
        return data.get("project", {}).get("version")

    def _check_literal_dunder_versions(self) -> list[Issue]:
        """Flag literal ``__version__ = "x.y.z"`` assignments in Python files."""
        issues: list[Issue] = []
        for file_path in self._iter_files(("src/**/*.py", "*.py", "**/__init__.py")):
            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in _LITERAL_VERSION.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description="Literal __version__ assignment found",
                        file=file_path.relative_to(self.project_dir),
                        line=line_num,
                        impact=Impact.IMPORTANT,
                        explanation=(
                            "The standard derives the version from the git tag; "
                            "use importlib.metadata.version() instead."
                        ),
                    )
                )
        return issues

    def _check_static_version_copies(self, version: str) -> list[Issue]:
        """Flag copies of a static project.version outside pyproject.toml.

        Args:
            version: The static version string declared in pyproject.toml.

        Returns:
            Issues for each hardcoded copy found.
        """
        issues: list[Issue] = []
        pattern = re.compile(
            rf"""(?:version\s*=\s*|__version__\s*=\s*)["']{re.escape(version)}["']"""
        )
        for file_path in self._iter_files(("**/*.py", "**/*.yml", "**/*.yaml")):
            if file_path.name == "pyproject.toml":
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                line = content.split("\n")[line_num - 1].strip()
                if line.startswith("#") or "importlib" in line:
                    continue
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=f"Hardcoded version '{version}' found",
                        file=file_path.relative_to(self.project_dir),
                        line=line_num,
                        impact=Impact.IMPORTANT,
                        explanation=(
                            "Version strings outside pyproject.toml drift; "
                            "derive them from package metadata."
                        ),
                    )
                )
        return issues

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False
