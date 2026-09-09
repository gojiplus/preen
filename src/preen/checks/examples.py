"""Whether the examples in a repo's documentation still match its code.

Every other check here is structural: does a file exist, does ruff pass, does
the changelog have the right shape. None reads what the documentation claims.
That is the one thing CRAN's `R CMD check` does that Python broadly lacks --
it runs your examples, so a package whose docs lie cannot ship. PyPI has no
such gate, which is why the norm must be voluntary, and why a fleet standard
is the place to put it.

The **static** tier carries the coverage and runs everywhere. Across 51 fleet
repos only two use doctest-style prompts, while thirty-seven show Python that
imports their own package. So it parses each fenced Python block, collects the
symbols reached for on the package, and compares them against what the
package's ``__init__`` defines. Nothing is imported and nothing is executed:
both sides are read with `ast`, so this works against a repo whose
dependencies are not installed, which is the normal case for a tool run over
someone else's project.

The **executing** tier is opt-in through ``[tool.preen] run_doctests``.
Measured across the fleet, the only repo it failed was one whose `>>>` blocks
are illustrative -- they depend on bindings from an earlier block and on
output from a live API. Running those by default would fail exactly the repos
the tier exists to serve.

Three false-positive classes were found by running this across every fleet
repo before enabling it, and each is handled below: dunder attributes, a local
binding that shadows the package name, and a name defined inside a try/except.
"""

import ast
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
from collections.abc import Iterable
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

#: A list item's marker and the space after it: the item's content starts
#: past it, and a fence may be indented three spaces past that.
_LIST_ITEM = re.compile(r"(?:[-*+]|\d{1,9}[.)])[ \t]+")

#: Info strings that mark a fenced block as Python. Bash and text blocks
#: document something else.
_PYTHON_INFO = {"python", "py", "pycon"}


def _fences(text: str) -> list[tuple[int, int | None, str]]:
    """Find every fenced block in a Markdown document.

    The rules are CommonMark's: a fence is three or more backticks or tildes
    indented at most three spaces past its container, a closing fence uses
    the same character, is at least as long, is indented at most three spaces
    further, and has nothing after it. A fence-looking line inside a block
    that breaks any of those is content, so a Python block shown inside a
    Markdown block is not code, and one indented four spaces outside any
    list is an indented code block showing Markdown, not a fence. A list
    item moves the container's edge to its content, so a fence inside a
    list still counts.

    Args:
        text: The document.

    Returns:
        ``(opening line, closing line or None, info string)`` per block,
        with 0-based line indexes.
    """
    lines = text.splitlines()
    found: list[tuple[int, int | None, str]] = []
    open_at = -1
    open_marker = ""
    open_indent = 0
    container = 0
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        marker = _fence_marker(stripped)
        if open_at < 0 and stripped:
            item = _LIST_ITEM.match(stripped)
            if item is not None:
                container = indent + len(item.group(0))
            elif indent < container:
                container = 0
        if marker is None:
            continue
        if open_at < 0:
            if indent > container + 3:
                continue
            open_at, open_marker, open_indent = index, marker, indent
            found.append((index, None, stripped[len(marker) :].strip()))
        elif (
            marker[0] == open_marker[0]
            and len(marker) >= len(open_marker)
            and indent <= open_indent + 3
            and not stripped[len(marker) :].strip()
        ):
            found[-1] = (open_at, index, found[-1][2])
            open_at = -1
    return found


def _python_blocks(text: str) -> list[str]:
    """The contents of every Python fenced block in a document.

    Args:
        text: The document.

    Returns:
        Each block's lines joined, in document order.
    """
    lines = text.splitlines()
    blocks = []
    for start, end, info in _fences(text):
        language = info.split()[0].lower() if info else ""
        if language in _PYTHON_INFO:
            stop = end if end is not None else len(lines)
            blocks.append("\n".join(lines[start + 1 : stop]) + "\n")
    return blocks


def _blank_fences(text: str) -> str:
    """Blank the lines that open and close each fenced block.

    doctest reads expected output up to a blank line or the next prompt, so
    a closing fence straight after the output would become part of what it
    expected. Only a block's own two fences go; a fence-looking line that
    does not close the block is content, and stays.

    Args:
        text: A Markdown document.

    Returns:
        The document with fence lines emptied, line count unchanged.
    """
    lines = text.splitlines(keepends=True)
    for start, end, _info in _fences(text):
        for index in (start, end):
            if index is not None:
                lines[index] = "\n" if lines[index].endswith("\n") else ""
    return "".join(lines)


