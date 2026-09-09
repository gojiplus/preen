"""Whether a repo meets the Python floor the fleet standard declares.

This check exists because a written standard and an executable checker are two
artifacts that can disagree, and nothing forced them to agree. STANDARD.md has
declared ``requires-python = ">=3.12"`` for some time while 30 of 51 adopted
repos shipped ``>=3.11``, py-canon's own package among them. Every one passed:
the `metadata` check tests only that ``requires-python`` is present and has no
upper bound, and `ci-matrix` reads the floor as an input to validate a matrix
rather than comparing it to anything.

**Off by default, deliberately.** Turning it on before the fleet has migrated
would put thirty repos in violation at once, which is how a check gets
switched off rather than obeyed. Enable it through ``[tool.preen]`` per repo
as each one moves, and flip the default once the campaign is finished.
"""

import time
import tomllib
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .base import Check, CheckResult, Impact, Issue, Severity

#: The floor STANDARD.md declares. Mirrored rather than parsed because the
#: document is prose; preen's own suite asserts the two agree whenever a
#: py-canon checkout is available beside this one.
STANDARD_FLOOR = (3, 12)

#: Every minor release an interpreter could plausibly be, oldest first.
_MINORS = [(2, m) for m in range(8)] + [(3, m) for m in range(40)]


def requires_python(pyproject: Path) -> str | None:
    """Read a repo's requires-python string.

    Args:
        pyproject: Path to the repo's pyproject.toml.

    Returns:
        The raw specifier, or None where none is declared or the file does
        not parse. An unparsable pyproject is the `metadata` check's business,
        not this one's, so it is passed over rather than reported twice.
    """
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    raw = project.get("requires-python")
    return str(raw) if raw else None


def declared_floor(pyproject: Path) -> tuple[int, ...] | None:
    """Work out the oldest minor release a repo's requires-python admits.

    The whole specifier decides, not its first ``>=``: ``>3.10`` still admits
    3.10.1, ``~=3.11`` admits 3.11, and ``>=3.10,>=3.12`` has a floor of 3.12.
    A specifier can only carve at the versions it names, so the probes are
    every named version and the patch after it (an exclusive bound rejects one
    and admits the other), plus ``X.Y`` and a late patch of each minor.

    Args:
        pyproject: Path to the repo's pyproject.toml.

    Returns:
        The floor as a ``(major, minor)`` tuple, or None where none is
        declared, none can be parsed, or nothing is admitted.
    """
    raw = requires_python(pyproject)
    if raw is None:
        return None
    try:
        spec = SpecifierSet(raw)
    except InvalidSpecifier:
        return None
    probes = {Version(f"{major}.{minor}") for major, minor in _MINORS}
    probes |= {Version(f"{major}.{minor}.99") for major, minor in _MINORS}
    for clause in spec:
        try:
            named = Version(clause.version.removesuffix(".*"))
        except InvalidVersion:
            continue
        probes.add(named)
        probes.add(Version(f"{named.major}.{named.minor}.{named.micro + 1}"))
    admitted = sorted(v for v in probes if spec.contains(v))
    return (admitted[0].major, admitted[0].minor) if admitted else None


class PythonFloorCheck(Check):
    """Check a repo's Python floor against the one the standard declares."""

    @property
    def name(self) -> str:
        """Return the name of this check.

        Returns:
            The check name.
        """
        return "python-floor"

    @property
    def description(self) -> str:
        """Return a description of what this check does.

        Returns:
            A one-line description.
        """
        return "Check requires-python meets the floor the fleet standard declares"

    def run(self) -> CheckResult:
        """Run the check.

        Returns:
            The result, flagging a floor below the standard's.
        """
        from ..config import PreenConfig

        started = time.time()
        if not PreenConfig.from_pyproject(self.project_dir).enforce_python_floor:
            return CheckResult(self.name, True, [], time.time() - started)

        pyproject = self.project_dir / "pyproject.toml"
        floor = declared_floor(pyproject)
        want = ".".join(str(p) for p in STANDARD_FLOOR)
        issues = []
        if floor is not None and floor < STANDARD_FLOOR:
            have = ".".join(str(p) for p in floor)
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=(
                        f"requires-python is {requires_python(pyproject)}, which "
                        f"admits Python {have}, below the >={want} the fleet "
                        f"standard declares"
                    ),
                    file=pyproject,
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "A floor below the standard's means the repo is tested "
                        "and resolved against interpreters the fleet no longer "
                        "supports, and it silently widens what its dependents "
                        "must support too."
                    ),
                )
            )
        return CheckResult(self.name, not issues, issues, time.time() - started)
