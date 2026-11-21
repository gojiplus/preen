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

The check compares the test inventory at the merge base with the working
tree. The inventory holds every ``test_*`` function and method, plus every
case of a ``pytest.mark.parametrize`` whose values are a literal list. A test
whose body reappears under another name or file counts as renamed, not
removed. A removal passes when a commit since the merge base carries a
trailer naming it, which may be an fnmatch pattern::

    Removed-test: tests/test_lit.py::test_redirects_are_rechecked
    Removed-test: tests/test_old.py::*

The trailer is the point: deleting a test stays cheap, and the reason for it
is written down where a reviewer reads it.

The base is ``$PREEN_BASE_REF``, else ``origin/$GITHUB_BASE_REF`` (set on
pull requests), else the branch's upstream, else ``origin/HEAD``. When none
resolves, for example in a shallow clone, the check says so and passes.
"""

import ast
import difflib
import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

TRAILER = re.compile(
    r"^Removed-tests?:[ \t]*(.+?)[ \t]*$", re.IGNORECASE | re.MULTILINE
)

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
        cases: ``argnames=value`` keys for each literal parametrize case.
    """

    node_id: str
    fingerprint: str
    cases: frozenset[str]


def _parametrize_cases(func: FuncDef) -> frozenset[str]:
    """List the literal cases of every parametrize decorator on a test.

    Args:
        func: The test function.

    Returns:
        One ``argnames=value`` key per case, written with ``ast.unparse`` so
        reformatting does not change it. Values that are not a literal list
        or tuple contribute nothing, since they cannot be read statically.
    """
    cases: set[str] = set()
    for deco in func.decorator_list:
        if not isinstance(deco, ast.Call) or not deco.args:
            continue
        target = deco.func
        if not (isinstance(target, ast.Attribute) and target.attr == "parametrize"):
            continue
        first = deco.args[0]
        names = (
            first.value
            if isinstance(first, ast.Constant) and isinstance(first.value, str)
            else ast.unparse(first)
        )
        values = deco.args[1] if len(deco.args) > 1 else None
        for kw in deco.keywords:
            if kw.arg == "argvalues":
                values = kw.value
        if isinstance(values, ast.List | ast.Tuple):
            cases.update(f"{names}={ast.unparse(v)}" for v in values.elts)
    return frozenset(cases)


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


def inventory(path: str, source: str) -> list[InventoryEntry]:
    """List the tests a module defines.

    Args:
        path: The module's project-relative path, in POSIX form.
        source: Its contents.

    Returns:
        Module-level ``test*`` functions and ``test*`` methods of ``Test*``
        classes, nested classes included. A file that does not parse yields
        nothing; the test run reports it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[InventoryEntry] = []

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, FuncDef) and node.name.startswith("test"):
                found.append(
                    InventoryEntry(
                        f"{prefix}::{node.name}",
                        _fingerprint(node),
                        _parametrize_cases(node),
                    )
                )
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                visit(node.body, f"{prefix}::{node.name}")

    visit(tree.body, path)
    return found


#: How alike two bodies must be for a vanished test to count as renamed.
#: A rename that also renames a variable (``per_km`` to ``per_mile``)
#: scores about 0.97; replacing what a test checks scores well below this.
RENAME_SIMILARITY = 0.8


def _renamed_to(
    old: InventoryEntry, added: list[InventoryEntry]
) -> InventoryEntry | None:
    """Find the new test a vanished one most plausibly became.

    Args:
        old: A test whose id no longer exists.
        added: Tests whose ids did not exist at the base.

    Returns:
        The closest added test at or above :data:`RENAME_SIMILARITY`, or
        None.
    """
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
        parametrize case a surviving or renamed test dropped, sorted. A test
        renamed with small edits to its body counts as renamed, so one that
        lost a single assertion in the same edit is not reported; the case
        comparison still applies to it.
    """
    old_ids = {e.node_id for e in before}
    by_id = {e.node_id: e for e in after}
    by_print: dict[str, InventoryEntry] = {}
    for e in after:
        by_print.setdefault(e.fingerprint, e)
    added = [e for e in after if e.node_id not in old_ids]
    # A case that moved to a sibling test in the same file is still tested.
    # Comparing only against the matched test misread a split of one
    # parametrized test into two as the loss of every case.
    file_cases: dict[str, frozenset[str]] = {}
    for e in after:
        path = _file_of(e.node_id)
        file_cases[path] = file_cases.get(path, frozenset()) | e.cases
    gone: list[str] = []
    for old in before:
        new = by_id.get(old.node_id) or by_print.get(old.fingerprint)
        if new is None:
            new = _renamed_to(old, added)
        if new is None:
            gone.append(old.node_id)
            continue
        kept = new.cases | file_cases.get(_file_of(old.node_id), frozenset())
        gone.extend(f"{old.node_id}[{case}]" for case in sorted(old.cases - kept))
    return sorted(gone)