def _fence_marker(stripped: str) -> str | None:
    """The run of backticks or tildes a line opens with, if any.

    Args:
        stripped: The line without its leading whitespace.

    Returns:
        The run, three characters or longer, or None.
    """
    for char in "`~":
        run = len(stripped) - len(stripped.lstrip(char))
        if run >= 3:
            return char * run
    return None


#: Seconds one document's doctests may take. Module-level so a test can lower it.
DOCTEST_TIMEOUT = 120.0


def _documented_files(project_dir: Path, excluded: frozenset[str]) -> list[Path]:
    """Documentation worth checking for examples.

    Args:
        project_dir: The repo root.
        excluded: Directory names no check looks inside, such as ``.venv``;
            a README vendored there belongs to someone else's package.

    Returns:
        README plus any markdown under docs/, skipping generated output.
    """
    found = [p for p in (project_dir / "README.md",) if p.exists()]
    docs = project_dir / "docs"
    if docs.is_dir():
        skip = excluded | {"_build"}
        found.extend(
            sorted(
                p
                for p in docs.rglob("*.md")
                if not skip & set(p.relative_to(docs).parts)
            )
        )
    return found


def _strip_prompts(block: str) -> str:
    """Turn a pycon-style block into plain source.

    Args:
        block: The fenced block's contents.

    Returns:
        Source with prompts removed and expected-output lines dropped.
    """
    lines = block.splitlines()
    first = next((line.strip() for line in lines if line.strip()), "")
    if not first.startswith(">>>"):
        # A session starts with a prompt. A prompt further down is a
        # docstring showing one, and the block is plain code.
        return block
    return "\n".join(
        line.strip()[4:] for line in lines if line.strip().startswith((">>> ", "... "))
    )


def _target_names(target: ast.expr) -> set[str]:
    """Names an assignment target binds, through tuple and list unpacking.

    Args:
        target: The target expression.

    Returns:
        Every plain name inside it.
    """
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(e) for e in target.elts))
    return set()


#: Statements and expressions whose bindings arrive through a target Name.
_TARGET_BINDERS = (
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.NamedExpr,
    ast.For,
    ast.AsyncFor,
    ast.With,
    ast.AsyncWith,
    ast.TypeAlias,
    ast.comprehension,
)

#: Nodes that open a scope of their own.
_SCOPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _scope_nodes(root: ast.AST) -> list[ast.AST]:
    """Every node inside one scope, in source order, nested scopes unentered.

    A nested def, class, lambda or comprehension is listed, so its name counts
    as bound here and it can be visited as a scope of its own, but nothing
    inside it is: a parameter named like the package shadows it in that
    function alone.

    Args:
        root: A module, or a node that opens a scope.

    Returns:
        The nodes, root excluded.
    """
    out: list[ast.AST] = []
    # A comprehension's first iterable runs where the comprehension sits.
    outside = {id(node) for node in _scope_header(root)}
    pending = list(reversed(_scope_body(root)))
    while pending:
        node = pending.pop()
        if id(node) in outside:
            continue
        out.append(node)
        if isinstance(node, _SCOPES):
            # Its decorators, defaults, annotations and bases run out here,
            # where the def sits; only its body runs inside it.
            pending.extend(reversed(_scope_header(node)))
        else:
            pending.extend(reversed(_children_in_evaluation_order(node)))
    return out


def _scope_body(root: ast.AST) -> list[ast.AST]:
    """The children of a scope that run inside it.

    Args:
        root: A module, or a node that opens a scope.

    Returns:
        A def's or class's body statements, a lambda's expression, a
        comprehension's elements and generators, a module's statements.
    """
    if isinstance(root, ast.Lambda):
        return [root.body]
    if isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return list(root.body)
    return _children_in_evaluation_order(root)


