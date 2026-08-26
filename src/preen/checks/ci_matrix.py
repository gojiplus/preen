"""CI workflow validation: canon shim, or a matrix covering the Python floor."""

import json
import re
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from .base import Check, CheckResult, Impact, Issue, Severity

CANON_SHIM_MARKER = "gojiplus/py-canon/.github/workflows/reusable-ci.yml@"

_FLOOR = re.compile(r">=\s*(\d+)\.(\d+)")

# `uses: owner/repo/path/to/workflow.yml@ref`
_USES = re.compile(
    r"^\s*uses:\s*(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/(?P<path>\.github/workflows/"
    r"[\w.-]+\.ya?ml)@(?P<ref>\S+)\s*$",
    re.MULTILINE,
)

RAW_URL = "https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"

FETCH_TIMEOUT_SECONDS = 10


def _version_key(version: str) -> tuple[int, ...]:
    """Parse a Python version string into a comparable tuple.

    Args:
        version: A version like ``3.12`` or ``3.14.0-rc.1``.

    Returns:
        The numeric components, or an empty tuple when none parse.
    """
    parts = []
    for chunk in str(version).split("."):
        digits = re.match(r"\d+", chunk)
        if digits is None:
            break
        parts.append(int(digits.group()))
    return tuple(parts)


def _parse_versions(declared: object) -> set[str] | None:
    """Normalize a python-versions value into a set of version strings.

    GitHub takes the input as a JSON array in a string; a workflow matrix may
    also carry a plain YAML list or a single scalar.

    Args:
        declared: The raw value.

    Returns:
        The versions, or None when there are none to read.
    """
    if declared is None:
        return None
    if isinstance(declared, str):
        try:
            declared = json.loads(declared)
        except json.JSONDecodeError:
            return {declared} if declared else None
    if isinstance(declared, list):
        versions = {str(entry) for entry in declared if str(entry)}
        return versions or None
    text = str(declared)
    return {text} if text else None


def _workflow_on(document: dict) -> dict:
    """Return a workflow's ``on:`` mapping.

    YAML 1.1 reads a bare ``on`` key as the boolean True, so the trigger block
    of every GitHub workflow is filed under ``True`` rather than ``"on"``.

    Args:
        document: A parsed workflow document.

    Returns:
        The trigger mapping, or an empty dict.
    """
    for key in ("on", True):
        value = document.get(key)
        if isinstance(value, dict):
            return value
    return {}


