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


def _catches(
    handler: ast.ExceptHandler,
    names: frozenset[str],
    builtins_names: frozenset[str] = frozenset({"builtins"}),
) -> bool:
    """Whether an except clause names one of the given builtin classes.

    Args:
        handler: The except clause.
        names: Builtin exception class names.
        builtins_names: Names bound to the ``builtins`` module.

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
            and n.value.id in builtins_names
        ):
            return True
    return False


def _skip_names(tree: ast.Module) -> tuple[set[str], set[str], frozenset[str]]:
    """Find the names a module binds to pytest, its skips and ``builtins``.

    Args:
        tree: The parsed module.

    Returns:
        ``(pytest_aliases, skip_aliases, builtins_aliases)``, from
        module-level imports only: an import inside one function does not
        rename anything in another.
    """
    modules, functions, builtin = {"pytest"}, set(), {"builtins"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pytest":
                    modules.add(alias.asname or "pytest")
                elif alias.name == "builtins":
                    builtin.add(alias.asname or "builtins")
        elif isinstance(node, ast.ImportFrom) and node.module == "pytest":
            for alias in node.names:
                if alias.name in PYTEST_SKIPS:
                    functions.add(alias.asname or alias.name)
    return modules, functions, frozenset(builtin)


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
        value) and no earlier statement is a re-raise guard that lets only a
        narrow exception through.
    """
    for stmt in handler.body:
        value = stmt.value if isinstance(stmt, ast.Expr | ast.Return) else None
        if _is_skip_call(value, modules, functions):
            return True
        if _reraises_all_but_narrow(stmt, handler.name):
            return False
    return False


def _reraises_all_but_narrow(stmt: ast.stmt, err: str | None) -> bool:
    """Whether a statement re-raises every error except a narrow one.

    Args:
        stmt: A statement in the handler.
        err: The name the handler binds the exception to.

    Returns:
        True for ``if not isinstance(err, T): raise``, where ``T`` is not one
        of the broad classes. ``if isinstance(err, T): raise`` lets
        everything else, failed assertions included, through to the skip.
    """
    if not (isinstance(stmt, ast.If) and err and not stmt.orelse):
        return False
    test = stmt.test
    if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
        return False
    call = test.operand
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "isinstance"
        and len(call.args) == 2
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == err
    ):
        return False
    kinds = call.args[1].elts if isinstance(call.args[1], ast.Tuple) else [call.args[1]]
    if any(getattr(k, "id", getattr(k, "attr", "")) in BROAD for k in kinds):
        return False
    return any(isinstance(s, ast.Raise) for s in stmt.body)


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
    raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    try:
        tree = ast.parse(raw)
    except (SyntaxError, ValueError):
        return []
    allowed = _allowed_lines(raw)
    modules, functions, builtin = _skip_names(tree)
    found: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try | ast.TryStar):
            continue
        asserts = any(
            isinstance(n, ast.Assert) for stmt in node.body for n in ast.walk(stmt)
        )
        assertion_caught_earlier = False
        for handler in node.handlers:
            broad = _catches(handler, BROAD, builtin)
            if (
                broad
                and handler.lineno not in allowed
                and _skips_unconditionally(handler, modules, functions)
            ):
                found.append((handler.lineno, asserts and not assertion_caught_earlier))
            if _catches(handler, BROAD, builtin):
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
                    else "an error in the try block is reported as a skip"
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
