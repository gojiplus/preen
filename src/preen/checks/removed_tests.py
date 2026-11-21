"""Find tests a change deletes without saying what replaces them.

A rewrite that swaps one implementation for another tends to delete the old
implementation's tests along with it. Each deletion looks reasonable on its
own, since those tests named the old function. The trouble is the property
they pinned, which nothing pins any more. One fleet commit moved URL fetching
onto requests-hardened and deleted three tests on the way: the one checking
that a redirect to a private address is refused, the IPv6 loopback case, and
the check that a public address is allowed. The commit message still
promised the redirect protection. The code kept it, but nothing tested it.

Coverage does not see this. The lines those tests exercised are still
executed by other tests, so the percentage does not move.

The check compares the test inventory at the base with the working tree. The
inventory holds every ``test*`` function and method (in ``Test*`` classes and
``unittest.TestCase`` subclasses, including under a module-level ``if`` or
``try``), plus every case of a ``pytest.mark.parametrize`` whose values are a
literal list, on the function or its class. A test whose body reappears in a
newly added test counts as renamed, not removed. A removal passes when a
commit since the base carries a git trailer naming it; ``*`` and ``?`` are the
only wildcards::

    Removed-test: tests/test_lit.py::test_redirects_are_rechecked
    Removed-test: tests/test_old.py::*

The trailer is the point: deleting a test stays cheap, and the reason for it
is written down where a reviewer reads it.

The base is ``$PREEN_BASE_REF``; else, on a pull request (``GITHUB_BASE_REF``
set) whose checkout is GitHub's merge commit, that commit's first parent,
which is the target it was built against; else the merge base with
``origin/$GITHUB_BASE_REF``, the branch's upstream, or ``origin/HEAD``. When
none resolves, for example in a shallow clone, the check says so and passes.

Not seen: cases built at run time (non-literal ``argvalues``,
``pytest_generate_tests``), tests in symlinked files, and tests outside a
sparse checkout, which read as removed.
"""

import ast
import difflib
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

TRAILER_KEYS = ("Removed-test", "Removed-tests")

FuncDef = ast.FunctionDef | ast.AsyncFunctionDef


def is_test_file(path: Path) -> bool:
    """Whether pytest would collect tests from a file by default.

    Args:
        path: Project-relative path.

    Returns:
        True for ``test_*.py`` and ``*_test.py``.
    """
    return path.suffix == ".py" and (
        path.name.startswith("test_") or path.stem.endswith("_test")
    )


@dataclass(frozen=True)
class InventoryEntry:
    """One test function and the parametrize cases it declares.

    Attributes:
        node_id: ``path::Class::name``, as pytest spells it.
        fingerprint: The function's arguments and body as source, without
            its name or decorators, so a rename or a move matches.
        cases: One key per literal parametrize case. A value repeated in the
            same list gets ``#2``, ``#3`` so shortening ``[1, 1]`` to ``[1]``
            counts as a removal.
    """

    node_id: str
    fingerprint: str
    cases: frozenset[str]


