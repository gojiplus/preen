"""Dependency vulnerability check using pip-audit.

Complements the `deps` check (unused/missing dependencies via deptry):
deptry doesn't look at known CVEs, pip-audit does. This check exports the
project's locked, pinned dependency set with `uv export` and scans it with
pip-audit. The export covers every dependency group and every optional extra:
an extra ships to users (`pip install pkg[web]`), so a package that arrives
only through one is as much the project's exposure as a core dependency.
"""

import json
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

from ..config import PreenConfig
from .base import Check, CheckResult, Impact, Issue, Severity

#: No existing subprocess check in this project sets an explicit timeout;
#: fall back to a generous 120s so a hung network call can't wedge `preen check`.
TIMEOUT_SECONDS = 120

#: Substrings marking a requirements-txt line as a direct VCS/URL/local-path
#: reference rather than a plain PyPI pin. `pip-audit --disable-pip` needs a
#: hash to verify against, which these forms can't provide.
_NON_PYPI_MARKERS = ("@ git+", "@ file:", "@ http")

_EGG_FRAGMENT_RE = re.compile(r"#egg=([A-Za-z0-9._-]+)")
_REQUIREMENT_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _is_non_pypi_requirement(first_line: str) -> bool:
    """Return True if a requirement's first line is a direct/VCS/local ref."""
    stripped = first_line.strip()
    if stripped.startswith("-e "):
        return True
    return any(marker in stripped for marker in _NON_PYPI_MARKERS)


def _requirement_name(first_line: str) -> str:
    """Best-effort package name for a requirement's first line."""
    spec = first_line.split("\\", 1)[0].strip()
    if spec.startswith("-e "):
        spec = spec[3:].strip()
        egg_match = _EGG_FRAGMENT_RE.search(spec)
        return egg_match.group(1) if egg_match else spec
    if " @ " in spec:
        return spec.split(" @ ", 1)[0].strip()
    name_match = _REQUIREMENT_NAME_RE.match(spec)
    return name_match.group(1) if name_match else spec


