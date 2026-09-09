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

#: Fenced blocks worth reading, backtick or tilde. Bash and text blocks
#: document something else.
_PY_BLOCK = re.compile(r"(```|~~~)(?:python|py|pycon)\n(.*?)\1", re.DOTALL)


def _blank_fences(text: str) -> str:
    """Blank the lines that open and close each fenced block.

    doctest reads expected output up to a blank line or the next prompt, so
    a closing fence straight after the output would become part of what it
    expected. Only a block's own two fences go; a line inside a tilde block
    that merely looks like a backtick fence is content, and stays.

    Args:
        text: A Markdown document.

    Returns:
        The document with fence lines emptied, line count unchanged.
    """
    out = []
    open_marker: str | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = next((m for m in ("```", "~~~") if stripped.startswith(m)), None)
        if open_marker is None and marker is not None:
            open_marker = marker
            line = "\n" if line.endswith("\n") else ""
        elif open_marker is not None and marker == open_marker:
            open_marker = None
            line = "\n" if line.endswith("\n") else ""
        out.append(line)
    return "".join(out)


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
    if not any(line.strip().startswith(">>>") for line in lines):
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


def _own_scope(tree: ast.AST) -> list[ast.AST]:
    """Every node of a block that is not inside a nested scope.

    A def, class or lambda is yielded, so its name counts as bound, but its
    body is not entered: a parameter named like the package shadows it
    inside that function only. A comprehension is its own scope too.

    Args:
        tree: A parsed code block.

    Returns:
        The nodes, in traversal order.
    """
    out: list[ast.AST] = []
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        out.append(node)
        if not isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Lambda,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            pending.extend(ast.iter_child_nodes(node))
    return out


def _locally_bound(tree: ast.AST, package: str, *, whole: bool = True) -> set[str]:
    """Names a block binds itself, which therefore are not the package.

    layoutlens documents a pytest fixture called ``layoutlens``, so every
    ``layoutlens.assert_*`` in its README is a fixture method rather than a
    package attribute. Reading those as exports reported three bugs that were
    not there.

    Args:
        tree: A parsed code block.
        package: The importable package name, so importing it does not count
            as shadowing it.
        whole: Look inside nested functions too, which is right within a
            block; pass False for what the block leaves bound at its top level.

    Returns:
        Every name bound as a parameter, assignment, loop, with or
        comprehension target, or by importing something other than the package.
    """
    bound: set[str] = set()
    for node in ast.walk(tree) if whole else _own_scope(tree):
        if isinstance(node, ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            if not whole:
                continue  # its parameters live inside it
            args = node.args
            bound.update(
                a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            )
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
        elif isinstance(node, ast.Assign):
            bound.update(*(_target_names(t) for t in node.targets))
        elif isinstance(
            node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            # Its loop variable is its own, but a walrus inside binds here.
            bound.update(
                name
                for sub in ast.walk(node)
                if isinstance(sub, ast.NamedExpr)
                for name in _target_names(sub.target)
            )
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
        elif isinstance(node, ast.Lambda) and whole:
            args = node.args
            bound.update(
                a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            )
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
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
    for _fence, block in _PY_BLOCK.findall(text):
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
        # `import mypkg`, `import mypkg as mp` and `import mypkg.sub` all bind
        # a name to the package. An import inside a helper function binds it
        # there alone, so it neither aliases the rest of the block nor carries
        # to later ones; a binding anywhere, by contrast, shadows the whole
        # block, since a false negative is the cheaper mistake.
        imported = _package_aliases(_own_scope(tree), package)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module == package:
                found.update(
                    a.name
                    for a in node.names
                    if a.name != "*" and not a.name.startswith("__")
                )
            elif node.module.startswith(package + "."):
                # `from mypkg.sub import x` reaches for `mypkg.sub` at least.
                found.add(node.module.split(".")[1])
        # So does `import mypkg.sub`, with or without an alias.
        found.update(
            a.name.split(".")[1]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for a in node.names
            if a.name.startswith(package + ".")
        )
        live = (aliases | imported) - _locally_bound(tree, package)
        # What carries to the next block is only what this one rebinds at
        # top level. A fixture parameter shadows inside its function alone.
        carried = (aliases | imported) - _locally_bound(tree, package, whole=False)
        # `mypkg.callback = ...` creates the attribute rather than reaching
        # for it, and a later `mypkg.callback()` then finds what it made.
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in live
                and not node.attr.startswith("__")
            ):
                (created if isinstance(node.ctx, ast.Store) else found).add(node.attr)
        aliases = carried
    return found - created


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


def _walrus_names(stmt: ast.stmt) -> set[str]:
    """Names a statement binds with ``:=`` in the enclosing scope.

    Args:
        stmt: A module-level statement.

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


def _defined_names(
    path: Path, visiting: frozenset[Path] = frozenset()
) -> tuple[set[str], set[str]] | None:
    """Read every name a module defines at top level, without importing it.

    A relative star import is followed into the sibling module; any other star
    import, a cycle of star imports, or a module-level ``__getattr__`` makes
    the set unknowable from here.

    Args:
        path: The module file.
        visiting: Modules already on the star-import path, to stop a cycle.

    Returns:
        ``(names, declared)``: every name defined, and the subset a literal
        ``__all__`` lists. None if the file cannot be parsed or its exports
        cannot be resolved statically.
    """
    path = path.resolve()
    if path in visiting:
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    names: set[str] = set()
    declared: set[str] = set()
    stars: list[tuple[int, str | None]] = []
    # `__all__ += [...]` or `__all__.extend(...)` means the literal list is
    # not the whole story; then it is treated as if there were none.
    grown: list[bool] = []

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
                if declares_all and isinstance(node.value, (ast.List, ast.Tuple)):
                    declared.update(
                        e.value
                        for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    )
                    names.update(declared)
            elif isinstance(node, ast.AugAssign):
                names.update(_target_names(node.target))
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    grown.append(True)
            elif (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "__all__"
            ):
                grown.append(True)
            elif isinstance(node, ast.AnnAssign):
                names.update(_target_names(node.target))
                if (
                    isinstance(node.target, ast.Name)
                    and node.target.id == "__all__"
                    and isinstance(node.value, (ast.List, ast.Tuple))
                ):
                    declared.update(
                        e.value
                        for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    )
                    names.update(declared)
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
    if grown:
        declared = set()
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
        pulled_names, pulled_declared = pulled
        # A star import brings in exactly what the target's __all__ lists,
        # underscores included, or every public name when it has none.
        names.update(
            pulled_declared or {n for n in pulled_names if not n.startswith("_")}
        )
    return names, declared


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
        if child.suffix == ".py" and child.stem != "__init__":
            names.add(child.stem)
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
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=(
                            f"{doc.name} shows `{package}.{symbol}`, which the "
                            f"package does not define"
                        ),
                        file=doc,
                        impact=Impact.IMPORTANT,
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
