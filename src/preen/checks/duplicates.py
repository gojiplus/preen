"""Find copied blocks of package code with pylint's duplicate-code detector.

ruff is the standard's only linter, and ruff has no duplicate-code rule, so a
block pasted into a second module passed every check. Copies drift: the fix
lands in one and not the other. In rank-preserving-calibration, three
copies of one isotonic regression diverged until one mishandled weights.

pylint's similarity checker (R0801) is the established tool for this, so this
check runs it rather than reimplementing it, on the import package only:
tests, docs, examples, scripts and notebooks repeat setup by design. The threshold is 12
matching lines, ignoring imports, docstrings, comments and signatures; at 6,
half the fleet flagged boilerplate, and at 12 every hit sampled was a real
copy.

Suppress a deliberate duplicate with pylint's own marker,
``# pylint: disable=duplicate-code``, in one of the two blocks.
"""

import json
import re
import subprocess
import sys
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
        """Return the Python files of the project's import packages.

        Returns:
            Sorted project-relative paths inside the package directories,
            skipping lint-excluded and test directories within them.
        """
        # In a src/ layout everything under src/ is package code, including a
        # namespace package with no top-level __init__.py.
        src = self.project_dir / "src"
        roots = [src] if src.is_dir() else self.package_dirs()
        packages = [p.relative_to(self.project_dir) for p in roots]
        files = []
        # project_files() respects .gitignore, so ignored files inside a
        # package are not package code either.
        for rel in self.project_files():
            if rel.suffix != ".py" or not any(
                rel.is_relative_to(package) for package in packages
            ):
                continue
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

        # Through this interpreter, not a bare `pylint`: `uv tool install` and
        # pipx put only preen's own entry point on PATH, not its dependencies'.
        cmd = [
            sys.executable,
            "-m",
            "pylint",
            "--disable=all",
            "--enable=duplicate-code",
            # pylint flags runs strictly longer than this, so 12+ needs 11.
            f"--min-similarity-lines={MIN_SIMILARITY_LINES - 1}",
            "--ignore-imports=y",
            "--ignore-docstrings=y",
            "--ignore-comments=y",
            "--ignore-signatures=y",
            "--output-format=json",
            "--score=n",
            *(str(f) for f in files),
        ]
        # A missing pylint module is exit status 1 with "No module named
        # pylint", which the exit-status check below reports.
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_dir
        )

        # pylint's exit status is a bitmask: 8 means refactor messages were
        # found. 1 (fatal), 32 (usage error, e.g. a bad .pylintrc) and, with
        # every other message disabled, 2 (a file that failed to parse) mean
        # the analysis did not complete; reading that as "no findings" would
        # pass a check that did not happen.
        if result.returncode & (1 | 2 | 32):
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=f"pylint failed to run (exit {result.returncode})",
                        impact=Impact.CRITICAL,
                        explanation=(result.stderr or result.stdout)[:500],
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
