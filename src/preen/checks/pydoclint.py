"""Pydoclint documentation linting check."""

import re
import subprocess
import tomllib
from pathlib import Path
from typing import ClassVar

# from typing import List  # No longer needed with Python 3.12+
from .base import Check, CheckResult, Impact, Issue, Severity


class PydoclintCheck(Check):
    """Check for docstring quality and completeness using pydoclint."""

    # Used only when the repo has no [tool.pydoclint] of its own to supply one.
    DEFAULT_EXCLUDE = r"\.venv|\.git|\.tox|build|dist|node_modules"

    #: The options canon's template writes, applied when a repo declares none.
    #: Measuring an unadopted repo against pydoclint's stricter defaults
    #: reports "you have not adopted" through the wrong check, once per
    #: docstring: gojiplus/uijudge-bench drew 218 findings, 130 of them
    #: important, of which all but 20 vanish the moment the canon table is
    #: added -- they are DOC105/109/110/203, the type-hints-in-docstring family
    #: canon turns off. The `template` check reports non-adoption once, which
    #: is the right number of times to report it.
    CANON_OPTIONS: ClassVar[tuple[str, ...]] = (
        "--style=google",
        "--arg-type-hints-in-docstring=False",
        "--check-return-types=False",
        "--check-yield-types=False",
        "--check-class-attributes=False",
        "--allow-init-docstring=True",
    )

    # pydoclint emits violations in two shapes -- "path:10: DOC101 ..." and a
    # per-file header followed by indented "  1956: DOC301: ..." lines -- so
    # match the code itself rather than either line layout. Case-sensitive on
    # purpose: its error messages link to violation_codes.html#notes-on-doc103,
    # and that lowercase mention must not read as a violation.
    _VIOLATION_RE = re.compile(r"\bDOC\d{3}\b")

    # The two layouts _VIOLATION_RE deliberately does not distinguish. 0.9.1
    # emits the block form; the flat form is kept because pydoclint has used it
    # and a parser that silently matches neither is what issue #58 was.
    _BLOCK_FILE_RE = re.compile(r"^(?!\s)(?P<path>\S.*\.py)\s*$")
    _BLOCK_VIOLATION_RE = re.compile(
        r"^\s+(?P<line>\d+): (?P<code>DOC\d{3}):?\s+(?P<text>.+)$"
    )
    _FLAT_VIOLATION_RE = re.compile(
        r"^(?!\s)(?P<path>.+?):(?P<line>\d+): (?P<code>DOC\d{3}):?\s+(?P<text>.+)$"
    )

    #: Codes that report a --arg-type-hints-* option disagreeing with the
    #: code, rather than a docstring that contradicts it.
    OPTION_CODES: ClassVar[frozenset[str]] = frozenset(
        {"DOC106", "DOC107", "DOC108", "DOC109", "DOC110", "DOC111"}
    )

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
        """Turn a pydoclint report into Issues.

        Handles both layouts pydoclint uses: a flat ``path:10: DOC101 ...``
        line, and the block form 0.9.1 emits, where a bare file path is
        followed by indented ``    4: DOC101: ...`` lines.

        Args:
            output: Captured pydoclint output.

        Returns:
            One Issue per violation line, in report order.
        """
        issues = []
        current_file: Path | None = None

        for line in output.splitlines():
            if not line.strip():
                continue

            block = self._BLOCK_VIOLATION_RE.match(line)
            if block and current_file is not None:
                issues.append(
                    self._issue_for_violation(
                        current_file,
                        int(block.group("line")),
                        block.group("code"),
                        block.group("text"),
                    )
                )
                continue

            flat = self._FLAT_VIOLATION_RE.match(line)
            if flat:
                issues.append(
                    self._issue_for_violation(
                        Path(flat.group("path")),
                        int(flat.group("line")),
                        flat.group("code"),
                        flat.group("text"),
                    )
                )
                continue

            header = self._BLOCK_FILE_RE.match(line)
            if header:
                current_file = Path(header.group("path"))

        return issues

    def _issue_for_violation(
        self, file_path: Path, line: int, code: str, description: str
    ) -> Issue:
        """Build one Issue from a parsed violation.

        Args:
            file_path: Path pydoclint reported, absolute or project-relative.
            line: Line number of the violation.
            code: The DOC code.
            description: pydoclint's own message for the violation.

        Returns:
            The Issue.
        """
        try:
            rel_path = file_path.relative_to(self.project_dir)
        except ValueError:
            rel_path = file_path

        impact = self._get_impact_for_violation(rel_path, code)
        severity = Severity.ERROR if impact == Impact.CRITICAL else Severity.WARNING

        return Issue(
            check=self.name,
            severity=severity,
            description=f"{code}: {description}",
            file=rel_path,
            line=line,
            impact=impact,
            explanation=self._get_explanation_for_code(code),
        )

    def _get_impact_for_violation(self, file_path: Path, code: str) -> Impact:
        """Classify a violation by where it is and what it says.

        Args:
            file_path: Project-relative path of the file.
            code: The DOC code.

        Returns:
            The impact level.
        """
        # Never critical. Impact.CRITICAL means "blocks release -- security,
        # broken builds"; a docstring that disagrees with its signature is
        # neither, and canon's CI runs bare pydoclint as its own gate anyway, so
        # preen refusing to tag adds nothing but a second veto. Grading a public
        # module's violations critical only became reachable once the parser
        # started working, and it put sixteen release blocks on one repo's
        # `cli.py` for things like "__init__() should not have a docstring".
        if code in self.OPTION_CODES:
            # A repo's type-hint options disagreeing with its code is a
            # configuration preference, not a docstring that misleads a reader.
            return Impact.INFORMATIONAL

        if file_path.suffix != ".py":
            return Impact.INFORMATIONAL

        return Impact.IMPORTANT

    def _get_explanation_for_code(self, code: str) -> str:
        """Explain what family of problem a DOC code belongs to.

        pydoclint already states the specific violation in its own message, so
        this adds the family rather than restating it. The per-code table this
        replaced had drifted wrong -- it called DOC101 "missing docstring in
        public method" when it means the docstring documents fewer arguments
        than the signature takes.

        Args:
            code: The DOC code.

        Returns:
            A one-line explanation.
        """
        families = {
            "0": "The docstring could not be parsed in the configured style.",
            "1": (
                "The documented arguments do not match the ones the function "
                "actually takes, so the docstring misleads a caller."
            ),
            "2": (
                "The documented return value does not match what the function returns."
            ),
            "3": "Class and __init__ docstring content is in the wrong place.",
            "4": "The documented yields do not match what the function yields.",
            "5": "The documented exceptions do not match what the code raises.",
            "6": "The documented class attributes do not match the class.",
        }
        return families.get(code[3:4], "Docstring formatting or completeness issue.")

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
            cmd += [*self.CANON_OPTIONS, f"--exclude={self.DEFAULT_EXCLUDE}"]
        # "." rather than an absolute path: a repo's own [tool.pydoclint]
        # exclude regex is matched against whatever path string pydoclint is
        # handed, so an absolute one lets any ancestor directory name silently
        # exclude the whole tree -- preen's own `exclude = '\.venv|tests|docs'`
        # would match a checkout living under any path containing "docs" -- and
        # makes an anchored user exclude like `^tests/` impossible to satisfy.
        result = subprocess.run(
            [*cmd, "."],
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        # pydoclint returns 0 if no issues, >0 if issues found. It has written
        # violations to stderr as well as stdout, and `stdout or stderr` hides
        # the second whenever the first is non-empty, so read both.
        report = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if result.returncode != 0 and self._looks_like_violations(report):
            issues = self._parse_pydoclint_output(report)
            if not issues:
                # pydoclint failed and its output carries DOC codes, but nothing
                # matched a layout this parser knows. Reporting `passed` here is
                # what issue #58 was: a non-zero pydoclint exit must never
                # become a green check just because preen cannot read it.
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=(
                            "pydoclint reported violations preen could not "
                            f"parse: {report.strip()[:500]}"
                        ),
                        impact=Impact.IMPORTANT,
                        explanation=(
                            "Run 'pydoclint .' directly to see them. preen's "
                            "parser needs updating for this output format."
                        ),
                    )
                )

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

        # Every violation counts, whatever its impact grade: pydoclint itself
        # exits non-zero on all of them and canon's CI runs it as its own gate,
        # so a preen pass that disagrees with that gate is the false pass this
        # check just stopped producing. Impact grades how much it matters at
        # release time; it does not decide whether the check passed.
        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False  # Docstring quality requires manual fixes