def _names_key(node: ast.expr) -> str:
    """Spell parametrize argnames the same however they were written.

    Args:
        node: The argnames expression.

    Returns:
        Comma-joined names without spaces: ``"x, y"``, ``"x,y"`` and
        ``("x", "y")`` all give ``x,y``.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return ",".join(n.strip() for n in node.value.split(","))
    if isinstance(node, ast.List | ast.Tuple) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts
    ):
        return ",".join(str(e.value).strip() for e in node.elts)  # type: ignore[union-attr]
    return ast.unparse(node)


def _value_key(node: ast.expr) -> str:
    """Spell one parametrize value by what it passes, not how it is labeled.

    Args:
        node: One element of argvalues.

    Returns:
        The unparsed value. For ``pytest.param(...)`` only the positional
        arguments count, so changing its ``id`` or marks is not a removal.
    """
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute | ast.Name)
        and (getattr(node.func, "attr", None) or getattr(node.func, "id", None))
        == "param"
    ):
        args = node.args
        return ast.unparse(args[0]) if len(args) == 1 else ast.unparse(ast.Tuple(args))
    return ast.unparse(node)


def _parametrize_cases(decorators: list[ast.expr]) -> list[str]:
    """List the literal cases of every parametrize decorator.

    Args:
        decorators: A function's or class's decorator list.

    Returns:
        One ``argnames=value`` key per case. Values that are not a literal
        list or tuple contribute nothing, since they cannot be read
        statically.
    """
    cases: list[str] = []
    for deco in decorators:
        if not isinstance(deco, ast.Call):
            continue
        target = deco.func
        if not (isinstance(target, ast.Attribute) and target.attr == "parametrize"):
            continue
        names = deco.args[0] if deco.args else None
        values = deco.args[1] if len(deco.args) > 1 else None
        for kw in deco.keywords:
            if kw.arg == "argnames":
                names = kw.value
            elif kw.arg == "argvalues":
                values = kw.value
        if names is None or not isinstance(values, ast.List | ast.Tuple):
            continue
        key = _names_key(names)
        counts: Counter[str] = Counter()
        for v in values.elts:
            case = f"{key}={_value_key(v)}"
            counts[case] += 1
            cases.append(case if counts[case] == 1 else f"{case}#{counts[case]}")
    return cases


def _fingerprint(func: FuncDef) -> str:
    """Describe a test function independently of its name and position.

    Args:
        func: The test function.

    Returns:
        Its arguments and body, unparsed, so formatting does not count.
        Decorators are left out, so a parametrize case removed from a renamed
        test is still compared case by case rather than hiding behind the
        rename.
    """
    body = ast.Module(body=[*func.body], type_ignores=[])
    return f"({ast.unparse(func.args)})\n{ast.unparse(body)}"


def _is_test_class(node: ast.ClassDef) -> bool:
    """Whether pytest collects tests from a class.

    Args:
        node: The class.

    Returns:
        True for ``Test*`` names and for ``unittest.TestCase`` subclasses,
        recognized by a base whose name ends in ``TestCase``.
    """
    if node.name.startswith("Test"):
        return True
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name.endswith("TestCase"):
            return True
    return False


def inventory(path: str, source: str | bytes) -> list[InventoryEntry]:
    """List the tests a module defines.

    Args:
        path: The module's project-relative path, in POSIX form.
        source: Its contents. Bytes are decoded the way Python does it,
            honoring a coding declaration or a byte-order mark.

    Returns:
        ``test*`` functions at module level and ``test*`` methods of test
        classes, nested classes included, and those under module-level or
        class-level ``if``, ``try`` and ``with`` blocks. A file that does not
        parse yields nothing; the test run reports it.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    found: list[InventoryEntry] = []

    def visit(body: list[ast.stmt], prefix: str, inherited: list[str]) -> None:
        for node in body:
            if isinstance(node, FuncDef) and node.name.startswith("test"):
                cases = inherited + _parametrize_cases(node.decorator_list)
                found.append(
                    InventoryEntry(
                        f"{prefix}::{node.name}", _fingerprint(node), frozenset(cases)
                    )
                )
            elif isinstance(node, ast.ClassDef) and _is_test_class(node):
                visit(
                    node.body,
                    f"{prefix}::{node.name}",
                    inherited + _parametrize_cases(node.decorator_list),
                )
            elif isinstance(node, ast.If | ast.Try | ast.TryStar | ast.With):
                for block in ("body", "orelse", "finalbody"):
                    visit(getattr(node, block, []), prefix, inherited)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body, prefix, inherited)

    visit(tree.body, path, [])
    return found


#: How alike two bodies must be for a vanished test to count as renamed to a
#: newly added one. A rename that also renames a variable (``per_km`` to
#: ``per_mile``) scores about 0.97. A small edit that inverts what a test
#: checks (``is True`` to ``is False``) can also clear it, so only tests that
#: did not exist at the base are candidates.
RENAME_SIMILARITY = 0.8


def _renamed_to(
    old: InventoryEntry, added: list[InventoryEntry]
) -> InventoryEntry | None:
    """Find the new test a vanished one most plausibly became.

    Args:
        old: A test whose id no longer exists.
        added: Tests whose ids did not exist at the base.

    Returns:
        An added test with the same fingerprint, else the closest one at or
        above :data:`RENAME_SIMILARITY`, else None.
    """
    for new in added:
        if new.fingerprint == old.fingerprint:
            return new
    best, score = None, RENAME_SIMILARITY
    for new in added:
        matcher = difflib.SequenceMatcher(None, old.fingerprint, new.fingerprint)
        if matcher.real_quick_ratio() < score or matcher.quick_ratio() < score:
            continue
        ratio = matcher.ratio()
        if ratio >= score:
            best, score = new, ratio
    return best


