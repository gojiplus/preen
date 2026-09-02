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
import subprocess
import time
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

#: Fenced blocks worth reading. Bash and text blocks document something else.
_PY_BLOCK = re.compile(r"```(?:python|py|pycon)\n(.*?)```", re.DOTALL)


def _documented_files(project_dir: Path) -> list[Path]:
    """Documentation worth checking for examples.

    Args:
        project_dir: The repo root.

    Returns:
        README plus any markdown under docs/, skipping generated output.
    """
    found = [p for p in (project_dir / "README.md",) if p.exists()]
    docs = project_dir / "docs"
    if docs.is_dir():
        found.extend(sorted(p for p in docs.rglob("*.md") if "_build" not in p.parts))
    return found


def _strip_prompts(block: str) -> str:
    """Turn a pycon-style block into plain source.

    Args:
        block: The fenced block's contents.

    Returns:
        Source with prompts removed and expected-output lines dropped.
    """
    if ">>>" not in block:
        return block
    return "\n".join(
        line.strip()[4:]
        for line in block.splitlines()
        if line.strip().startswith((">>> ", "... "))
    )


def _locally_bound(tree: ast.AST) -> set[str]:
    """Names a block binds itself, which therefore are not the package.

    layoutlens documents a pytest fixture called ``layoutlens``, so every
    ``layoutlens.assert_*`` in its README is a fixture method rather than a
    package attribute. Reading those as exports reported three bugs that were
    not there.

    Args:
        tree: A parsed code block.

    Returns:
        Every name bound as a parameter, assignment, loop or with target.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            bound.update(
                a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            )
            if args.vararg:
                bound.add(args.vararg.arg)
            if args.kwarg:
                bound.add(args.kwarg.arg)
        elif isinstance(node, ast.Assign):
            bound.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(
            node.target, ast.Name
        ):
            bound.add(node.target.id)
        elif isinstance(node, ast.With):
            bound.update(
                item.optional_vars.id
                for item in node.items
                if isinstance(item.optional_vars, ast.Name)
            )
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
    trees = []
    for block in _PY_BLOCK.findall(text):
        try:
            trees.append(ast.parse(_strip_prompts(block)))
        except SyntaxError:
            # A fragment rather than a program. Not this check's business.
            continue

    # Gathered across the whole document rather than per block: a README
    # imports the package once at the top and uses that alias throughout.
    aliases = {package}
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update(
                    a.asname or a.name for a in node.names if a.name == package
                )
            elif isinstance(node, ast.ImportFrom) and node.module == package:
                found.update(
                    a.name
                    for a in node.names
                    if a.name != "*" and not a.name.startswith("__")
                )

    for tree in trees:
        live = aliases - _locally_bound(tree)
        found.update(
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in live
            and not node.attr.startswith("__")
        )
    return found


def exported_symbols(init: Path) -> set[str] | None:
    """Read every name a package's ``__init__`` defines, without importing it.

    Deliberately permissive. ``__all__`` governs ``from x import *``, not
    attribute access, so a name absent from it can still be valid --
    ``__version__`` assigned inside a try/except is the common case, and
    reading ``__all__`` alone reported it as missing from a package that has
    it. A false positive here is a failing check on somebody else's repo; a
    false negative merely misses one stale example.

    Args:
        init: Path to the package's ``__init__.py``.

    Returns:
        The names the module defines, or None if the file cannot be parsed.
    """
    try:
        tree = ast.parse(init.read_text())
    except (OSError, SyntaxError):
        return None

    names: set[str] = set()

    def collect(body: list[ast.stmt]) -> None:
        """Gather names from a statement list, descending into try and if.

        Args:
            body: Statements to walk.
        """
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update(a.asname or a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
                declares_all = any(
                    isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
                )
                if declares_all and isinstance(node.value, (ast.List, ast.Tuple)):
                    names.update(
                        e.value
                        for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.Try):
                collect(node.body)
                for handler in node.handlers:
                    collect(handler.body)
                collect(node.orelse)
                collect(node.finalbody)
            elif isinstance(node, ast.If):
                collect(node.body)
                collect(node.orelse)

    collect(tree.body)
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

        located = self._package_init()
        if located is None:
            return CheckResult(self.name, True, [], time.time() - started)
        package, init = located
        exported = exported_symbols(init)

        if exported is not None:
            for doc in _documented_files(self.project_dir):
                used = referenced_symbols(doc.read_text(), package)
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
        return CheckResult(self.name, not issues, issues, time.time() - started)

    def _run_doctests(self) -> list[Issue]:
        """Execute doctest-style examples, where a repo has asked for it.

        Returns:
            One issue per document whose examples do not reproduce.
        """
        from ..config import PreenConfig

        if not PreenConfig.from_pyproject(self.project_dir).run_doctests:
            return []

        docs = [
            d for d in _documented_files(self.project_dir) if ">>>" in d.read_text()
        ]
        interpreter = self.project_dir / ".venv" / "bin" / "python"
        if not docs:
            return []
        if not interpreter.exists():
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
            done = subprocess.run(
                [str(interpreter), "-m", "doctest", str(doc)],
                capture_output=True,
                text=True,
                cwd=self.project_dir,
                timeout=120,
                check=False,
            )
            if done.returncode != 0:
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=(
                            f"{doc.name} has a documented example that no "
                            f"longer reproduces"
                        ),
                        file=doc,
                        impact=Impact.IMPORTANT,
                        explanation=(done.stdout or done.stderr).strip()[:600],
                    )
                )
        return issues