def _scope_header(node: ast.AST) -> list[ast.AST]:
    """The parts of a def, class or lambda that run in the enclosing scope.

    Args:
        node: A node that opens a scope.

    Returns:
        Decorators, parameter defaults and annotations, the return
        annotation, a class's bases and keywords, and a comprehension's
        first iterable.
    """
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return [node.generators[0].iter]
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *(k.value for k in node.keywords)]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = node.args
        header: list[ast.AST] = [
            *getattr(node, "decorator_list", []),
            *args.defaults,
            *(d for d in args.kw_defaults if d is not None),
        ]
        params = (*args.posonlyargs, *args.args, *args.kwonlyargs)
        header.extend(a.annotation for a in params if a.annotation is not None)
        header.extend(
            extra.annotation
            for extra in (args.vararg, args.kwarg)
            if extra is not None and extra.annotation is not None
        )
        returns = getattr(node, "returns", None)
        if returns is not None:
            header.append(returns)
        return header
    return []


def _children_in_evaluation_order(node: ast.AST) -> list[ast.AST]:
    """A node's children in the order Python evaluates them.

    ``ast`` lists an assignment's targets before its value and a loop's
    target before its iterable, but the value or iterable runs first: in
    ``mypkg.f = mypkg.f()`` the read happens before the write.

    Args:
        node: Any node.

    Returns:
        Its direct children.
    """
    children = list(ast.iter_child_nodes(node))
    first: ast.AST | None = None
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
        first = node.value
    elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        first = node.iter
    if first is not None:
        children = [first, *(c for c in children if c is not first)]
    return children


def _parameters(root: ast.AST) -> set[str]:
    """The names a scope's own signature binds inside it.

    Args:
        root: A node that opens a scope.

    Returns:
        A function's or lambda's parameters. A comprehension's loop variables
        are bound by its ``comprehension`` nodes instead, and a class or module
        has none.
    """
    args = getattr(root, "args", None)
    if not isinstance(args, ast.arguments):
        return set()
    names = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _locally_bound(nodes: Iterable[ast.AST], package: str) -> set[str]:
    """Names a scope's own statements bind, which therefore are not the package.

    layoutlens documents a pytest fixture called ``layoutlens``, so every
    ``layoutlens.assert_*`` inside its test functions is a fixture method
    rather than a package attribute. Reading those as exports reported three
    bugs that were not there.

    Args:
        nodes: The scope's nodes, from :func:`_scope_nodes`.
        package: The importable package name, so importing it does not count
            as shadowing it.

    Returns:
        Every name bound by assignment, loop, with, except, match capture,
        def, class, type alias, an import of something other than the
        package, or a walrus inside a nested comprehension.
    """
    bound: set[str] = set()
    for node in nodes:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            bound.update(*(_target_names(t) for t in node.targets))
        elif isinstance(
            node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            # Its loop variable is its own, but a walrus inside binds here,
            # unless a lambda inside it owns that walrus.
            bound.update(_walrus_names(node))
        elif isinstance(
            node,
            (
                ast.AnnAssign,
                ast.AugAssign,
                ast.NamedExpr,
                ast.For,
                ast.AsyncFor,
                ast.comprehension,
            ),
        ):
            bound.update(_target_names(node.target))
        elif isinstance(node, ast.TypeAlias):
            bound.update(_target_names(node.name))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    bound.update(_target_names(item.optional_vars))
        elif (
            isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar))
            and node.name
        ):
            bound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
        elif isinstance(node, ast.Import):
            # `import mypkg` and `import mypkg as mp` bind the package itself;
            # `import mypkg.sub` binds `mypkg` too. Anything else bound here,
            # including `import mypkg.sub as mp`, is not the package.
            bound.update(
                a.asname or a.name.split(".")[0]
                for a in node.names
                if a.name != package
                and (a.asname is not None or a.name.split(".")[0] != package)
            )
        elif isinstance(node, ast.ImportFrom):
            # `from mypkg import client as mp` binds a submodule, not the
            # package, so an earlier `import mypkg as mp` no longer applies.
            bound.update(a.asname or a.name for a in node.names if a.name != "*")
    return bound


