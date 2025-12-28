"""Project structure validation check."""

from __future__ import annotations

from pathlib import Path

from ..config import PreenConfig
from .base import Check, CheckResult, Issue, Fix, Severity


class StructureCheck(Check):
    """Check project structure follows opinionated best practices."""

    @property
    def name(self) -> str:
        return "structure"

    @property
    def description(self) -> str:
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
        issues = []

        # Check if tests/ exists at root
        root_tests = self.project_dir / "tests"
        if not root_tests.exists():
            # Look for tests in src/ directory
            src_dir = self.project_dir / "src"
            if src_dir.exists():
                for package_dir in src_dir.iterdir():
                    if package_dir.is_dir() and (package_dir / "tests").exists():
                        issues.append(
                            Issue(
                                check=self.name,
                                severity=Severity.WARNING,
                                description=f"tests/ directory found inside package at {package_dir / 'tests'}",
                                file=package_dir / "tests",
                                proposed_fix=Fix(
                                    description="Move tests/ to project root",
                                    diff=f"Move {package_dir / 'tests'} -> {root_tests}",
                                    apply=lambda: self._move_tests_to_root(
                                        package_dir / "tests"
                                    ),
                                ),
                            )
                        )

        return issues

    def _check_examples_location(self) -> list[Issue]:
        """Check that examples/ is at project root, not inside package."""
        issues = []

        # Check if examples/ exists at root
        root_examples = self.project_dir / "examples"
        if not root_examples.exists():
            # Look for examples in src/ directory
            src_dir = self.project_dir / "src"
            if src_dir.exists():
                for package_dir in src_dir.iterdir():
                    if package_dir.is_dir() and (package_dir / "examples").exists():
                        issues.append(
                            Issue(
                                check=self.name,
                                severity=Severity.WARNING,
                                description=f"examples/ directory found inside package at {package_dir / 'examples'}",
                                file=package_dir / "examples",
                                proposed_fix=Fix(
                                    description="Move examples/ to project root",
                                    diff=f"Move {package_dir / 'examples'} -> {root_examples}",
                                    apply=lambda: self._move_examples_to_root(
                                        package_dir / "examples"
                                    ),
                                ),
                            )
                        )

        return issues

    def _check_src_layout(self) -> list[Issue]:
        """Check src/ layout is properly structured."""
        issues = []

        src_dir = self.project_dir / "src"
        if not src_dir.exists():
            # Check if package is at root (flat layout)
            pyproject_path = self.project_dir / "pyproject.toml"
            if pyproject_path.exists():
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore

                with pyproject_path.open("rb") as f:
                    data = tomllib.load(f)

                package_name = data.get("project", {}).get("name", "")
                if package_name and (self.project_dir / package_name).exists():
                    issues.append(
                        Issue(
                            check=self.name,
                            severity=Severity.INFO,
                            description="Package uses flat layout. Consider src/ layout for better isolation.",
                            file=Path(package_name),
                        )
                    )

        return issues

    def _check_common_antipatterns(self) -> list[Issue]:
        """Check for common project structure anti-patterns."""
        issues = []

        # Check for __pycache__ in git (should be in .gitignore)
        pycache_dirs = list(self.project_dir.rglob("__pycache__"))
        if pycache_dirs and (self.project_dir / ".git").exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description="__pycache__ directories found. Add '**/__pycache__/' to .gitignore",
                    proposed_fix=Fix(
                        description="Add __pycache__ to .gitignore",
                        diff="Add to .gitignore:\n**/__pycache__/\n*.pyc\n*.pyo\n*.pyd",
                        apply=lambda: self._update_gitignore(),
                    ),
                )
            )

        # Check for .pyc files
        pyc_files = list(self.project_dir.rglob("*.pyc"))
        if pyc_files:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=f"Found {len(pyc_files)} .pyc files. These should not be committed.",
                )
            )

        return issues

    def can_fix(self) -> bool:
        return True

    def _move_tests_to_root(self, src_tests_path: Path) -> None:
        """Move tests directory from src/ to root."""
        import shutil

        root_tests = self.project_dir / "tests"
        shutil.move(src_tests_path, root_tests)

    def _move_examples_to_root(self, src_examples_path: Path) -> None:
        """Move examples directory from src/ to root."""
        import shutil

        root_examples = self.project_dir / "examples"
        shutil.move(src_examples_path, root_examples)

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