class CIMatrixCheck(Check):
    """Check that ci.yml is a py-canon shim or covers the requires-python floor."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "ci-matrix"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check ci.yml is a canon shim or its matrix covers the Python floor"

    def run(self) -> CheckResult:
        """Run the CI workflow check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        ci_path = self.project_dir / ".github" / "workflows" / "ci.yml"

        if not ci_path.exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description="No CI workflow found at .github/workflows/ci.yml",
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "Every fleet repo calls the reusable py-canon CI "
                        "workflow; run 'preen adopt' to add the shim."
                    ),
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        content = ci_path.read_text(encoding="utf-8")

        # A canon shim delegates the matrix to the reusable workflow -- but
        # delegating is not the same as being covered. The reusable default is
        # a fixed pair of versions; a repo whose floor sits above the lower one
        # gets a leg `uv sync` cannot resolve, and reporting the shim as green
        # said nothing about that (issue #57).
        if CANON_SHIM_MARKER in content:
            return self._check_shim(ci_path, content)

        floor = self._requires_python_floor()
        if floor is None:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=(
                        "ci.yml is not a py-canon shim and no requires-python "
                        "floor could be determined"
                    ),
                    impact=Impact.INFORMATIONAL,
                )
            )
            return CheckResult(check=self.name, passed=True, issues=issues)

        ci_versions = self._matrix_python_versions(ci_path, issues)
        if issues and any(i.severity == Severity.ERROR for i in issues):
            return CheckResult(check=self.name, passed=False, issues=issues)

        if floor not in ci_versions:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"ci.yml is not a py-canon shim and its matrix "
                        f"{sorted(ci_versions) or '(empty)'} does not test the "
                        f"requires-python floor {floor}"
                    ),
                    file=Path(".github/workflows/ci.yml"),
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "The standard tests the floor and the ceiling; either "
                        "adopt the canon shim ('preen adopt') or add the floor "
                        "to the matrix."
                    ),
                )
            )

        blocking = [i for i in issues if i.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)

    def _check_shim(self, ci_path: Path, content: str) -> CheckResult:
        """Check that a reusable workflow's matrix covers the Python floor.

        Args:
            ci_path: Path to ci.yml.
            content: Its text.

        Returns:
            The check result.
        """
        issues: list[Issue] = []
        floor = self._requires_python_floor()
        if floor is None:
            return CheckResult(check=self.name, passed=True, issues=[])

        versions, source = self._effective_versions(ci_path, content, issues)
        if versions is None:
            return CheckResult(check=self.name, passed=True, issues=issues)

        floor_key = _version_key(floor)
        unresolvable = sorted(
            version
            for version in versions
            if (key := _version_key(version)) is not None and key < floor_key
        )
        if unresolvable:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"ci.yml runs Python {', '.join(unresolvable)} "
                        f"({source}), below the requires-python floor {floor}"
                    ),
                    file=Path(".github/workflows/ci.yml"),
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "Those legs cannot resolve -- 'uv sync' exits 2 -- so "
                        "CI fails for a reason the repo did nothing to cause. "
                        "Pass an explicit python-versions in the shim's 'with' "
                        "block."
                    ),
                )
            )
        elif floor not in versions:
            # Advisory, not blocking. A repo that wrote its own matrix chose
            # both halves of this mismatch, so the non-shim branch below gates
            # on it. A shim inherits its matrix from py-canon, and canon
            # raising its default -- as v1.2.0 did, to 3.12 -- would otherwise
            # turn every repo still declaring a 3.11 floor red on the same day,
            # for a change none of them made. CI is green here; only the floor
            # claim is unverified.
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=(
                        f"ci.yml tests {sorted(versions)} ({source}) but never "
                        f"the requires-python floor {floor}"
                    ),
                    file=Path(".github/workflows/ci.yml"),
                    impact=Impact.INFORMATIONAL,
                    explanation=(
                        "Nothing verifies that the package installs on "
                        f"{floor}. Either raise requires-python to "
                        f"{min(sorted(versions))}, or pass an explicit "
                        "python-versions in the shim's 'with' block."
                    ),
                )
            )

        blocking = [issue for issue in issues if issue.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)

    def _effective_versions(
        self, ci_path: Path, content: str, issues: list[Issue]
    ) -> tuple[set[str] | None, str]:
        """Return the Python versions the shim actually runs.

        An explicit ``python-versions`` input wins; otherwise the reusable
        workflow's own default decides, and that lives in the other repo.

        Args:
            ci_path: Path to ci.yml.
            content: Its text.
            issues: List to append an INFO note to when the answer is unknown.

        Returns:
            The versions and a short phrase naming where they came from, or
            ``(None, "")`` when they could not be determined.
        """
        try:
            with ci_path.open("r", encoding="utf-8") as handle:
                workflow = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"Failed to parse CI workflow: {exc}",
                    impact=Impact.CRITICAL,
                )
            )
            return None, ""

        for job in (workflow.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            declared = (job.get("with") or {}).get("python-versions")
            parsed = _parse_versions(declared)
            if parsed:
                return parsed, "declared in the shim"

        match = _USES.search(content)
        if match is None:
            return None, ""

        default = self._reusable_default(match.groupdict())
        if default is None:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=(
                        "Could not read the reusable workflow's default "
                        f"python-versions from {match.group('owner')}/"
                        f"{match.group('repo')}@{match.group('ref')}; skipping "
                        "the floor-coverage comparison"
                    ),
                    impact=Impact.INFORMATIONAL,
                )
            )
            return None, ""
        return default, f"the reusable default at {match.group('ref')}"

    def _reusable_default(self, ref: dict[str, str]) -> set[str] | None:
        """Fetch a reusable workflow's default ``python-versions`` input.

        Args:
            ref: The owner/repo/path/ref groups from the ``uses:`` line.

        Returns:
            The default versions, or None when the workflow cannot be read.
        """
        url = RAW_URL.format(**ref)
        try:
            with urllib.request.urlopen(  # noqa: S310 -- https literal above
                url, timeout=FETCH_TIMEOUT_SECONDS
            ) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, OSError, UnicodeDecodeError, ValueError):
            return None

        try:
            document = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            return None
        if not isinstance(document, dict):
            return None

        inputs = (_workflow_on(document).get("workflow_call") or {}).get("inputs") or {}
        declared = (inputs.get("python-versions") or {}).get("default")
        return _parse_versions(declared)

    def _requires_python_floor(self) -> str | None:
        """Return the requires-python floor (e.g. '3.11'), or None if unknown."""
        pyproject_path = self.project_dir / "pyproject.toml"
        if not pyproject_path.exists():
            return None
        try:
            with pyproject_path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return None
        requires = data.get("project", {}).get("requires-python", "")
        match = _FLOOR.search(requires)
        if not match:
            return None
        return f"{match.group(1)}.{match.group(2)}"

    def _matrix_python_versions(self, ci_path: Path, issues: list[Issue]) -> set[str]:
        """Extract all python-version matrix entries from the workflow.

        Args:
            ci_path: Path to the ci.yml workflow file.
            issues: Issue list to append parse errors to.

        Returns:
            Set of python versions found in any job's matrix.
        """
        versions: set[str] = set()
        try:
            with ci_path.open("r", encoding="utf-8") as f:
                workflow = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"Failed to parse CI workflow: {exc}",
                    impact=Impact.CRITICAL,
                )
            )
            return versions

        for job in (workflow.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            matrix = ((job.get("strategy") or {}).get("matrix")) or {}
            raw = matrix.get("python-version", [])
            if isinstance(raw, list):
                versions.update(str(v) for v in raw)
            elif raw:
                versions.add(str(raw))
        return versions