def _file_of(node_id: str) -> str:
    """Return the file part of a node id.

    Args:
        node_id: ``path::...``.

    Returns:
        ``path``.
    """
    return node_id.split("::", 1)[0]


def removed(before: list[InventoryEntry], after: list[InventoryEntry]) -> list[str]:
    """Return what ``before`` tests that ``after`` no longer does.

    Args:
        before: The inventory at the base.
        after: The inventory now.

    Returns:
        Node ids of removed tests, and ``node_id[case]`` for each
        parametrize case a surviving or renamed test dropped, sorted. A
        vanished test matches only a test that did not exist at the base, so
        an unchanged sibling with the same body cannot stand in for it. A
        test renamed with small edits to its body counts as renamed, so one
        that lost a single assertion in the same edit is not reported; the
        case comparison still applies to it.
    """
    old_by_id = {e.node_id: e for e in before}
    by_id = {e.node_id: e for e in after}
    added = [e for e in after if e.node_id not in old_by_id]
    # A case counts as moved only into a test that gained it, so an unchanged
    # sibling that happens to share a value cannot hide a deletion.
    gained: dict[str, set[str]] = {}
    for e in after:
        prior = old_by_id.get(e.node_id)
        new_cases = e.cases - prior.cases if prior else e.cases
        gained.setdefault(_file_of(e.node_id), set()).update(new_cases)
    gone: list[str] = []
    for old in before:
        new = by_id.get(old.node_id) or _renamed_to(old, added)
        if new is None:
            gone.append(old.node_id)
            continue
        kept = new.cases | gained.get(_file_of(old.node_id), set())
        gone.extend(f"{old.node_id}[{case}]" for case in sorted(old.cases - kept))
    return sorted(gone)


def _matches(node: str, pattern: str) -> bool:
    """Whether a trailer names a removed test.

    Args:
        node: The removed test's id.
        pattern: The trailer's value.

    Returns:
        True for an exact match, or a match where ``*`` stands for any run of
        characters and ``?`` for one. Brackets are literal: parametrize ids
        contain them, and a glob character class would let one exact trailer
        acknowledge a different test.
    """
    if node == pattern:
        return True
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(regex, node) is not None


def _git(cwd: Path, *args: str) -> str | None:
    """Run git and return its text output, or None when it fails.

    Args:
        cwd: Directory to run in.
        *args: git arguments.

    Returns:
        Standard output, or None on a non-zero exit or a missing git.
    """
    out = _git_bytes(cwd, *args)
    return None if out is None else out.decode("utf-8", errors="replace")


def _git_bytes(cwd: Path, *args: str) -> bytes | None:
    """Run git and return its raw output, or None when it fails.

    Args:
        cwd: Directory to run in.
        *args: git arguments.

    Returns:
        Standard output, or None on a non-zero exit or a missing git.
    """
    try:
        proc = subprocess.run(["git", *args], capture_output=True, cwd=cwd, check=False)
    except FileNotFoundError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _base_candidates() -> list[str]:
    """List the refs whose merge base with HEAD may be the base.

    Returns:
        Ref names, unresolved, most specific first.
    """
    refs: list[str] = []
    if os.environ.get("GITHUB_BASE_REF"):
        refs.append(f"origin/{os.environ['GITHUB_BASE_REF']}")
    refs += ["@{upstream}", "origin/HEAD"]
    return refs