def _matches(node: str, pattern: str) -> bool:
    """Whether a trailer names a removed test.

    Args:
        node: The removed test's id.
        pattern: The trailer's value.

    Returns:
        True for an exact match, or an fnmatch match. Exact comes first
        because a parametrize id contains brackets, which fnmatch reads as a
        character class.
    """
    return node == pattern or fnmatch.fnmatchcase(node, pattern)


def _git(cwd: Path, *args: str) -> str | None:
    """Run git and return its output, or None when it fails.

    Args:
        cwd: Directory to run in.
        *args: git arguments.

    Returns:
        Standard output, or None on a non-zero exit or a missing git.
    """
    try:
        proc = subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=cwd, check=False
        )
    except FileNotFoundError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _base_candidates() -> list[str]:
    """List the refs to compare against, most specific first.

    Returns:
        Ref names, unresolved.
    """
    refs: list[str] = []
    if os.environ.get("PREEN_BASE_REF"):
        refs.append(os.environ["PREEN_BASE_REF"])
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
            ``(ref, sha)`` for the first candidate that resolves, or None.
        """
        for ref in _base_candidates():
            out = _git(self.project_dir, "merge-base", ref, "HEAD")
            if out:
                return ref, out.strip()
        return None

    def _base_sources(self, sha: str) -> dict[str, str]:
        """Read every test file as it was at a commit.

        Args:
            sha: The commit.

        Returns:
            ``{posix_path: source}``.
        """
        listing = _git(self.project_dir, "ls-tree", "-r", "-z", "--name-only", sha)
        out: dict[str, str] = {}
        for name in (listing or "").split("\0"):
            path = Path(name)
            if name and is_test_file(path) and not self.is_excluded(path):
                text = _git(self.project_dir, "show", f"{sha}:{name}")
                if text is not None:
                    out[name] = text
        return out

    def _head_sources(self) -> dict[str, str]:
        """Read every test file in the working tree.

        Returns:
            ``{posix_path: source}``.
        """
        out: dict[str, str] = {}
        for path in self.project_files():
            if is_test_file(path) and not self.is_excluded(path):
                try:
                    out[path.as_posix()] = (self.project_dir / path).read_text(
                        encoding="utf-8"
                    )
                except (OSError, UnicodeDecodeError):
                    continue
        return out

    def _acknowledged(self, sha: str) -> list[str]:
        """Collect the ``Removed-test:`` trailers since the base.

        Args:
            sha: The merge base.

        Returns:
            The patterns the trailers name.
        """
        log = _git(self.project_dir, "log", "--format=%B", f"{sha}..HEAD") or ""
        return TRAILER.findall(log)

    def run(self) -> CheckResult:
        """Compare the test inventory at the merge base with the working tree.

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

        ref, sha = base
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
                description=f"{node} was removed since {ref} ({sha[:10]})",
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
