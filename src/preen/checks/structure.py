"""Project structure validation check."""

import fnmatch
import shutil
import subprocess
import tomllib
from pathlib import Path

from ..config import PreenConfig
from .base import Check, CheckResult, Fix, Impact, Issue, Severity


def _move(src: Path, dest: Path) -> None:
    """Move a directory, discarding shutil.move's return value.

    Args:
        src: Directory to move.
        dest: Destination path.
    """
    shutil.move(src, dest)


class StructureCheck(Check):
    """Check project structure follows opinionated best practices."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "structure"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check project structure follows best practices"

    def run(self) -> CheckResult:
        """Check project structure."""
        issues = []
        config = PreenConfig.from_pyproject(self.project_dir)

        # Check for tests/ at root (not in src/)
        if config.tests_at_root:
            issues.extend(self._check_tests_location())

        # Check for examples/ at root (not in src/)
        if config.examples_at_root:
            issues.extend(self._check_examples_location())

        # Check src layout if configured
        if config.src_layout:
            issues.extend(self._check_src_layout())

        # Check for common anti-patterns
        issues.extend(self._check_common_antipatterns())

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def _check_tests_location(self) -> list[Issue]:
        """Check that tests/ is at project root, not inside package."""
        return self._check_dir_at_root("tests")

    def _check_examples_location(self) -> list[Issue]:
        """Check that examples/ is at project root, not inside package."""
        return self._check_dir_at_root("examples")

    def _check_dir_at_root(self, name: str) -> list[Issue]:
        """Flag a `name`/ directory nested under src/ instead of at the root.

        Args:
            name: Directory name, e.g. ``tests``.

        Returns:
            One issue per package that nests the directory.
        """
        root = self.project_dir / name
        src_dir = self.project_dir / "src"
        if root.exists() or not src_dir.exists():
            return []
        return [
            self._nested_dir_issue(package_dir / name, root, name)
            for package_dir in src_dir.iterdir()
            if package_dir.is_dir() and (package_dir / name).exists()
        ]

    def _nested_dir_issue(self, nested: Path, root: Path, name: str) -> Issue:
        """Build the issue for a directory that belongs at the repo root.

        Args:
            nested: The misplaced directory under src/.
            root: Where it belongs.
            name: Directory name, for the message.

        Returns:
            The issue, carrying a fix that moves the directory.
        """
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description=f"{name}/ directory found inside package at {nested}",
            file=nested,
            proposed_fix=Fix(
                description=f"Move {name}/ to project root",
                diff=f"Move {nested} -> {root}",
                apply=lambda: _move(nested, root),
            ),
        )

    def _check_src_layout(self) -> list[Issue]:
        """Check src/ layout is properly structured."""
        issues = []

        src_dir = self.project_dir / "src"
        if not src_dir.exists():
            # Check if package is at root (flat layout)
            pyproject_path = self.project_dir / "pyproject.toml"
            if pyproject_path.exists():
                with pyproject_path.open("rb") as f:
                    data = tomllib.load(f)

                package_name = data.get("project", {}).get("name", "")
                if package_name and (self.project_dir / package_name).exists():
                    issues.append(
                        Issue(
                            check=self.name,
                            severity=Severity.INFO,
                            description=(
                                "Package uses flat layout. Consider src/ "
                                "layout for better isolation."
                            ),
                            file=Path(package_name),
                            impact=Impact.INFORMATIONAL,
                        )
                    )

        return issues

    def _tracked_matches(self, pattern: str) -> list[Path]:
        """Git-tracked paths whose final component matches pattern.

        Committed cache files are the real antipattern; on-disk but
        git-ignored ones are fine. Falls back to a filesystem scan
        outside a git repo.
        """
        if (self.project_dir / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "ls-files", "-z"],
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=self.project_dir,
                )
            except (subprocess.SubprocessError, FileNotFoundError):
                return []
            return [
                Path(p)
                for p in result.stdout.split("\0")
                if p and any(fnmatch.fnmatch(part, pattern) for part in Path(p).parts)
            ]
        return [
            p
            for p in self.project_dir.rglob(pattern)
            if not self.is_excluded(p.relative_to(self.project_dir))
        ]

    def _check_common_antipatterns(self) -> list[Issue]:
        """Check for common project structure anti-patterns."""
        issues = []

        # Check for __pycache__ in git (should be in .gitignore)
        pycache_dirs = self._tracked_matches("__pycache__")
        if pycache_dirs and (self.project_dir / ".git").exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        "__pycache__ directories found. Add "
                        "'**/__pycache__/' to .gitignore"
                    ),
                    proposed_fix=Fix(
                        description="Add __pycache__ to .gitignore",
                        diff="Add to .gitignore:\n**/__pycache__/\n*.pyc\n*.pyo\n*.pyd",
                        apply=lambda: self._update_gitignore(),
                    ),
                )
            )

        # Check for .pyc files
        pyc_files = self._tracked_matches("*.pyc")
        if pyc_files:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"Found {len(pyc_files)} .pyc files. "
                        "These should not be committed."
                    ),
                )
            )

        return issues

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return True

    def _update_gitignore(self) -> None:
        """Update .gitignore to exclude Python artifacts."""
        gitignore_path = self.project_dir / ".gitignore"

        python_ignores = [
            "# Python artifacts",
            "**/__pycache__/",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".Python",
            "build/",
            "develop-eggs/",
            "dist/",
            "downloads/",
            "eggs/",
            ".eggs/",
            "lib/",
            "lib64/",
            "parts/",
            "sdist/",
            "var/",
            "wheels/",
            "*.egg-info/",
            ".installed.cfg",
            "*.egg",
            "",
        ]

        if gitignore_path.exists():
            content = gitignore_path.read_text()
            if "__pycache__" not in content:
                with gitignore_path.open("a") as f:
                    f.write("\n" + "\n".join(python_ignores))
        else:
            gitignore_path.write_text("\n".join(python_ignores) + "\n")