def _split_requirement_blocks(text: str) -> list[list[str]]:
    """Group exported requirements-txt lines into logical blocks.

    Each top-level requirement line is grouped with any indented
    continuation lines that follow it (e.g. `--hash=...` entries from
    a backslash-continued line). Comment and blank lines each stand alone.
    """
    lines = text.splitlines()
    blocks: list[list[str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.startswith("#") or line[0].isspace():
            blocks.append([line])
            i += 1
            continue
        block = [line]
        i += 1
        while i < len(lines) and lines[i] and lines[i][0].isspace():
            block.append(lines[i])
            i += 1
        blocks.append(block)
    return blocks


def _filter_pypi_requirements(text: str) -> tuple[str, list[str]]:
    """Drop non-PyPI-auditable requirement lines (VCS/local/direct-URL refs).

    Args:
        text: Exported requirements-txt content (e.g. from `uv export`).

    Returns:
        A tuple of the filtered requirements-txt content and the names of
        the packages dropped, in encounter order.
    """
    kept_lines: list[str] = []
    dropped: list[str] = []
    for block in _split_requirement_blocks(text):
        first_line = block[0]
        is_requirement_start = (
            first_line.strip()
            and not first_line.startswith("#")
            and not first_line[0].isspace()
        )
        if is_requirement_start and _is_non_pypi_requirement(first_line):
            dropped.append(_requirement_name(first_line))
            continue
        kept_lines.extend(block)
    return "\n".join(kept_lines) + "\n", dropped


def _extras_selections(project_dir: Path) -> tuple[list[list[str]], bool]:
    """Choose the `uv export` extras flags that cover every extra.

    uv refuses ``--all-extras`` when ``[tool.uv] conflicts`` declares two
    extras as conflicting, since no single environment can hold both. Such
    a project is exported one extra at a time.

    Args:
        project_dir: The project whose pyproject.toml declares the extras.

    Returns:
        The extras flags for each export, and whether they are per-extra.
    """
    try:
        with (project_dir / "pyproject.toml").open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    extras = data.get("project", {}).get("optional-dependencies", {})
    conflicts = data.get("tool", {}).get("uv", {}).get("conflicts", [])
    conflicting = isinstance(conflicts, list) and any(
        isinstance(item, dict) and "extra" in item
        for conflict in conflicts
        if isinstance(conflict, list)
        for item in conflict
    )
    if conflicting and isinstance(extras, dict) and extras:
        return [["--extra", name] for name in sorted(extras)], True
    return [["--all-extras"]], False


def _merge_dependencies(reports: list[list]) -> list:
    """Concatenate pip-audit dependency lists, keeping one entry per pin.

    Exports taken one extra at a time repeat the core dependencies; without
    this a vulnerable core pin would be reported once per extra.
    """
    seen: set[tuple[str, str]] = set()
    merged = []
    for dependencies in reports:
        for dependency in dependencies:
            if isinstance(dependency, dict):
                key = (str(dependency.get("name")), str(dependency.get("version")))
                if key in seen:
                    continue
                seen.add(key)
            merged.append(dependency)
    return merged


class AuditCheck(Check):
    """Check locked dependencies for known vulnerabilities using pip-audit."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "audit"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check locked dependencies for known vulnerabilities with pip-audit"

    def run(self) -> CheckResult:
        """Run pip-audit over the project's exported, locked dependencies."""
        if not (self.project_dir / "uv.lock").exists():
            return self._skip(
                "No uv.lock found; pip-audit needs a locked, pinned "
                "dependency set to scan. Skipping audit."
            )

        selections, per_extra = _extras_selections(self.project_dir)

        exports: list[str] = []
        for selection in selections:
            requirements, stderr = self._export_requirements(selection)
            if requirements is not None:
                exports.append(requirements)
            elif per_extra:
                # An extra that won't export is an extra left unscanned, and
                # an info-level skip would let `--strict` pass it unseen.
                return self._export_failed(selection, stderr)
            else:
                return self._skip(
                    "Could not export requirements with `uv export`; skipping audit."
                )

        pip_audit_cmd = self._find_pip_audit()
        if pip_audit_cmd is None:
            return self._skip(
                "pip-audit is not installed. Install with: pip install pip-audit"
            )

        reports: list[list] = []
        dropped: list[str] = []
        for requirements in exports:
            filtered_requirements, export_dropped = _filter_pypi_requirements(
                requirements
            )
            dropped.extend(n for n in export_dropped if n not in dropped)
            dependencies = self._run_pip_audit(pip_audit_cmd, filtered_requirements)
            if dependencies is None:
                return self._skip("pip-audit could not complete; skipping audit.")
            reports.append(dependencies)
        dependencies = _merge_dependencies(reports)

        configured = PreenConfig.from_pyproject(self.project_dir).audit_ignore
        vuln_issues, ignored, matched = self._issues_from_dependencies(
            dependencies, {i.lower() for i in configured}
        )
        issues = list(vuln_issues)
        if ignored:
            issues.append(self._ignored_issue(ignored))
        # An entry that matched nothing is the signal the comment next to it
        # promised: upstream shipped a fix, or the package left the lock, and
        # the exception can go.
        stale = sorted(i for i in configured if i.lower() not in matched)
        if stale:
            issues.append(self._stale_ignore_issue(stale))
        if dropped:
            issues.append(self._dropped_issue(dropped))

        # Only actual vulnerabilities fail the check; the informational
        # "couldn't scan this one" note doesn't.
        return CheckResult(check=self.name, passed=len(vuln_issues) == 0, issues=issues)

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False  # Bumping a vulnerable dependency requires manual review

    def _export_requirements(self, selection: list[str]) -> tuple[str | None, str]:
        """Export the project's locked dependencies as pinned requirements.

        Args:
            selection: The extras flags to pass, ``["--all-extras"]`` or
                ``["--extra", name]``.

        Returns:
            The exported requirements-txt content, or None if `uv` is
            unavailable or the export fails; and uv's stderr.
        """
        try:
            result = subprocess.run(
                [
                    "uv",
                    "export",
                    "--format",
                    "requirements-txt",
                    "--no-emit-project",
                    "--all-groups",
                    *selection,
                ],
                capture_output=True,
                text=True,
                cwd=self.project_dir,
                timeout=TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError) as error:
            return None, str(error)

        if result.returncode != 0:
            return None, result.stderr or ""
        return result.stdout, result.stderr or ""

    def _run_pip_audit(
        self, pip_audit_cmd: list[str], requirements: str
    ) -> list | None:
        """Scan one requirements export with pip-audit.

        Args:
            pip_audit_cmd: The command prefix from `_find_pip_audit`.
            requirements: Filtered requirements-txt content.

        Returns:
            The report's ``"dependencies"`` list, or None if pip-audit did not
            produce a usable report.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements_path = Path(tmpdir) / "requirements.txt"
            requirements_path.write_text(requirements)

            try:
                result = subprocess.run(
                    [
                        *pip_audit_cmd,
                        "-r",
                        str(requirements_path),
                        "--disable-pip",
                        "--format",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=self.project_dir,
                    timeout=TIMEOUT_SECONDS,
                )
            except (subprocess.SubprocessError, OSError):
                return None

        # 0: no vulnerabilities. 1: vulnerabilities found (with valid JSON on
        # stdout). Anything else is a genuine failure (network, bad
        # invocation) -- degrade gracefully rather than crash.
        if result.returncode not in (0, 1):
            return None

        # A real report is always non-empty JSON (pip-audit prints
        # `{"dependencies": [...], "fixes": []}` even when there's nothing to
        # flag). Empty or unparsable stdout means pip-audit errored before
        # producing a report (e.g. a requirement it couldn't resolve).
        if not result.stdout.strip():
            return None
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

        if not isinstance(report, dict):
            return None

        dependencies = report.get("dependencies")
        if not isinstance(dependencies, list):
            return None
        return dependencies

    def _find_pip_audit(self) -> list[str] | None:
        """Locate a runnable pip-audit command, trying `uvx` as a fallback.

        Returns:
            The command prefix to invoke pip-audit with, or None if it
            can't be found or run either directly or via `uvx`.
        """
        try:
            subprocess.run(
                ["pip-audit", "--version"],
                capture_output=True,
                check=True,
                cwd=self.project_dir,
                timeout=TIMEOUT_SECONDS,
            )
            return ["pip-audit"]
        except (subprocess.SubprocessError, OSError):
            pass

        try:
            subprocess.run(
                ["uvx", "--version"],
                capture_output=True,
                check=True,
                cwd=self.project_dir,
                timeout=TIMEOUT_SECONDS,
            )
            return ["uvx", "pip-audit"]
        except (subprocess.SubprocessError, OSError):
            return None

    def _issues_from_dependencies(
        self, dependencies: list, ignored_ids: frozenset[str] | set[str] = frozenset()
    ) -> tuple[list[Issue], list[str], set[str]]:
        """Build an Issue per vulnerable dependency from a pip-audit report.

        Args:
            dependencies: The `"dependencies"` list from a pip-audit JSON
                report. Non-dict entries are skipped rather than raising.
            ignored_ids: Advisory ids from ``[tool.preen] audit_ignore``,
                lower-cased. A vulnerability whose primary id or any alias is
                listed does not produce an Issue; it is reported back so the
                caller can note it. pip-audit names one advisory several
                ways, PYSEC as the id with the GHSA and CVE in ``aliases``
                for the same finding, and a repo will write down whichever
                it read, in whatever case it read it.

        Returns:
            One Issue per vulnerable dependency; the list of
            ``"<package> <version>: <id>"`` strings that were ignored, where
            the id is the one the configuration matched; and the lower-cased
            configured ids that matched something.
        """
        issues = []
        ignored: list[str] = []
        matched_ids: set[str] = set()
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue

            name = dependency.get("name", "<unknown>")
            version = dependency.get("version", "<unknown>")
            vulns = []
            for vuln in dependency.get("vulns", []):
                # pip-audit emits aliases as a list, but a report is data from
                # outside: null or a bare string must not crash the check.
                aliases = vuln.get("aliases")
                names = [
                    vuln.get("id"),
                    *(aliases if isinstance(aliases, list) else []),
                ]
                hits = [
                    n for n in names if isinstance(n, str) and n.lower() in ignored_ids
                ]
                if hits:
                    # Report under the first configured name; credit every
                    # configured name, or a repo that listed both the PYSEC
                    # and the GHSA would be told one of them is stale.
                    ignored.append(f"{name} {version}: {hits[0]}")
                    matched_ids.update(h.lower() for h in hits)
                else:
                    vulns.append(vuln)
            if not vulns:
                continue

            vuln_ids = ", ".join(vuln.get("id", "") for vuln in vulns if vuln.get("id"))
            fix_versions = sorted(
                {fv for vuln in vulns for fv in vuln.get("fix_versions", [])}
            )

            description = f"{name} {version} has known vulnerabilities"
            if vuln_ids:
                description += f": {vuln_ids}"
            if fix_versions:
                description += f" (fix available: {', '.join(fix_versions)})"

            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=description,
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "pip-audit found known vulnerabilities in a locked "
                        "dependency. Bump the dependency to a fixed version "
                        "and re-lock (`uv lock --upgrade-package "
                        f"{name}`)."
                    ),
                )
            )
        return issues, ignored, matched_ids

    def _stale_ignore_issue(self, entries: list[str]) -> Issue:
        """Build the info issue naming audit_ignore entries that matched nothing."""
        return Issue(
            check=self.name,
            severity=Severity.INFO,
            description=(
                "audit_ignore entries that match no advisory in the lock: "
                f"{', '.join(entries)}"
            ),
            impact=Impact.INFORMATIONAL,
            explanation=(
                "Usually upstream shipped a fix and the lock moved past the "
                "advisory, or the package left the lock. Remove the entry so "
                "the check gates on that advisory again if it returns."
            ),
        )

    def _ignored_issue(self, entries: list[str]) -> Issue:
        """Build the info issue naming advisories ignored by configuration."""
        return Issue(
            check=self.name,
            severity=Severity.INFO,
            description=(
                f"ignored per [tool.preen] audit_ignore: {', '.join(entries)}"
            ),
            impact=Impact.INFORMATIONAL,
            explanation=(
                "These advisories are listed in audit_ignore, usually because "
                "no fixed release exists yet. Remove the entry once upstream "
                "ships a fix so the check gates on it again."
            ),
        )

    def _dropped_issue(self, names: list[str]) -> Issue:
        """Build the info issue naming packages dropped from the scan."""
        joined = ", ".join(names)
        verb = "is" if len(names) == 1 else "are"
        return Issue(
            check=self.name,
            severity=Severity.INFO,
            description=f"{joined} {verb} not auditable (non-PyPI source), skipped",
            impact=Impact.INFORMATIONAL,
            explanation=(
                "pip-audit (run with --disable-pip) needs a hash to verify "
                "each requirement against, which direct VCS/URL/local-path "
                "references can't provide. These dependencies were excluded "
                "from the scan; audit them manually if needed."
            ),
        )

    def _export_failed(self, selection: list[str], stderr: str) -> CheckResult:
        """Build the failing result for an extra that would not export."""
        detail = stderr.strip().splitlines()[-1] if stderr.strip() else ""
        description = f"`uv export {' '.join(selection)}` failed"
        if detail:
            description += f": {detail}"
        return CheckResult(
            check=self.name,
            passed=False,
            issues=[
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=description,
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "[tool.uv] conflicts declares conflicting extras, so "
                        "each extra is exported and audited on its own. This "
                        "one could not be exported, so its dependencies went "
                        "unscanned."
                    ),
                )
            ],
        )

    def _skip(self, message: str) -> CheckResult:
        """Build a CheckResult for a graceful no-op with a single info issue."""
        return CheckResult(
            check=self.name,
            passed=False,
            issues=[
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=message,
                    impact=Impact.INFORMATIONAL,
                )
            ],
        )
