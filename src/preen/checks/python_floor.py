"""Whether a repo meets the Python floor the fleet standard declares.

This check exists because a written standard and an executable checker are two
artefacts that can disagree, and nothing forced them to agree. STANDARD.md has
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

import re
import time
import tomllib
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

#: The floor STANDARD.md declares. Mirrored rather than parsed because the
#: document is prose; preen's own suite asserts the two agree whenever a
#: py-canon checkout is available beside this one.
STANDARD_FLOOR = (3, 12)

_FLOOR = re.compile(r">=\s*(\d+)\.(\d+)")


def declared_floor(pyproject: Path) -> tuple[int, ...] | None:
    """Read the lower bound from a repo's requires-python.

    Args:
        pyproject: Path to the repo's pyproject.toml.

    Returns:
        The floor as a version tuple, or None where none is declared or the
        file does not parse. An unparsable pyproject is the `metadata`
        check's business, not this one's, so it is passed over rather than
        reported twice.
    """
    try:
        data = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    match = _FLOOR.search(str(data.get("project", {}).get("requires-python", "")))
    return (int(match.group(1)), int(match.group(2))) if match else None


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
                        f"requires-python is >={have}, below the >={want} the "
                        f"fleet standard declares"
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
