"""Find tests that turn any error, failed assertions included, into a skip.

The shape::

    try:
        assert fit(x).monotone
    except Exception:
        pytest.skip("solver not available")

``AssertionError`` is an ``Exception``, so a failed assertion lands in the
handler and is reported as a skip. CI stays green and the run's summary
shows one more skip among dozens. One fleet package had nine of these
hiding three failing assertions. Because a skip ends the test, everything
after the first failure in each loop went unchecked as well.

A handler is reported when it catches broadly (bare ``except``, or the
builtin ``Exception``, ``BaseException`` or ``AssertionError``, alone or in a
tuple) and skips as one of its own top-level statements, with no ``raise``
before the skip. A skip is a call to ``pytest.skip``, ``pytest.xfail`` or
``self.skipTest``, including through ``import pytest as ...`` and ``from
pytest import skip as ...``, called alone or returned. A handler that
inspects the error and re-raises otherwise is not reported. Catch the
specific exception that means "unavailable" instead.

Suppress a deliberate one with a ``# preen: allow-skip-on-error`` comment on
the ``except`` line.
"""

import ast
import io
import tokenize

from .base import Check, CheckResult, Impact, Issue, Severity
from .removed_tests import is_test_file

ALLOW_COMMENT = "preen: allow-skip-on-error"
BROAD = frozenset({"Exception", "BaseException", "AssertionError"})
PYTEST_SKIPS = frozenset({"skip", "xfail"})


def _catches(handler: ast.ExceptHandler, names: frozenset[str]) -> bool:
    """Whether an except clause names one of the given builtin classes.

    Args:
        handler: The except clause.
        names: Builtin exception class names.

    Returns:
        True for a bare clause, or one naming a class in ``names`` as a bare
        name or ``builtins.<name>``, alone or in a tuple. ``pkg.Exception``
        is some other class and does not count.
    """
    if handler.type is None:
        return True
    elts = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    for n in elts:
        if isinstance(n, ast.Name) and n.id in names:
            return True
        if (
            isinstance(n, ast.Attribute)
            and n.attr in names
            and isinstance(n.value, ast.Name)
            and n.value.id == "builtins"
        ):
            return True
    return False


def _skip_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Find the names a module uses for pytest and its skip functions.

    Args:
        tree: The parsed module.

    Returns:
        ``(module_aliases, function_aliases)``: names bound to the pytest
        module, and names bound to ``pytest.skip`` or ``pytest.xfail``.
    """
    modules, functions = {"pytest"}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pytest":
                    modules.add(alias.asname or "pytest")
        elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
            for alias in node.names:
                if alias.name in PYTEST_SKIPS:
                    functions.add(alias.asname or alias.name)
    return modules, functions


def _is_skip_call(
    node: ast.expr | None, modules: set[str], functions: set[str]
) -> bool:
    """Whether an expression calls a function that skips the test.

    Args:
        node: The expression.
        modules: Names bound to the pytest module.
        functions: Names bound to pytest's skip functions.

    Returns:
        True for ``pytest.skip(...)``, ``pytest.xfail(...)``, an imported
        alias of either, or ``<obj>.skipTest(...)``. ``pytest.mark.skip(...)``
        only builds a mark and is not a skip.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in functions
    if isinstance(func, ast.Attribute):
        if func.attr == "skipTest":
            return True
        return (
            func.attr in PYTEST_SKIPS
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        )
    return False


def _skips_unconditionally(
    handler: ast.ExceptHandler, modules: set[str], functions: set[str]
) -> bool:
    """Whether every error reaching the handler becomes a skip.

    Args:
        handler: The except clause.
        modules: Names bound to the pytest module.
        functions: Names bound to pytest's skip functions.

    Returns:
        True when a top-level statement skips (alone or as a ``return``
        value) and no ``raise`` appears in the statements before it.
    """
    for stmt in handler.body:
        value = stmt.value if isinstance(stmt, ast.Expr | ast.Return) else None
        if _is_skip_call(value, modules, functions):
            return True
        if any(isinstance(n, ast.Raise) for n in ast.walk(stmt)):
            return False
    return False


def _allowed_lines(source: bytes) -> set[int]:
    """Find the lines that carry the suppression comment.

    Args:
        source: Module source.

    Returns:
        Line numbers, as the parser counts them, of comments containing the
        marker. Reading comment tokens means the marker inside a string does
        not count, and the numbering matches the AST's even when a string
        holds a character ``str.splitlines`` treats as a line break.
    """
    lines: set[int] = set()
    try:
        for tok in tokenize.tokenize(io.BytesIO(source).readline):
            if tok.type == tokenize.COMMENT and ALLOW_COMMENT in tok.string:
                lines.add(tok.start[0])
    except (tokenize.TokenError, SyntaxError):
        pass
    return lines


def find_skip_on_error(source: str | bytes) -> list[tuple[int, bool]]:
    """Locate the broad handlers that skip.

    Args:
        source: Module source. Bytes are decoded as Python does, honoring a
            coding declaration or a byte-order mark.

    Returns:
        ``(line, guards_an_assert)`` per finding, where the second element
        says whether a failed ``assert`` in the ``try`` body reaches the
        handler: the try contains an ``assert`` and no earlier handler of the
        same ``try`` catches ``AssertionError``.
    """
    raw = source.encode("utf-8") if isinstance(source, str) else source
    try:
        tree = ast.parse(raw)
    except (SyntaxError, ValueError):
        return []
    allowed = _allowed_lines(raw)
    modules, functions = _skip_names(tree)
    found: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try | ast.TryStar):
            continue
        asserts = any(
            isinstance(n, ast.Assert) for stmt in node.body for n in ast.walk(stmt)
        )
        assertion_caught_earlier = False
        for handler in node.handlers:
            broad = _catches(handler, BROAD)
            if (
                broad
                and handler.lineno not in allowed
                and _skips_unconditionally(handler, modules, functions)
            ):
                found.append((handler.lineno, asserts and not assertion_caught_earlier))
            if _catches(handler, BROAD):
                assertion_caught_earlier = True
    return sorted(found)


class SkipOnErrorCheck(Check):
    """Check that tests do not convert failures into skips."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "skip-on-error"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check for broad except handlers in tests that skip"

    def run(self) -> CheckResult:
        """Scan test modules and conftest files for skipping handlers.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        for path in sorted(self.project_files()):
            if not (is_test_file(path) or path.name == "conftest.py"):
                continue
            if self.is_excluded(path):
                continue
            try:
                source = (self.project_dir / path).read_bytes()
            except OSError:
                continue
            for line, asserts in find_skip_on_error(source):
                hidden = (
                    "a failed assertion in the try block is reported as a skip"
                    if asserts
                    else "any error in the try block is reported as a skip"
                )
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=f"broad except handler skips: {hidden}",
                        file=path,
                        line=line,
                        impact=Impact.IMPORTANT,
                        explanation=(
                            "Catch the exception that means the dependency is "
                            "unavailable, not Exception. Mark a deliberate one "
                            f"`# {ALLOW_COMMENT}` on the except line."
                        ),
                    )
                )
        return CheckResult(check=self.name, passed=not issues, issues=issues)
