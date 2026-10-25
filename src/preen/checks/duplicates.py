"""Find copied blocks of package code with jscpd.

ruff is the standard's only linter, and ruff has no duplicate-code rule, so a
block pasted into a second module passed every check. Copies drift: the fix
lands in one and not the other. In rank-preserving-calibration, three
copies of one isotonic regression diverged until one mishandled weights.

jscpd is the maintained copy-paste detector, so this check runs it rather
than reimplementing one, on the import package only: tests, docs, examples,
and scripts or notebooks outside the package repeat setup by design. It
replaces pylint's similarity checker (R0801), which compares text and only
across files, so it missed copies inside one module and copies whose local
names differ; across the fleet pylint reported nothing and this check finds
22 groups of copies, 19 of them within one module. jscpd matches renamed
names only when they are renamed consistently
(``--ignore-identifiers=consistent``).

The threshold is 12 lines of code in every copy, not counting imports,
docstrings, comments, blank lines and signatures. jscpd counts raw lines, so
this module counts code lines itself from the syntax tree; at 6, half the
fleet flagged boilerplate, and at 12 every hit sampled was a real copy.

Mark a deliberate copy with ``# jscpd:ignore-start`` and ``# jscpd:ignore-end``
around one of the blocks.
"""

import ast
import io
import json
import re
import shutil
import subprocess
import sysconfig
import tempfile
import tokenize
from importlib import metadata
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

MIN_SIMILARITY_LINES = 12

NOT_PACKAGE_DIRS = frozenset({"tests", "test", "docs", "examples", "benchmarks"})

_NOT_CODE = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
)

Block = tuple[Path, int, int]

# Line -> (byte column where its code starts, where it ends), 0-based UTF-8,
# the unit jscpd reports columns in.
CodeLines = dict[int, tuple[int, int]]

_IGNORE_MARKER = re.compile(r"jscpd:ignore-(start|end)")

_LINE_END = 1 << 30


def _code_lines(text: str) -> CodeLines:
    """Return the lines that hold code, not imports, docstrings or signatures.

    Args:
        text: Source of a module that parses, decoded, with LF newlines.
            jscpd is given this same text, so its lines and columns agree.

    Returns:
        1-based line numbers that count toward the threshold, with the extent
        of their code, so a match ending partway through a line can skip it.
    """
    # The tokenizer's own line split: str.splitlines also breaks at form
    # feeds and U+2028 inside strings, and the line numbers would disagree.
    lines = io.StringIO(text).readlines()

    def byte(line: int, column: int) -> int:
        return len(lines[line - 1][:column].encode("utf-8"))

    code: CodeLines = {}
    dropped: set[int] = set()
    ignore_from: int | None = None
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        # Lines jscpd is told to ignore cannot count toward a copy either.
        # Markers are read in order, so one comment can open and close a
        # region, and a second start inside an open region does not move it.
        if token.type == tokenize.COMMENT:
            for marker in _IGNORE_MARKER.finditer(token.string):
                if marker.group(1) == "start":
                    if ignore_from is None:
                        ignore_from = token.start[0]
                elif ignore_from is not None:
                    dropped.update(range(ignore_from, token.start[0] + 1))
                    ignore_from = None
        if token.type in _NOT_CODE:
            continue
        (first, start), (last, end) = token.start, token.end
        for line in range(first, last + 1):
            begin = byte(line, start) if line == first else 0
            finish = byte(line, end) if line == last else _LINE_END
            low, high = code.get(line, (begin, finish))
            code[line] = (min(low, begin), max(high, finish))
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import | ast.ImportFrom):
            dropped.update(range(node.lineno, (node.end_lineno or 0) + 1))
        # A signature is not shared logic, so parallel public wrappers with
        # matching parameter lists are not copies. Decorators stay: their
        # arguments can carry real duplication, such as copied tool schemas
        # or click options.
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            # The body starts at its first statement's decorators, if any.
            first = node.body[0]
            decorators = getattr(first, "decorator_list", [])
            body_start = min([first.lineno, *(d.lineno for d in decorators)])
            dropped.update(range(node.lineno, body_start))
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            doc = body[0]
            if (
                isinstance(doc, ast.Expr)
                and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)
            ):
                dropped.update(range(doc.lineno, (doc.end_lineno or 0) + 1))
    return {line: extent for line, extent in code.items() if line not in dropped}