def _scan_scope(
    root: ast.AST,
    inherited: set[str],
    package: str,
    found: set[str],
    created: set[str],
) -> set[str]:
    """Check one scope's reaches for the package, then its nested scopes.

    A scope sees the aliases live around it, plus what it imports itself,
    minus what it binds itself and its own parameters. Inside a function a
    name bound anywhere is local throughout, as Python has it; at module
    level code runs top-down, so ``mypkg.run()`` before ``mypkg = 1`` still
    reaches for the package and nothing after it does. Reads and writes are
    taken in evaluation order, so ``mypkg.flag = 1`` inside an ``if`` is
    seen before a ``mypkg.flag`` below it.

    Args:
        root: A module, or a node that opens a scope.
        inherited: Names bound to the package around this scope.
        package: The importable package name.
        found: Collects every symbol reached for; extended in place.
        created: Collects every attribute an example creates; extended in
            place.

    Returns:
        The aliases live at the end of this scope. For a module, that is what
        the next block of the document starts from.
    """
    nodes = _scope_nodes(root)
    # A module and a class body run top-down; a function's locals are local
    # throughout it.
    top_down = isinstance(root, (ast.Module, ast.ClassDef))
    if top_down:
        live = set(inherited)
    else:
        live = (
            (inherited | _package_aliases(nodes, package))
            - _locally_bound(nodes, package)
            - _parameters(root)
        )
    augmented: set[int] = set()
    for node in nodes:
        if top_down:
            live |= _package_aliases([node], package)
        if isinstance(node, ast.AugAssign):
            augmented.add(id(node.target))
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == package:
                found.update(
                    a.name
                    for a in node.names
                    if a.name != "*" and not a.name.startswith("__")
                )
            elif node.module.startswith(package + "."):
                # `from mypkg.sub import x` reaches for `mypkg.sub` at least.
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            # So does `import mypkg.sub`, with or without an alias.
            found.update(
                a.name.split(".")[1]
                for a in node.names
                if a.name.startswith(package + ".")
            )
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in live
            and not node.attr.startswith("__")
        ):
            # `mypkg.callback = ...` creates the attribute rather than
            # reaching for it, and a later `mypkg.callback()` finds it.
            # `mypkg.n += 1` reads the attribute before it writes it.
            if isinstance(node.ctx, ast.Store) and id(node) not in augmented:
                created.add(node.attr)
            elif node.attr not in created:
                found.add(node.attr)
        elif isinstance(node, _SCOPES):
            # A method does not see its class's namespace; it sees what the
            # class saw. Anything else nested sees this scope.
            outer = inherited if isinstance(root, ast.ClassDef) else live
            # A def or lambda body runs later, if at all, so what it writes
            # is not there yet for the code around it; a class body or
            # comprehension runs now.
            deferred = isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            )
            _scan_scope(
                node, outer, package, found, set(created) if deferred else created
            )
        if top_down:
            # A binding takes effect once it runs: a Name in Store context
            # comes after the value it is assigned, a def or class after
            # its header, and an import at once.
            if isinstance(node, ast.Name) and isinstance(
                node.ctx, (ast.Store, ast.Del)
            ):
                live.discard(node.id)
            elif not isinstance(node, _TARGET_BINDERS):
                # Anything that binds through a target is handled at that
                # target's Name, after its value; the rest binds here.
                live -= _locally_bound([node], package)
    return live


def referenced_symbols(text: str, package: str) -> set[str]:
    """Find the package symbols a document's examples reach for.

    Args:
        text: The document's contents.
        package: The importable package name.

    Returns:
        Every attribute accessed on the package, plus everything imported from
        it by name. Dunders are excluded: they are language protocol rather
        than package API.
    """
    found: set[str] = set()
    created: set[str] = set()
    trees = []
    for block in _python_blocks(text):
        try:
            # Dedented so a block inside a Markdown list still parses.
            trees.append(ast.parse(_strip_prompts(textwrap.dedent(block))))
        except SyntaxError:
            # A fragment rather than a program. Not this check's business.
            continue

    # Aliases carry across blocks in document order: a README imports the
    # package once at the top and uses that name throughout, and a later
    # `from mypkg import client as mp` retires `mp` until it is imported again.
    aliases = {package}
    for tree in trees:
        aliases = _scan_scope(tree, aliases, package, found, created)
    return found


def _package_aliases(nodes: Iterable[ast.AST], package: str) -> set[str]:
    """Names that ``import`` statements among some nodes bind to the package.

    Args:
        nodes: The nodes to look through.
        package: The importable package name.

    Returns:
        The bound names: ``mypkg`` for ``import mypkg`` or ``import
        mypkg.sub``, ``mp`` for ``import mypkg as mp``.
    """
    names: set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.Import):
            continue
        for a in node.names:
            if a.name == package:
                names.add(a.asname or a.name)
            elif a.asname is None and a.name.split(".")[0] == package:
                names.add(package)
    return names


