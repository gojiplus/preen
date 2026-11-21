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

A handler is reported when it catches broadly (bare ``except``,
``Exception``, ``BaseException`` or ``AssertionError``, alone or in a tuple)
and calls ``skip``, ``xfail`` or ``skipTest`` as one of its own top-level
statements, so every error that reaches it becomes a skip. A handler that
skips only after inspecting the error and re-raises otherwise is not
reported. Catch the specific exception that means "unavailable" instead.

Suppress a deliberate one with ``# preen: allow-skip-on-error`` on the
``except`` line.
"""

import ast

from .base import Check, CheckResult, Impact, Issue, Severity
from .removed_tests import is_test_file

ALLOW_COMMENT = "preen: allow-skip-on-error"
BROAD = frozenset({"Exception", "BaseException", "AssertionError"})
SKIPS = frozenset({"skip", "xfail", "skipTest"})


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """Whether an except clause catches failed assertions.

    Args:
        handler: The except clause.

    Returns:
        True for a bare clause, or one naming a broad class alone or in a
        tuple.
    """
    if handler.type is None:
        return True
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(
        (isinstance(n, ast.Name) and n.id in BROAD)
        or (isinstance(n, ast.Attribute) and n.attr in BROAD)
        for n in names
    )


def _skips_unconditionally(handler: ast.ExceptHandler) -> bool:
    """Whether the handler's own statements include a skip call.

    Args:
        handler: The except clause.

    Returns:
        True when a top-level statement of the body is a call to
        ``*.skip``, ``*.xfail``, ``*.skipTest`` or a bare ``skip(...)``.
    """
    for stmt in handler.body:
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
            continue
        func = stmt.value.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in SKIPS:
            return True
    return False


def find_skip_on_error(source: str) -> list[tuple[int, bool]]:
    """Locate the broad handlers that skip.

    Args:
        source: Module source.

    Returns:
        ``(line, guards_an_assert)`` per finding, where the second element
        says whether the ``try`` body contains an ``assert``, the case where a
        failure is certainly being hidden.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    found: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try | ast.TryStar):
            continue
        asserts = any(
            isinstance(n, ast.Assert) for stmt in node.body for n in ast.walk(stmt)
        )
        for handler in node.handlers:
            if ALLOW_COMMENT in lines[handler.lineno - 1]:
                continue
            if _is_broad(handler) and _skips_unconditionally(handler):
                found.append((handler.lineno, asserts))
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
                source = (self.project_dir / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
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
