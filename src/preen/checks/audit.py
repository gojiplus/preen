"""Dependency vulnerability check using pip-audit.

Complements the `deps` check (unused/missing dependencies via deptry):
deptry doesn't look at known CVEs, pip-audit does. This check exports the
project's locked, pinned dependency set with `uv export` and scans it with
pip-audit.
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path

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

        requirements = self._export_requirements()
        if requirements is None:
            return self._skip(
                "Could not export requirements with `uv export`; skipping audit."
            )

        pip_audit_cmd = self._find_pip_audit()
        if pip_audit_cmd is None:
            return self._skip(
                "pip-audit is not installed. Install with: pip install pip-audit"
            )

        filtered_requirements, dropped = _filter_pypi_requirements(requirements)

        with tempfile.TemporaryDirectory() as tmpdir:
            requirements_path = Path(tmpdir) / "requirements.txt"
            requirements_path.write_text(filtered_requirements)

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
                return self._skip("pip-audit could not complete; skipping audit.")

        # 0: no vulnerabilities. 1: vulnerabilities found (with valid JSON on
        # stdout). Anything else is a genuine failure (network, bad
        # invocation) -- degrade gracefully rather than crash.
        if result.returncode not in (0, 1):
            return self._skip("pip-audit could not complete; skipping audit.")

        # A real report is always non-empty JSON (pip-audit prints
        # `{"dependencies": [...], "fixes": []}` even when there's nothing to
        # flag). Empty or unparsable stdout means pip-audit errored before
        # producing a report (e.g. a requirement it couldn't resolve).
        if not result.stdout.strip():
            return self._skip("pip-audit could not complete; skipping audit.")
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            return self._skip("pip-audit could not complete; skipping audit.")

        if not isinstance(report, dict):
            return self._skip("pip-audit could not complete; skipping audit.")

        dependencies = report.get("dependencies")
        if not isinstance(dependencies, list):
            return self._skip("pip-audit could not complete; skipping audit.")

        vuln_issues = self._issues_from_dependencies(dependencies)
        issues = list(vuln_issues)
        if dropped:
            issues.append(self._dropped_issue(dropped))

        # Only actual vulnerabilities fail the check; the informational
        # "couldn't scan this one" note doesn't.
        return CheckResult(check=self.name, passed=len(vuln_issues) == 0, issues=issues)

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return False  # Bumping a vulnerable dependency requires manual review

    def _export_requirements(self) -> str | None:
        """Export the project's locked dependencies as pinned requirements.

        Returns:
            The exported requirements-txt content, or None if `uv` is
            unavailable or the export fails.
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
                ],
                capture_output=True,
                text=True,
                cwd=self.project_dir,
                timeout=TIMEOUT_SECONDS,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        if result.returncode != 0:
            return None
        return result.stdout

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

    def _issues_from_dependencies(self, dependencies: list) -> list[Issue]:
        """Build an Issue per vulnerable dependency from a pip-audit report.

        Args:
            dependencies: The `"dependencies"` list from a pip-audit JSON
                report. Non-dict entries are skipped rather than raising.

        Returns:
            One Issue per vulnerability found across all dependencies.
        """
        issues = []
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue

            vulns = dependency.get("vulns", [])
            if not vulns:
                continue

            name = dependency.get("name", "<unknown>")
            version = dependency.get("version", "<unknown>")
            vuln_ids = ", ".join(vuln.get("id", "") for vuln in vulns if vuln.get("id"))
            fix_versions = sorted(
                {fv for vuln in vulns for fv in vuln.get("fix_versions", [])}
            )

            description = f"{name} {version} has known vulnerabilities: {vuln_ids}"
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
        return issues

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
