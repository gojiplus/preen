"""Find parameters a caller accepts and then fails to forward.

The shape: function ``f`` takes a parameter ``p`` and calls ``g``, which also
takes ``p`` and gives it a default. If the call omits ``p``, ``g`` quietly uses
its default and ``f``'s ``p`` never reaches the thing it names. The code runs,
the tests pass, and a documented knob does nothing.

ruff's ARG001 does not see this. ARG001 fires when a parameter is never read in
the body, but here ``f`` may well read ``p`` elsewhere, and the call to ``g``
has a perfectly valid signature. Only the relationship between the two
signatures gives it away.

This is worth its own check because the failure is silent and the blast radius
is whatever the parameter controlled. One package shipped three of them: a
confidence level that left one interval at 95% while its neighbour honoured the
request, a subsampling cap that never reached the routine that subsamples, and
a coverage simulation whose bootstrap arm reported identical coverage at every
nominal level because the level never arrived.

Suppress a deliberate one with a ``# preen: allow-dropped-arg`` comment on the
call, or in the comment block directly above it, for the case where the callee
is meant to compute with its own default. The marker may open a rationale that
runs to several lines.
"""

import ast
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

ALLOW_COMMENT = "preen: allow-dropped-arg"

FuncDef = ast.FunctionDef | ast.AsyncFunctionDef


def _params(node: FuncDef) -> dict[str, bool]:
    """Map each parameter of a function to whether it has a default.

    Args:
        node: The function definition.

    Returns:
        ``{name: has_default}`` over positional, positional-only and
        keyword-only parameters.
    """
    args = node.args
    positional = args.posonlyargs + args.args
    out: dict[str, bool] = {}
    n_defaults = len(args.defaults)
    for i, arg in enumerate(positional):
        out[arg.arg] = i >= len(positional) - n_defaults
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        out[arg.arg] = default is not None
    return out


def _positional_names(node: FuncDef) -> list[str]:
    """List the parameters a caller may fill positionally, in order.

    Args:
        node: The function definition.

    Returns:
        Parameter names in positional order.
    """
    return [a.arg for a in node.args.posonlyargs + node.args.args]


def _allowed_lines(source: str) -> set[int]:
    """Find the lines a suppression comment covers.

    A marker on a code line covers that line. A marker on a comment line
    covers the comment-only lines that follow it without a break and the
    first line after those, so it can open a rationale of several lines and
    still reach the call underneath. Before, only the line directly above the
    call counted, and a marker that started a longer comment was silently
    ignored.

    Args:
        source: File contents.

    Returns:
        1-based line numbers within reach of an allow comment.
    """
    lines = source.splitlines()
    covered: set[int] = set()
    for i, line in enumerate(lines, start=1):
        if ALLOW_COMMENT not in line:
            continue
        if not line.lstrip().startswith("#"):
            covered.add(i)
            continue
        end = i
        while end < len(lines) and lines[end].lstrip().startswith("#"):
            end += 1
        covered.update(range(i, end + 2))
    return covered


def _index(trees: dict[Path, ast.Module]) -> dict[str, FuncDef]:
    """Index every function by name, dropping names defined more than once.

    A duplicated name cannot be resolved from a bare ``Name`` call with
    confidence, and guessing produces false positives.

    Args:
        trees: Parsed modules keyed by path.

    Returns:
        ``{function_name: definition}``.
    """
    found: dict[str, FuncDef] = {}
    clashes: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name in found:
                    clashes.add(node.name)
                found[node.name] = node
    for name in clashes:
        found.pop(name, None)
    return found


def _owns_block(node: ast.AST) -> bool:
    """Whether a node has a header and then a suite of statements.

    Args:
        node: Any node.

    Returns:
        True for a compound statement, an except handler or a match case.
    """
    return isinstance(node, ast.Match) or isinstance(getattr(node, "body", None), list)


def _start_line(node: ast.AST) -> int:
    """First line of a node, taken from its children when it has none.

    Args:
        node: Any node; a ``match_case`` carries no position of its own.

    Returns:
        The 1-based line.
    """
    own = getattr(node, "lineno", None)
    if own is not None:
        return own
    return min((_start_line(c) for c in ast.iter_child_nodes(node)), default=0)


