"""Citation file check."""

from __future__ import annotations

from pathlib import Path

from ..syncer import sync_project
from .base import Check, CheckResult, Issue, Fix, Severity


class CitationCheck(Check):
    """Check if CITATION.cff is in sync with pyproject.toml."""

    @property
    def name(self) -> str:
        return "citation"

    @property
    def description(self) -> str:
        return "Check if CITATION.cff is synced with pyproject.toml"

    def run(self) -> CheckResult:
        """Check if citation file needs updating."""
        issues = []

        # Run sync in check mode for citation only
        try:
            result = sync_project(
                self.project_dir,
                quiet=True,
                check=True,
                targets={"citation"},
            )
        except SystemExit:
            # sync_project exits with 1 if files would change
            result = sync_project(
                self.project_dir,
                quiet=True,
                check=False,
                targets={"citation"},
            )

            # Get the diff
            citation_path = self.project_dir / "CITATION.cff"
            old_content = ""
            if citation_path.exists():
                old_content = citation_path.read_text()

            new_content = result.get("updated", {}).get("CITATION.cff", "")

            def apply_fix():
                sync_project(
                    self.project_dir,
                    quiet=True,
                    check=False,
                    targets={"citation"},
                )

            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description="CITATION.cff is out of sync with pyproject.toml",
                    file=Path("CITATION.cff"),
                    proposed_fix=Fix(
                        description="Regenerate CITATION.cff from pyproject.toml",
                        diff=self._generate_diff(old_content, new_content),
                        apply=apply_fix,
                    ),
                )
            )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return True

    def _generate_diff(self, old: str, new: str) -> str:
        """Generate a simple diff between old and new content."""
        if not old:
            return f"Create new file:\n{new}"

        old_lines = old.split("\n")
        new_lines = new.split("\n")

        diff_lines = []
        for i, (old_line, new_line) in enumerate(zip(old_lines, new_lines)):
            if old_line != new_line:
                diff_lines.append(f"@@ Line {i + 1} @@")
                diff_lines.append(f"- {old_line}")
                diff_lines.append(f"+ {new_line}")

        # Handle different lengths
        if len(new_lines) > len(old_lines):
            diff_lines.append("@@ Added lines @@")
            for line in new_lines[len(old_lines) :]:
                diff_lines.append(f"+ {line}")
        elif len(old_lines) > len(new_lines):
            diff_lines.append("@@ Removed lines @@")
            for line in old_lines[len(new_lines) :]:
                diff_lines.append(f"- {line}")

        return "\n".join(diff_lines) if diff_lines else "No changes"
