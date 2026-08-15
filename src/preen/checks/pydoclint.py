"""Pydoclint documentation linting check."""

import re
import subprocess
import tomllib
from pathlib import Path

# from typing import List  # No longer needed with Python 3.12+
from .base import Check, CheckResult, Impact, Issue, Severity


class PydoclintCheck(Check):
    """Check for docstring quality and completeness using pydoclint."""

    # Used only when the repo has no [tool.pydoclint] of its own to supply one.
    DEFAULT_EXCLUDE = r"\.venv|\.git|\.tox|build|dist|node_modules"

    # pydoclint emits violations in two shapes -- "path:10: DOC101 ..." and a
    # per-file header followed by indented "  1956: DOC301: ..." lines -- so
    # match the code itself rather than either line layout. Case-sensitive on
    # purpose: its error messages link to violation_codes.html#notes-on-doc103,
    # and that lowercase mention must not read as a violation.
    _VIOLATION_RE = re.compile(r"\bDOC\d{3}\b")

    @classmethod
    def _looks_like_violations(cls, text: str) -> bool:
        """Report whether `text` is a violation report rather than a failure.

        Args:
            text: Captured pydoclint output.

        Returns:
            True when at least one line carries a DOC code.
        """
        return bool(text) and bool(cls._VIOLATION_RE.search(text))

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "pydoclint"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check docstring quality and completeness with pydoclint"

    def _has_pydoclint_config(self) -> bool:
        """Report whether pyproject.toml actually carries a [tool.pydoclint] table.

        The existence of pyproject.toml is not the same question. pydoclint
        refuses to start when handed ``--config`` for a file with no
        ``[tool.pydoclint]`` section::

            Error: Invalid value for '--config': Config file "pyproject.toml"
            does not have a [tool.pydoclint] section.

        Treating the two as equivalent meant the check never ran on any repo
        without that table -- it reported a warning about its own invocation
        instead, so a repo with real docstring problems looked like one with
        none. Eight of the twenty-six repos in py-canon's FLEET were affected.

        Returns:
            True when the table is present and the file parses.
        """
        pyproject = self.project_dir / "pyproject.toml"
        if not pyproject.exists():
            return False
        try:
            with pyproject.open("rb") as fh:
                return "pydoclint" in tomllib.load(fh).get("tool", {})
        except (tomllib.TOMLDecodeError, OSError):
            # An unreadable pyproject is someone else's finding to report; here
            # it just means fall back to the default style.
            return False

    def _parse_pydoclint_output(self, output: str) -> list[Issue]:
        """Parse pydoclint output and convert to Issue objects."""
        issues = []

        # Pattern to match pydoclint output format:
        # path/to/file.py:line: DOC001 Missing docstring in function
        pattern = r"^(.+?):(\d+): (DOC\d+) (.+)$"

        for line in output.strip().split("\n"):
            if not line.strip():
                continue

            match = re.match(pattern, line)
            if match:
                file_path, line_num, code, description = match.groups()

                # Convert absolute path to relative
                try:
                    rel_path = Path(file_path).relative_to(self.project_dir)
                except ValueError:
                    # If path is not under project_dir, use as-is
                    rel_path = Path(file_path)

                # Determine impact based on file location and violation type
                impact = self._get_impact_for_violation(rel_path, code, description)

                # Determine severity - most docstring issues are warnings
                severity = (
                    Severity.ERROR
                    if (
                        "missing" in description.lower()
                        and any(
                            critical in rel_path.name
                            for critical in ["__init__.py", "cli.py"]
                        )
                    )
                    or any(critical in str(rel_path) for critical in ["api/", "public"])
                    else Severity.WARNING
                )

                issues.append(
                    Issue(
                        check=self.name,
                        severity=severity,
                        description=f"{code}: {description}",
                        file=rel_path,
                        line=int(line_num),
                        impact=impact,
                        explanation=self._get_explanation_for_code(code),
                    )
                )

        return issues

    def _get_impact_for_violation(
        self, file_path: Path, code: str, description: str
    ) -> Impact:
        """Determine impact level based on file location and violation type."""
        # Critical for public APIs and main module files
        if file_path.name in ["__init__.py", "cli.py"] or any(
            critical in str(file_path) for critical in ["api/", "public"]
        ):
            return Impact.CRITICAL

        # Important for most Python files with docstring issues
        if file_path.suffix == ".py":
            # Missing docstrings are more important than formatting issues
            if "missing" in description.lower() or code in [
                "DOC101",
                "DOC102",
                "DOC103",
            ]:
                return Impact.IMPORTANT
            return Impact.INFORMATIONAL

        # Everything else is informational
        return Impact.INFORMATIONAL

    def _get_explanation_for_code(self, code: str) -> str:
        """Provide explanation for common pydoclint error codes."""
        explanations = {
            "DOC101": "Missing docstring in public method",
            "DOC102": "Missing docstring in public function",
            "DOC103": "Missing docstring in public class",
            "DOC201": "Function/method has no argument documented",
            "DOC202": "Function/method has argument documented but not defined",
            "DOC203": "Function/method has return documented but no return statement",
            "DOC501": "Function/method has exception documented but not raised",
            "DOC502": "Function/method has exception raised but not documented",
        }

        base_explanation = explanations.get(
            code, "Docstring formatting or completeness issue"
        )

        return (
            f"{base_explanation}. Good documentation improves code "
            "maintainability and helps other developers understand your code."
        )

    def run(self) -> CheckResult:
        """Run pydoclint check."""
        issues = []

        # Check if pydoclint is available
        try:
            subprocess.run(
                ["pydoclint", "--version"],
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
                            "pydoclint is not installed. "
                            "Install with: pip install pydoclint"
                        ),
                        impact=Impact.CRITICAL,
                        explanation=(
                            "pydoclint is required for docstring quality checking"
                        ),
                    )
                ],
            )

        # Run pydoclint on the project directory
        # Use --quiet to suppress file scanning output, only show violations
        cmd = ["pydoclint", "--quiet"]
        if self._has_pydoclint_config():
            # Honor the repo's own [tool.pydoclint] (style, exclude, options)
            cmd += ["--config", "pyproject.toml"]
        else:
            # The repo's own config would carry an exclude; without one,
            # pydoclint walks everything under the project directory. On a repo
            # with a .venv that is every installed dependency -- 34,696 lines of
            # findings about OpenSSL and friends, none of them this repo's.
            cmd += ["--style=google", f"--exclude={self.DEFAULT_EXCLUDE}"]
        result = subprocess.run(
            [*cmd, str(self.project_dir)],
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        # pydoclint returns 0 if no issues, >0 if issues found. It writes the
        # violations themselves to stderr, not stdout, so reading only stdout
        # meant every real finding was reported as "pydoclint encountered an
        # error" -- the check has never surfaced a docstring violation this way.
        report = result.stdout or result.stderr
        if result.returncode != 0 and self._looks_like_violations(report):
            issues = self._parse_pydoclint_output(report)

        # A genuine failure to run: non-zero, but nothing that parses as output.
        elif result.stderr and result.returncode != 0:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"pydoclint encountered an error: {result.stderr.strip()}"
                    ),
                    impact=Impact.INFORMATIONAL,
                    explanation="pydoclint had trouble analyzing some files",
                )
            )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False  # Docstring quality requires manual fixes