class RemovedTestsCheck(Check):
    """Check that a change does not drop tests without saying so."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "removed-tests"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check for tests deleted since the merge base without a trailer"

    def _merge_base(self) -> tuple[str, str] | None:
        """Find the commit the change started from.

        Returns:
            ``(label, sha)``, or None when nothing resolves.
        """
        explicit = os.environ.get("PREEN_BASE_REF")
        if explicit:
            out = _git(self.project_dir, "merge-base", explicit, "HEAD")
            return (explicit, out.strip()) if out else None
        if os.environ.get("GITHUB_BASE_REF") and _git(
            self.project_dir, "rev-parse", "--verify", "-q", "HEAD^2"
        ):
            # GitHub's pull-request checkout is a merge commit whose first
            # parent is the target it was built against. Reading the target
            # branch's current tip instead would charge the PR with deletions
            # made on the target after the merge commit was created.
            out = _git(self.project_dir, "rev-parse", "HEAD^1")
            if out:
                return "the pull request's target", out.strip()
        for ref in _base_candidates():
            out = _git(self.project_dir, "merge-base", ref, "HEAD")
            if out:
                return ref, out.strip()
        return None

    def _prefix(self) -> str:
        """Return the project directory's path inside the repository.

        Returns:
            ``sub/dir/`` when the project is a subdirectory, else ``""``.
        """
        return (_git(self.project_dir, "rev-parse", "--show-prefix") or "").strip()

    def _base_sources(self, sha: str) -> dict[str, bytes]:
        """Read every test file under the project as it was at a commit.

        Args:
            sha: The commit.

        Returns:
            ``{project_relative_posix_path: source_bytes}``.
        """
        prefix = self._prefix()
        listing = _git(
            self.project_dir, "ls-tree", "-r", "-z", "--full-tree", "--name-only", sha
        )
        out: dict[str, bytes] = {}
        for full in (listing or "").split("\0"):
            if not full or not full.startswith(prefix):
                continue
            name = full[len(prefix) :]
            path = Path(name)
            if is_test_file(path) and not self.is_excluded(path):
                data = _git_bytes(self.project_dir, "show", f"{sha}:{full}")
                if data is not None:
                    out[name] = data
        return out

    def _head_sources(self) -> dict[str, bytes]:
        """Read every test file in the working tree.

        Returns:
            ``{project_relative_posix_path: source_bytes}``.
        """
        out: dict[str, bytes] = {}
        for path in self.project_files():
            if is_test_file(path) and not self.is_excluded(path):
                try:
                    out[path.as_posix()] = (self.project_dir / path).read_bytes()
                except OSError:
                    continue
        return out

    def _acknowledged(self, sha: str) -> list[str]:
        """Collect the ``Removed-test:`` trailers since the base.

        Args:
            sha: The merge base.

        Returns:
            The patterns the trailers name. Git parses the trailers, so a
            line that merely looks like one in the message body does not
            count.
        """
        keys = ",".join(f"key={k}" for k in TRAILER_KEYS)
        log = _git(
            self.project_dir,
            "log",
            f"--format=%(trailers:{keys},valueonly,separator=%x00)%x00",
            f"{sha}..HEAD",
        )
        return [v.strip() for v in (log or "").split("\0") if v.strip()]

    def run(self) -> CheckResult:
        """Compare the test inventory at the base with the working tree.

        Returns:
            CheckResult containing one issue per unacknowledged removal.
        """
        base = self._merge_base()
        if base is None:
            note = Issue(
                check=self.name,
                severity=Severity.INFO,
                description=(
                    "No base to compare against; set PREEN_BASE_REF or fetch "
                    "history (actions/checkout with fetch-depth: 0)"
                ),
                impact=Impact.INFORMATIONAL,
            )
            return CheckResult(check=self.name, passed=True, issues=[note])

        label, sha = base
        before = [
            e
            for p, s in sorted(self._base_sources(sha).items())
            for e in inventory(p, s)
        ]
        after = [
            e for p, s in sorted(self._head_sources().items()) for e in inventory(p, s)
        ]
        patterns = self._acknowledged(sha)
        unexplained = [
            node
            for node in removed(before, after)
            if not any(_matches(node, pat) for pat in patterns)
        ]

        issues = [
            Issue(
                check=self.name,
                severity=Severity.WARNING,
                description=f"{node} was removed since {label} ({sha[:10]})",
                file=Path(_file_of(node)),
                impact=Impact.IMPORTANT,
                explanation=(
                    "Whatever this test pinned is no longer tested. Restore it, "
                    "replace it, or say why in a commit trailer: "
                    f"'Removed-test: {node}'."
                ),
            )
            for node in unexplained
        ]
        return CheckResult(check=self.name, passed=not issues, issues=issues)