def _covered(code: CodeLines, side: dict) -> int:
    """Count the code lines a jscpd match covers completely.

    jscpd reports the lines a match touches; a match that stops after
    ``return`` and before the differing value still names that line.

    Args:
        code: The file's code lines.
        side: One side of a jscpd duplicate, with ``startLoc`` and ``endLoc``.

    Returns:
        Number of code lines inside the match from their first to last token.
    """
    start, end = side["startLoc"], side["endLoc"]
    count = 0
    for line in range(int(start["line"]), int(end["line"]) + 1):
        if line not in code:
            continue
        low, high = code[line]
        if line == start["line"] and start["column"] > low:
            continue
        if line == end["line"] and end["column"] < high:
            continue
        count += 1
    return count


def _jscpd() -> Path:
    """Return the jscpd binary installed with this environment's jscpd package.

    The wheel ships a binary, not a Python module, and where installers put it
    varies: the environment's scripts directory, the user base for
    ``pip --user``. ``uv tool`` and pipx put only preen's own entry point on
    PATH. The package's own file list records where the binary went.

    Returns:
        Path to the jscpd executable (which may not exist, so running it fails
        loudly rather than passing).
    """
    try:
        files = metadata.distribution("jscpd").files or []
    except metadata.PackageNotFoundError:
        files = []
    for file in files:
        if file.name in ("jscpd", "jscpd.exe") and file.parent.name in (
            "bin",
            "Scripts",
        ):
            path = Path(str(file.locate())).resolve()
            if path.exists():
                return path
    scripts = Path(sysconfig.get_path("scripts"))
    for candidate in (scripts / "jscpd.exe", scripts / "jscpd"):
        if candidate.exists():
            return candidate
    found = shutil.which("jscpd")
    return Path(found) if found else scripts / "jscpd"


def _groups(pairs: list[tuple[Block, Block]]) -> list[list[Block]]:
    """Merge pairs that share a copy, so three copies are one finding.

    Args:
        pairs: Matched block pairs.

    Returns:
        Groups of blocks, each sorted, in sorted order.
    """
    parent: dict[Block, Block] = {}

    def root(block: Block) -> Block:
        parent.setdefault(block, block)
        while parent[block] != block:
            parent[block] = parent[parent[block]]
            block = parent[block]
        return block

    for first, second in pairs:
        parent[root(first)] = root(second)
    members: dict[Block, list[Block]] = {}
    for block in parent:
        members.setdefault(root(block), []).append(block)
    return sorted(sorted(group) for group in members.values())


def _error(name: str, description: str, detail: str) -> CheckResult:
    return CheckResult(
        check=name,
        passed=False,
        issues=[
            Issue(
                check=name,
                severity=Severity.ERROR,
                description=description,
                impact=Impact.CRITICAL,
                explanation=detail[:500],
            )
        ],
    )