def _pattern_names(pattern: ast.pattern) -> set[str]:
    """Names a match pattern captures.

    Args:
        pattern: A case pattern.

    Returns:
        Every capture, star and ``**rest`` name inside it.
    """
    names: set[str] = set()
    for node in ast.walk(pattern):
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def _walrus_names(stmt: ast.AST) -> set[str]:
    """Names a statement binds with ``:=`` in the enclosing scope.

    Args:
        stmt: A statement, or a comprehension.

    Returns:
        The targets, not descending into a def, class or lambda, whose
        walruses bind their own scope.
    """
    names: set[str] = set()
    pending: list[ast.AST] = [stmt]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.NamedExpr):
            names.update(_target_names(node.target))
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            pending.extend(ast.iter_child_nodes(node))
    return names


def _relative_module(origin: Path, level: int, module: str | None) -> Path | None:
    """Locate the file a relative import names.

    Args:
        origin: The module doing the importing.
        level: Number of leading dots.
        module: The dotted name after the dots, if any.

    Returns:
        The target's ``__init__.py`` or ``.py`` file, or None if it is not
        inside this package tree.
    """
    if level < 1:
        return None
    base = origin.parent
    for _ in range(level - 1):
        base = base.parent
    target = base.joinpath(*module.split(".")) if module else base
    if (target / "__init__.py").exists():
        return target / "__init__.py"
    if target.with_suffix(".py").exists():
        return target.with_suffix(".py")
    return None


def _string_elements(node: ast.List | ast.Tuple) -> tuple[set[str], bool]:
    """The string literals in a list or tuple display.

    Args:
        node: The display, such as the value of ``__all__``.

    Returns:
        Its strings, and whether they are all of it: ``['a', *extra]`` names
        ``a`` for sure but cannot be read as a complete list.
    """
    strings: set[str] = set()
    complete = True
    for e in node.elts:
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            strings.add(e.value)
        else:
            complete = False
    return strings, complete


