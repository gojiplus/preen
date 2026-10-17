"""Find copied blocks of package code with pylint's duplicate-code detector.

ruff is the standard's only linter, and ruff has no duplicate-code rule, so a
block pasted into a second module passed every check. Copies drift: the fix
lands in one and not the other. In rank-preserving-calibration, three
copies of one isotonic regression diverged until one mishandled weights.

pylint's similarity checker (R0801) is the established tool for this, so this
check runs it rather than reimplementing it, on package code only: tests,
docs, examples and benchmarks repeat setup by design. The threshold is 12
matching lines, ignoring imports, docstrings, comments and signatures; at 6,
half the fleet flagged boilerplate, and at 12 every hit sampled was a real
copy.

Suppress a deliberate duplicate with pylint's own marker,
``# pylint: disable=duplicate-code``, in one of the two blocks.
"""

import json
import re
import subprocess
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

MIN_SIMILARITY_LINES = 12

NOT_PACKAGE_DIRS = frozenset({"tests", "test", "docs", "examples", "benchmarks"})

_BLOCK = re.compile(r"^==(?P<module>[\w.]+):\[(?P<start>\d+):(?P<end>\d+)\]$")


class DuplicateCodeCheck(Check):
    """Report blocks of package code duplicated across modules."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "duplicate-code"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Find copied blocks of package code (pylint duplicate-code)"

    def _package_files(self) -> list[Path]:
        """Return the project's non-test Python files, project-relative.

        Returns:
            Sorted paths outside excluded, test, docs and example directories.
        """
        files = []
        for path in self.project_dir.rglob("*.py"):
            rel = path.relative_to(self.project_dir)
            if self.is_lint_excluded(rel):
                continue
            if any(part in NOT_PACKAGE_DIRS for part in rel.parts[:-1]):
                continue
            if rel.name.startswith("test_") or rel.name == "conftest.py":
                continue
            files.append(rel)
        return sorted(files)

    def run(self) -> CheckResult:
        """Run pylint's duplicate-code checker over the package.

        Returns:
            CheckResult with one issue per duplicated block.
        """
        files = self._package_files()
        if len(files) < 2:
            return CheckResult(check=self.name, passed=True, issues=[])

        cmd = [
            "pylint",
            "--disable=all",
            "--enable=duplicate-code",
            f"--min-similarity-lines={MIN_SIMILARITY_LINES}",
            "--ignore-imports=y",
            "--ignore-docstrings=y",
            "--ignore-comments=y",
            "--ignore-signatures=y",
            "--output-format=json",
            "--score=n",
            *(str(f) for f in files),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=self.project_dir
            )
        except FileNotFoundError:
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description="pylint is not installed",
                        impact=Impact.CRITICAL,
                        explanation="The duplicate-code check runs pylint.",
                    )
                ],
            )

        try:
            messages = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=f"pylint exited {result.returncode} "
                        "without JSON output",
                        impact=Impact.CRITICAL,
                        explanation=(result.stderr or result.stdout)[:500],
                    )
                ],
            )

        # pylint files R0801 under whichever module it read last, often neither
        # of the two copies, so the location is the blocks named here, not a
        # file and line.
        issues = []
        for message in messages:
            if message.get("symbol") != "duplicate-code":
                continue
            lines = message.get("message", "").splitlines()
            blocks = [m for m in (_BLOCK.match(line) for line in lines) if m]
            where = ", ".join(
                f"{b['module']} lines {b['start']}-{b['end']}" for b in blocks
            )
            size = int(blocks[0]["end"]) - int(blocks[0]["start"]) if blocks else 0
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=f"{size} duplicated lines: {where}",
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "Copied code drifts: a fix lands in one copy and not "
                        "the other. Extract the shared block, or mark a "
                        "deliberate copy `# pylint: disable=duplicate-code`."
                    ),
                )
            )
        return CheckResult(check=self.name, passed=not issues, issues=issues)