def _calls_with_statement_lines(
    func: FuncDef,
) -> list[tuple[ast.Call, range]]:
    """Pair each call in a function with the lines a marker must sit on.

    A marker anywhere on a simple statement covers the calls in it, so a
    wrapped call whose marker sits on the first line is still heard. A call
    in a compound statement's header (``if inner(x):``, ``match inner(x):``,
    ``except inner(x):``) is covered by the header's lines, which may wrap,
    and never by its body's, or a marker on ``if`` would silence the body.

    Args:
        func: The function to walk.

    Returns:
        ``(call, lines)`` pairs, in source order.
    """
    found: list[tuple[ast.Call, range]] = []

    def header_end(node: ast.AST) -> int:
        """Last line of a block owner's header, before its body starts.

        Args:
            node: A compound statement, except handler or match case.

        Returns:
            The end line of whatever precedes the body: a condition, an
            iterable, a subject, a pattern, decorators and parameters.
        """
        end = _start_line(node)
        pending = [c for c in ast.iter_child_nodes(node) if not _owns_block(c)]
        while pending:
            child = pending.pop()
            if isinstance(child, ast.stmt):
                continue
            end = max(end, getattr(child, "end_lineno", None) or end)
            pending.extend(c for c in ast.iter_child_nodes(child) if not _owns_block(c))
        return end

    def visit(node: ast.AST, lines: range | None) -> None:
        """Descend, tracking the lines a marker may sit on for this node.

        Args:
            node: The node to visit.
            lines: The enclosing simple statement's lines, or a block
                owner's header lines.
        """
        if _owns_block(node):
            lines = range(_start_line(node), header_end(node) + 1)
        elif isinstance(node, ast.stmt):
            lines = range(node.lineno, (node.end_lineno or node.lineno) + 1)
        if isinstance(node, ast.Call):
            own = range(node.lineno, (node.end_lineno or node.lineno) + 1)
            found.append((node, lines if lines is not None else own))
        for child in ast.iter_child_nodes(node):
            visit(child, lines)

    # Children, not just the body: a default value or a decorator is part of
    # the function too, and a call there drops arguments like any other.
    for child in ast.iter_child_nodes(func):
        visit(child, None)
    return found


def find_dropped(
    trees: dict[Path, ast.Module], allowed: dict[Path, set[int]]
) -> list[tuple[Path, int, str, str, str]]:
    """Report every parameter a caller fails to forward to a local callee.

    Args:
        trees: Parsed modules keyed by path.
        allowed: Suppressed line numbers keyed by path.

    Returns:
        ``(path, line, caller, callee, parameter)`` per finding.
    """
    known = _index(trees)
    findings: list[tuple[Path, int, str, str, str]] = []

    for path, tree in trees.items():
        skip = allowed.get(path, set())
        for caller in ast.walk(tree):
            if not isinstance(caller, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            caller_params = set(_params(caller))
            if not caller_params:
                continue

            for call, lines in _calls_with_statement_lines(caller):
                if not isinstance(call.func, ast.Name):
                    continue
                callee = known.get(call.func.id)
                if callee is None or callee is caller:
                    continue
                if any(kw.arg is None for kw in call.keywords):
                    continue  # `**kwargs` forwards everything; nothing dropped
                if skip & set(lines):
                    continue

                supplied = {kw.arg for kw in call.keywords if kw.arg}
                supplied |= set(_positional_names(callee)[: len(call.args)])

                for name, has_default in sorted(_params(callee).items()):
                    if has_default and name not in supplied and name in caller_params:
                        findings.append(
                            (path, call.lineno, caller.name, callee.name, name)
                        )
    return findings


class DroppedArgsCheck(Check):
    """Check that callers forward the parameters they accept."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "dropped-args"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check for parameters a caller accepts but never forwards"

    def run(self) -> CheckResult:
        """Parse the package and report unforwarded parameters.

        Returns:
            CheckResult containing any issues found.
        """
        trees: dict[Path, ast.Module] = {}
        allowed: dict[Path, set[int]] = {}

        for path in sorted(self.project_dir.rglob("*.py")):
            if self.is_lint_excluded(path.relative_to(self.project_dir)):
                continue
            try:
                source = path.read_text(encoding="utf-8")
                trees[path] = ast.parse(source, filename=str(path))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            allowed[path] = _allowed_lines(source)

        issues: list[Issue] = []
        for path, line, caller, callee, param in find_dropped(trees, allowed):
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"{caller}() takes {param!r} but calls {callee}() "
                        f"without it, so {callee}() uses its own default"
                    ),
                    file=path.relative_to(self.project_dir),
                    line=line,
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "The parameter is accepted, probably documented, and "
                        "silently has no effect. Forward it, or mark the call "
                        f"`# {ALLOW_COMMENT}` if the default is deliberate."
                    ),
                )
            )

        return CheckResult(check=self.name, passed=not issues, issues=issues)
