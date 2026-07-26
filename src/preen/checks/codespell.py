"""Codespell spell checking check."""

import re
import subprocess
from pathlib import Path

from .base import Check, CheckResult, Fix, Impact, Issue, Severity

# Files whose content is prose or code, where a codespell suggestion is safe
# to apply unattended.
AUTO_FIXABLE_SUFFIXES = frozenset({".md", ".rst", ".txt", ".py"})

# Directory names that hold test data rather than prose. A "misspelling" in a
# fixture is as likely to be a real proper noun -- auto-applying the
# suggestion once turned "Denis Leary" into "Leery" in a transcript fixture.
NEVER_AUTO_DIRS = frozenset({"data", "fixtures", "testdata", "samples", "golden"})


def is_auto_fixable(file_path: Path) -> bool:
    """Return True if a codespell suggestion for this file is safe to auto-apply.

    Args:
        file_path: Repo-relative path to the file.

    Returns:
        True for prose and code files outside data/fixture directories.
    """
    if any(part.lower() in NEVER_AUTO_DIRS for part in file_path.parts):
        return False
    return file_path.suffix.lower() in AUTO_FIXABLE_SUFFIXES


class CodespellCheck(Check):
    """Check for spelling errors in documentation and comments using codespell."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "codespell"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check spelling in documentation and comments with codespell"

    def _parse_codespell_output(self, output: str) -> list[Issue]:
        """Parse codespell output and convert to Issue objects."""
        issues = []

        # Pattern to match codespell output format:
        # path/to/file.py:line: word ==> suggestion
        pattern = r"^(.+?):(\d+): (.+) ==> (.+)$"

        for line in output.strip().split("\n"):
            if not line.strip():
                continue

            match = re.match(pattern, line)
            if match:
                file_path, line_num, misspelled, suggestion = match.groups()

                # Convert absolute path to relative
                try:
                    rel_path = Path(file_path).relative_to(self.project_dir)
                except ValueError:
                    # If path is not under project_dir, use as-is
                    rel_path = Path(file_path)

                # Determine impact based on file location
                impact = self._get_impact_for_file(rel_path)

                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=f"'{misspelled}' should be '{suggestion}'",
                        file=rel_path,
                        line=int(line_num),
                        impact=impact,
                        explanation=(
                            f"Spelling error: '{misspelled}' should be "
                            f"'{suggestion}'. Good spelling improves "
                            "documentation quality."
                        ),
                    )
                )

        return issues

    def _get_impact_for_file(self, file_path: Path) -> Impact:
        """Determine impact level based on file location."""
        file_str = str(file_path).lower()

        # Critical for user-facing documentation
        if any(
            critical in file_str
            for critical in ["readme", "changelog", "license", "contributing"]
        ):
            return Impact.CRITICAL

        # Important for documentation and code
        if file_path.suffix in [".md", ".rst", ".py", ".txt"] or "docs/" in file_str:
            return Impact.IMPORTANT

        # Informational for other files
        return Impact.INFORMATIONAL

    def _get_codespell_command(self, target: Path | None = None) -> list[str]:
        """Build codespell command with appropriate options.

        Args:
            target: Repo-relative path to check, defaulting to the whole
                project.

        Returns:
            The argv list.
        """
        cmd = ["codespell"]

        # codespell auto-discovers setup.cfg/.codespellrc/tox.ini but NOT
        # pyproject.toml -- [tool.codespell] is read only when --toml points
        # at the file. Without this a repo's skip list is silently ignored.
        pyproject = self.project_dir / "pyproject.toml"
        if pyproject.exists():
            cmd.extend(["--toml", str(pyproject)])

        # Add skip patterns for common directories/files that don't need spell checking
        skip_patterns = [
            *sorted(self.excluded_dirs()),
            "*.pyc",
            "*.egg-info",
            "*.ipynb",
            "uv.lock",
        ]

        cmd.extend(["--skip", ",".join(skip_patterns)])

        # Focus on text files and code
        # Don't spell check binary files, images, etc.
        cmd.extend(
            [
                "--check-filenames",  # Also check file names
                "--quiet-level",
                "2",  # Suppress binary file warnings
            ]
        )

        # Relative to the cwd the command runs in, so that repo-relative skip
        # globs in [tool.codespell] match the paths codespell actually sees.
        cmd.append(str(target) if target is not None else ".")

        return cmd

    def run(self) -> CheckResult:
        """Run codespell check."""
        issues = []

        # Check if codespell is available
        try:
            subprocess.run(
                ["codespell", "--version"],
                capture_output=True,
                check=True,
                cwd=self.project_dir,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=(
                            "codespell is not installed. "
                            "Install with: pip install codespell"
                        ),
                        impact=Impact.CRITICAL,
                        explanation=(
                            "codespell is required for spell checking "
                            "documentation and comments"
                        ),
                    )
                ],
            )

        # Run codespell
        cmd = self._get_codespell_command()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        # codespell returns:
        # 0: No misspellings found
        # >0: Misspellings found (exit code represents number of files with issues)

        match result.returncode:
            case 0:
                # No misspellings found - issues list stays empty
                pass
            case code if code > 0 and (result.stdout or result.stderr):
                # Misspellings found - check both stdout and stderr
                output = result.stdout or result.stderr
                if output:
                    issues = self._parse_codespell_output(output)
                    self._attach_fixes(issues)
            case code if code > 0:
                # Non-zero exit code but no output - likely an error
                error_msg = (
                    result.stderr.strip()
                    or f"codespell exited with code {result.returncode}"
                )
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=f"codespell error: {error_msg}",
                        impact=Impact.INFORMATIONAL,
                        explanation="codespell had trouble analyzing some files",
                    )
                )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return True  # Codespell can auto-fix spelling errors

    def _attach_fixes(self, issues: list[Issue]) -> None:
        """Attach one fix per file to the first issue found in that file.

        Fixing per file rather than per repo means the human confirming a
        change sees one file's diff at a time, and lets fixes for content
        codespell cannot judge be held back from ``--auto``.

        Args:
            issues: Parsed issues, mutated in place.
        """
        seen: set[Path] = set()
        for issue in issues:
            if issue.file is None or issue.file in seen:
                continue
            seen.add(issue.file)
            count = sum(1 for other in issues if other.file == issue.file)
            issue.proposed_fix = self._get_fix_for_file(issue.file, count)

    def _get_fix_for_file(self, rel_path: Path, count: int) -> Fix:
        """Create a Fix that applies codespell's corrections to a single file.

        Args:
            rel_path: Repo-relative path to the file.
            count: How many misspellings the file has.

        Returns:
            The fix, flagged for confirmation unless the file is prose or code.
        """

        def apply_codespell_fix() -> None:
            """Apply codespell automatic fixes to this file."""
            cmd = self._get_codespell_command(rel_path)
            cmd.insert(-1, "--write-changes")
            subprocess.run(
                cmd,
                cwd=self.project_dir,
                check=False,  # Don't raise on exit code 1 (fixes applied)
            )

        cmd = self._get_codespell_command(rel_path)
        cmd.insert(-1, "--diff")
        diff_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )
        diff_output = diff_result.stdout or "No diff available"

        auto_ok = is_auto_fixable(rel_path)
        description = f"Fix {count} spelling error(s) in {rel_path}"
        if not auto_ok:
            description += " (needs confirmation: not prose or code)"

        return Fix(
            description=description,
            diff=diff_output,
            apply=apply_codespell_fix,
            requires_confirmation=not auto_ok,
        )
