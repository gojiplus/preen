"""Base classes for the check framework."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional


class Severity(Enum):
    """Severity levels for issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Fix:
    """Represents a proposed fix for an issue."""

    description: str
    diff: str
    apply: Callable[[], None]

    def preview(self) -> str:
        """Return a preview of the fix as a diff."""
        return self.diff


@dataclass
class Issue:
    """Represents an issue found by a check."""

    check: str
    severity: Severity
    description: str
    file: Optional[Path] = None
    line: Optional[int] = None
    proposed_fix: Optional[Fix] = None

    def __str__(self) -> str:
        location = ""
        if self.file:
            location = f" in {self.file}"
            if self.line:
                location += f":{self.line}"
        return f"[{self.severity.value}] {self.check}: {self.description}{location}"


@dataclass
class CheckResult:
    """Result of running a check."""

    check: str
    passed: bool
    issues: List[Issue] = field(default_factory=list)
    duration: float = 0.0

    @property
    def has_errors(self) -> bool:
        """Return True if any issues are errors."""
        return any(issue.severity == Severity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Return True if any issues are warnings."""
        return any(issue.severity == Severity.WARNING for issue in self.issues)


class Check(ABC):
    """Abstract base class for all checks."""

    def __init__(self, project_dir: Path):
        """Initialize the check.

        Args:
            project_dir: Path to the project directory.
        """
        self.project_dir = project_dir

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this check."""
        pass

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
        pass

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False