def _defined_names(
    path: Path, visiting: frozenset[Path] = frozenset()
) -> tuple[set[str], set[str], bool] | None:
    """Read every name a module defines at top level, without importing it.

    A relative star import is followed into the sibling module; any other star
    import, a cycle of star imports, or a module-level ``__getattr__`` makes
    the set unknowable from here.

    Args:
        path: The module file.
        visiting: Modules already on the star-import path, to stop a cycle.

    Returns:
        ``(names, listed, complete)``: every name defined; every string a
        literal ``__all__`` names, including in ``+=`` and ``extend``; and
        whether that listing is the whole of ``__all__``. None if the file
        cannot be parsed or its exports cannot be resolved statically.
    """
    path = path.resolve()
    if path in visiting:
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    names: set[str] = set()
    listed: set[str] = set()
    stars: list[tuple[int, str | None]] = []
    # `__all__ = [...]` makes the list complete; `+= [...]`, `.extend(...)`
    # or a computed element such as `*extra` means it is only a lower bound.
    state = {"seen": False, "complete": True}

    def note_all(value: ast.expr, *, complete: bool) -> None:
        """Record what an ``__all__`` assignment or extension contributes.

        Args:
            value: The right-hand side, or an ``extend`` argument.
            complete: Whether this is a fresh ``__all__ = [...]`` rather
                than an addition to one.
        """
        strings: set[str] = set()
        literal = isinstance(value, (ast.List, ast.Tuple))
        if literal:
            strings, whole = _string_elements(value)
            complete = complete and whole
        else:
            # Whatever the expression names literally, at least: a string
            # handed to append, or list literals inside a sum.
            for sub in ast.walk(value):
                if isinstance(sub, (ast.List, ast.Tuple)):
                    strings |= _string_elements(sub)[0]
                elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    strings.add(sub.value)
            complete = False
        state["seen"] = True
        if not complete:
            state["complete"] = False
        listed.update(strings)
        names.update(strings)

    def collect(body: list[ast.stmt]) -> None:
        """Gather names from a statement list, descending into try and if.

        Args:
            body: Statements to walk.
        """
        for node in body:
            names.update(_walrus_names(node))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Import):
                names.update(a.asname or a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if any(a.name == "*" for a in node.names):
                    stars.append((node.level, node.module))
                names.update(a.asname or a.name for a in node.names if a.name != "*")
            elif isinstance(node, ast.Assign):
                names.update(*(_target_names(t) for t in node.targets))
                declares_all = any(
                    isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
                )
                if declares_all:
                    # `__all__ = [...]` is complete; `__all__ = __all__ + [...]`
                    # or any other expression is only what it names.
                    literal = isinstance(node.value, (ast.List, ast.Tuple))
                    note_all(node.value, complete=literal)
            elif isinstance(node, ast.AugAssign):
                names.update(_target_names(node.target))
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    note_all(node.value, complete=False)
            elif (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "__all__"
            ):
                for arg in node.value.args:
                    note_all(arg, complete=False)
            elif isinstance(node, ast.AnnAssign):
                names.update(_target_names(node.target))
                if (
                    isinstance(node.target, ast.Name)
                    and node.target.id == "__all__"
                    and node.value is not None
                ):
                    literal = isinstance(node.value, (ast.List, ast.Tuple))
                    note_all(node.value, complete=literal)
            elif isinstance(node, ast.TypeAlias):
                names.update(_target_names(node.name))
            # Every compound statement's suites are still module level:
            # `try: from x import y`, `with suppress(ImportError): ...`, a
            # `match sys.platform` that picks a backend, all bind names here.
            elif isinstance(node, (ast.Try, ast.TryStar)):
                collect(node.body)
                for handler in node.handlers:
                    collect(handler.body)
                collect(node.orelse)
                collect(node.finalbody)
            elif isinstance(node, (ast.If, ast.While)):
                collect(node.body)
                collect(node.orelse)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                names.update(_target_names(node.target))
                collect(node.body)
                collect(node.orelse)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        names.update(_target_names(item.optional_vars))
                collect(node.body)
            elif isinstance(node, ast.Match):
                for case in node.cases:
                    names.update(_pattern_names(case.pattern))
                    collect(case.body)

    collect(tree.body)
    if "__getattr__" in names:
        # PEP 562: attributes are made on demand, so no static list is complete.
        return None
    for level, module in stars:
        target = _relative_module(path, level, module)
        pulled = (
            _defined_names(target, visiting | {path}) if target is not None else None
        )
        if pulled is None:
            return None
        pulled_names, pulled_listed, pulled_complete = pulled
        # A star import brings in exactly what the target's __all__ lists,
        # underscores included and an empty list included. When the list is
        # only a lower bound, or there is none, every public name comes too.
        names.update(pulled_listed)
        if not pulled_complete:
            names.update(n for n in pulled_names if not n.startswith("_"))
    return names, listed, state["seen"] and state["complete"]


def exported_symbols(init: Path) -> set[str] | None:
    """Read every name a package exposes, without importing it.

    Deliberately permissive. ``__all__`` governs ``from x import *``, not
    attribute access, so a name absent from it can still be valid --
    ``__version__`` assigned inside a try/except is the common case, and
    reading ``__all__`` alone reported it as missing from a package that has
    it. A false positive here is a failing check on somebody else's repo; a
    false negative merely misses one stale example.

    Args:
        init: Path to the package's ``__init__.py``.

    Returns:
        The names ``__init__`` defines plus every child module and subpackage,
        which ``from pkg import child`` loads without ``__init__`` naming it.
        None if the exports cannot be read statically.
    """
    defined = _defined_names(init)
    if defined is None:
        return None
    names = defined[0]
    for child in init.parent.iterdir():
        # A module is a .py file or a compiled extension such as
        # `_fast.cpython-313-darwin.so`; the import name is up to the first dot.
        module = child.name.split(".")[0]
        if (
            child.is_file()
            and child.suffix in {".py", ".so", ".pyd"}
            and module.isidentifier()
            and module != "__init__"
        ):
            names.add(module)
        elif child.is_dir() and child.name.isidentifier():
            # With or without __init__.py: a bare directory is a namespace
            # package, and `from pkg import child` loads it.
            names.add(child.name)
    return names


class ExamplesCheck(Check):
    """Check that documented examples still match the package."""

    @property
    def name(self) -> str:
        """Return the name of this check.

        Returns:
            The check name.
        """
        return "examples"

    @property
    def description(self) -> str:
        """Return a description of what this check does.

        Returns:
            A one-line description.
        """
        return "Check documented examples still name symbols the package has"

    def _package_init(self) -> tuple[str, Path] | None:
        """Locate the package's ``__init__.py``.

        Returns:
            An ``(import name, path)`` pair, or None where there is no single
            obvious package to check against.
        """
        src = self.project_dir / "src"
        candidates = (
            [d for d in src.iterdir() if (d / "__init__.py").exists()]
            if src.is_dir()
            else [
                d
                for d in self.project_dir.iterdir()
                if d.is_dir()
                and d.name not in self.excluded_dirs()
                and (d / "__init__.py").exists()
            ]
        )
        if len(candidates) != 1:
            return None
        return candidates[0].name, candidates[0] / "__init__.py"

    def run(self) -> CheckResult:
        """Run the check.

        Returns:
            The result, listing any documented symbol the package lacks.
        """
        started = time.time()
        issues: list[Issue] = []

        # Only the static tier needs one package to compare against.
        located = self._package_init()
        exported = exported_symbols(located[1]) if located else None
        if located and exported is not None:
            package = located[0]
            for doc in _documented_files(self.project_dir, self.excluded_dirs()):
                used = referenced_symbols(doc.read_text(encoding="utf-8"), package)
                issues.extend(
                    # Advisory in 0.6.0. Thirty-five rounds of independent
                    # review kept finding corners of Python and Markdown this
                    # static tier had not met, and a false positive here fails
                    # someone else's CI. It gates once a fleet sweep shows a
                    # release with none.
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=(
                            f"{doc.name} shows `{package}.{symbol}`, which the "
                            f"package does not define"
                        ),
                        file=doc,
                        impact=Impact.INFORMATIONAL,
                        explanation=(
                            "An example naming something that no longer exists "
                            "fails for the first person who copies it, and "
                            "nothing else in the suite reads documentation."
                        ),
                    )
                    for symbol in sorted(used - exported)
                )

        issues.extend(self._run_doctests())
        blocking = [issue for issue in issues if issue.severity != Severity.INFO]
        return CheckResult(self.name, not blocking, issues, time.time() - started)

    def _run_doctests(self) -> list[Issue]:
        """Execute doctest-style examples, where a repo has asked for it.

        Returns:
            One issue per document whose examples do not reproduce.
        """
        from ..config import PreenConfig

        if not PreenConfig.from_pyproject(self.project_dir).run_doctests:
            return []

        root = self.project_dir.resolve()
        docs = [
            d
            for d in _documented_files(root, self.excluded_dirs())
            if ">>>" in d.read_text(encoding="utf-8")
        ]
        interpreter = next(
            (
                p
                for p in (
                    root / ".venv" / "bin" / "python",
                    root / ".venv" / "Scripts" / "python.exe",
                )
                if p.exists()
            ),
            None,
        )
        if not docs:
            return []
        if interpreter is None:
            # Saying so beats passing silently: nothing was checked.
            return [
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description="doctest examples not executed: no .venv in this repo",
                    impact=Impact.INFORMATIONAL,
                )
            ]

        issues = []
        for doc in docs:
            failure = self._doctest(doc, interpreter, root)
            if failure is not None:
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=f"{doc.name} {failure[0]}",
                        file=doc,
                        impact=Impact.IMPORTANT,
                        explanation=failure[1],
                    )
                )
        return issues

    @staticmethod
    def _doctest(doc: Path, interpreter: Path, root: Path) -> tuple[str, str] | None:
        """Run one document's doctests under the repo's interpreter.

        doctest reads expected output up to a blank line or the next prompt,
        so a closing fence straight after the output became part of what it
        expected. The document is copied with every fence line blanked, which
        keeps line numbers intact, and run from a scratch directory.

        Args:
            doc: The document.
            interpreter: The repo's Python.
            root: The repo root, absolute, which the examples run from.

        Returns:
            ``(what happened, detail)`` on failure, None on success.
        """
        scratch = Path(tempfile.mkdtemp(prefix="preen-doctest-"))
        try:
            copy = scratch / doc.name
            copy.write_text(
                _blank_fences(doc.read_text(encoding="utf-8")), encoding="utf-8"
            )
            try:
                done = subprocess.run(
                    [str(interpreter), "-m", "doctest", str(copy)],
                    capture_output=True,
                    text=True,
                    cwd=root,
                    timeout=DOCTEST_TIMEOUT,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return (
                    f"has a documented example that did not finish within "
                    f"{DOCTEST_TIMEOUT:g} seconds",
                    "A hanging example is reported rather than aborting the run.",
                )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        if done.returncode == 0:
            return None
        return (
            "has a documented example that no longer reproduces",
            (done.stdout or done.stderr).strip()[:600],
        )