class DuplicateCodeCheck(Check):
    """Report blocks of package code duplicated within or across modules."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "duplicate-code"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Find copied blocks of package code (jscpd)"

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
        """Run jscpd over the package and keep copies of 12+ code lines.

        Returns:
            CheckResult with one issue per group of duplicated blocks.
        """
        files = self._package_files()
        if not files:
            return CheckResult(check=self.name, passed=True, issues=[])

        # A file that does not parse cannot be measured; passing it would pass
        # a check that did not happen.
        # A symlink to another package module is the same code, not a copy.
        seen: set[Path] = set()
        unique = []
        for rel in files:
            real = (self.project_dir / rel).resolve()
            if real not in seen:
                seen.add(real)
                unique.append(rel)
        files = unique

        code: dict[Path, CodeLines] = {}
        texts: dict[Path, str] = {}
        for rel in files:
            try:
                # tokenize.open decodes as Python does (BOM, coding cookie)
                # and translates newlines to \n.
                with tokenize.open(self.project_dir / rel) as handle:
                    texts[rel] = handle.read()
                code[rel] = _code_lines(texts[rel])
            except (SyntaxError, tokenize.TokenError, UnicodeDecodeError) as exc:
                return _error(self.name, f"cannot parse {rel}", str(exc))

        with tempfile.TemporaryDirectory() as out:
            # jscpd reads UTF-8 only and skips anything else in silence, so it
            # scans UTF-8, \n-only copies of exactly the text measured above.
            sources = Path(out, "src").resolve()
            for rel, text in texts.items():
                (sources / rel).parent.mkdir(parents=True, exist_ok=True)
                (sources / rel).write_text(text, encoding="utf-8", newline="\n")
            # An explicit config keeps a repository's .jscpd.json (threshold,
            # reportName, minLines) from changing what this check runs.
            config = Path(out, "config.json")
            config.write_text("{}")
            report_dir = Path(out, "report")
            cmd = [
                str(_jscpd()),
                *(str(sources / f) for f in files),
                "--config",
                str(config),
                "--format",
                "python",
                # Weak mode skips comment tokens, so copies whose comments
                # differ still match; ignore markers are still honored.
                "--mode",
                "weak",
                "--ignore-identifiers=consistent",
                # jscpd counts raw lines; this is only a prefilter below the
                # code-line threshold applied afterwards.
                "--min-lines",
                str(MIN_SIMILARITY_LINES),
                "--min-tokens",
                "1",
                "--absolute",
                "--no-gitignore",
                "--reporters",
                "json",
                "--output",
                str(report_dir),
                "--silent",
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=sources
                )
            except OSError as exc:
                return _error(self.name, "jscpd failed to run", str(exc))
            report = report_dir / "jscpd-report.json"
            if result.returncode != 0 or not report.exists():
                return _error(
                    self.name,
                    f"jscpd failed to run (exit {result.returncode})",
                    result.stderr or result.stdout,
                )
            try:
                duplicates = json.loads(report.read_text())["duplicates"]
            except (json.JSONDecodeError, KeyError) as exc:
                return _error(self.name, "jscpd wrote an unreadable report", str(exc))

        pairs: list[tuple[Block, Block]] = []
        sizes: dict[Block, int] = {}
        for dup in duplicates:
            first, second = (
                (
                    Path(dup[side]["name"]).resolve().relative_to(sources),
                    int(dup[side]["start"]),
                    int(dup[side]["end"]),
                )
                for side in ("firstFile", "secondFile")
            )
            # Repetitive code can match itself shifted by a few lines.
            if (
                first[0] == second[0]
                and first[1] <= second[2]
                and second[1] <= first[2]
            ):
                continue
            counts = [
                _covered(code[block[0]], dup[side])
                for block, side in ((first, "firstFile"), (second, "secondFile"))
            ]
            if min(counts) >= MIN_SIMILARITY_LINES:
                pairs.append((first, second))
                for block, count in zip((first, second), counts, strict=True):
                    sizes[block] = max(sizes.get(block, 0), count)

        issues = []
        for group in _groups(pairs):
            size = min(sizes[block] for block in group)
            where = ", ".join(
                f"{path} lines {start}-{end}" for path, start, end in group
            )
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=f"{size} duplicated lines of code: {where}",
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "Copied code drifts: a fix lands in one copy and not "
                        "the other. Extract the shared block, or mark a "
                        "deliberate copy with `# jscpd:ignore-start` and "
                        "`# jscpd:ignore-end`."
                    ),
                )
            )
        return CheckResult(check=self.name, passed=not issues, issues=issues)
