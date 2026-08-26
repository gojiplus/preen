"""Base classes for the check framework."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(Enum):
    """Severity levels for issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Impact(Enum):
    """Impact classification for release workflow decision making."""

    CRITICAL = "critical"  # Must fix - blocks release (security, broken builds)
    IMPORTANT = "important"  # Should fix but can override (style, deprecations)
    INFORMATIONAL = "info"  # Nice to fix (suggestions, optimizations)


@dataclass
class Fix:
    """Represents a proposed fix for an issue."""

    description: str
    diff: str
    apply: Callable[[], None]
    #: Refuse to apply this fix non-interactively. For fixes that rewrite
    #: content a tool cannot judge — a misspelling inside a data fixture may
    #: be a real proper noun — a human has to look at the diff first.
    requires_confirmation: bool = False

    def preview(self) -> str:
        """Return a preview of the fix as a diff."""
        return self.diff


@dataclass
class Issue:
    """Represents an issue found by a check."""

    check: str
    severity: Severity
    description: str
    file: Path | None = None
    line: int | None = None
    proposed_fix: Fix | None = None
    impact: Impact = Impact.IMPORTANT  # Default to important (can override)
    explanation: str = ""  # Why this issue matters
    override_question: str = ""  # Custom question for override prompt

    def __str__(self) -> str:
        """Return a human-readable one-line summary of the issue."""
        location = ""
        if self.file:
            location = f" in {self.file}"
            if self.line:
                location += f":{self.line}"
        return f"[{self.severity.value}] {self.check}: {self.description}{location}"

    def get_impact_symbol(self) -> str:
        """Get emoji symbol for impact level."""
        symbols = {
            Impact.CRITICAL: "🚫",
            Impact.IMPORTANT: "⚠️",
            Impact.INFORMATIONAL: "(i)",
        }
        return symbols[self.impact]

    def is_blocking(self) -> bool:
        """Return True if this issue should block release by default."""
        return self.impact == Impact.CRITICAL

    def can_override(self) -> bool:
        """Return True if this issue can be overridden in interactive mode."""
        return self.impact in [Impact.IMPORTANT, Impact.INFORMATIONAL]


@dataclass
class CheckResult:
    """Result of running a check."""

    check: str
    passed: bool
    issues: list[Issue] = field(default_factory=list)
    duration: float = 0.0

    @property
    def has_errors(self) -> bool:
        """Return True if any issues are errors."""
        return any(issue.severity == Severity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Return True if any issues are warnings."""
        return any(issue.severity == Severity.WARNING for issue in self.issues)

    @property
    def has_blocking_issues(self) -> bool:
        """Return True if any issues are blocking (critical impact)."""
        return any(issue.is_blocking() for issue in self.issues)

    @property
    def has_overridable_issues(self) -> bool:
        """Return True if any issues can be overridden."""
        return any(issue.can_override() for issue in self.issues)

    def get_issues_by_impact(self, impact: Impact) -> list[Issue]:
        """Get all issues with a specific impact level."""
        return [issue for issue in self.issues if issue.impact == impact]


class Check(ABC):
    """Abstract base class for all checks."""

    #: Directories never worth checking, regardless of repo config.
    DEFAULT_EXCLUDES = frozenset(
        {
            ".git",
            ".tox",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            "dist",
            "build",
        }
    )

    def __init__(self, project_dir: Path):
        """Initialize the check.

        Args:
            project_dir: Path to the project directory.
        """
        self.project_dir = project_dir
        self._lint_excluded_dirs: frozenset[str] | None = None

    def excluded_dirs(self) -> frozenset[str]:
        """Directory names no check should ever look at.

        Caches, build output and virtualenvs -- nothing a repo can configure.

        Returns:
            The default exclusion set.
        """
        return self.DEFAULT_EXCLUDES

    def lint_excluded_dirs(self) -> frozenset[str]:
        """Directory names a *scanner* should skip.

        Adds the repo's own ``[tool.ruff]`` ``exclude``/``extend-exclude``
        entries to :meth:`excluded_dirs`, for checks where "don't lint this"
        genuinely means "don't read this" -- spell checking, link scanning,
        import graphs.

        Deliberately not the default. Folding these into every check let a
        lint-scope setting switch off a packaging one: ``extend-exclude =
        ["data"]`` made ``indicate/data/**`` invisible to ``runtime-assets``,
        so the wheel-contents check passed on a tree full of ``.safetensors``
        (issue #59).

        Returns:
            The default exclusion set plus ruff's directory-name excludes.
        """
        if self._lint_excluded_dirs is None:
            names = set(self.DEFAULT_EXCLUDES)
            pyproject = self.project_dir / "pyproject.toml"
            if pyproject.exists():
                import tomllib

                try:
                    ruff = (
                        tomllib.loads(pyproject.read_text())
                        .get("tool", {})
                        .get("ruff", {})
                    )
                except (tomllib.TOMLDecodeError, OSError):
                    ruff = {}
                for key in ("exclude", "extend-exclude"):
                    for entry in ruff.get(key, []):
                        # Only plain directory names scope cleanly here
                        if "*" not in entry and "/" not in entry:
                            names.add(entry)
            self._lint_excluded_dirs = frozenset(names)
        return self._lint_excluded_dirs

    def is_excluded(self, path: Path) -> bool:
        """Return True if a project-relative path lies under an excluded dir.

        Args:
            path: Path to test. Must be project-relative: an absolute path
                lets a component of the user's checkout location (``build``,
                ``dist``, ``venv``) match and silently drop the file.

        Returns:
            True when any component is an excluded directory name.
        """
        return any(part in self.excluded_dirs() for part in path.parts)

    def is_lint_excluded(self, path: Path) -> bool:
        """Return True if a project-relative path is out of scope for scanning.

        Args:
            path: Project-relative path to test.

        Returns:
            True when any component is in :meth:`lint_excluded_dirs`.
        """
        return any(part in self.lint_excluded_dirs() for part in path.parts)

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this check."""

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return ""

    @abstractmethod
    def run(self) -> CheckResult:
        """Run the check and return the result.

        Returns:
            CheckResult containing any issues found.
        """

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False
