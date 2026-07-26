"""PEP 639 `license` metadata check.

Flags the legacy TOML-table license form, structurally invalid or
unrecognized SPDX expressions, redundant ``License ::`` trove classifiers,
and a missing ``license-files`` declaration when a license file exists.
"""

import re
import tomllib
from pathlib import Path

import tomlkit

from .base import Check, CheckResult, Fix, Impact, Issue, Severity

# A small allowlist of common OSI-approved SPDX identifiers. Not a full SPDX
# database -- unknown identifiers are only flagged as advisory, not failed.
SPDX_ALLOWLIST = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "MPL-2.0",
        "ISC",
        "Unlicense",
        "0BSD",
        "CC0-1.0",
        "BSL-1.0",
        "Zlib",
        "PSF-2.0",
    }
)

# Legacy free-text spellings that map unambiguously to an SPDX identifier.
# Anything not listed here (e.g. "BSD", which could be 2- or 3-clause) is
# left for a human to resolve.
LEGACY_TEXT_ALIASES = {
    "MIT License": "MIT",
    "Apache 2.0": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
}

LICENSE_FILE_STEMS = ("license", "licence", "copying")

# The operator alternatives need a trailing word-boundary guard, or an
# identifier that merely starts with one (a hypothetical "ANDover-1.0") would
# be split into an operator plus a stray identifier.
_SPDX_TOKEN_RE = re.compile(
    r"\(|\)|(?:AND|OR|WITH)(?![A-Za-z0-9.+-])|[A-Za-z0-9][A-Za-z0-9.+-]*"
)


def _tokenize_spdx(expression: str) -> list[str] | None:
    """Tokenize an SPDX expression, or return None on an invalid character."""
    text = expression.strip()
    if not text:
        return None
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        match = _SPDX_TOKEN_RE.match(text, pos)
        if not match:
            return None
        tokens.append(match.group())
        pos = match.end()
    return tokens or None


def _is_structurally_valid(symbols: list[str]) -> bool:
    """Check symbols form a well-parenthesized AND/OR/WITH expression."""
    depth = 0
    expect_operand = True
    for symbol in symbols:
        if symbol == "(":
            if not expect_operand:
                return False
            depth += 1
        elif symbol == ")":
            if expect_operand or depth == 0:
                return False
            depth -= 1
        elif symbol in ("AND", "OR", "WITH"):
            if expect_operand:
                return False
            expect_operand = True
        else:
            if not expect_operand:
                return False
            expect_operand = False
    return depth == 0 and not expect_operand


def _license_identifiers(symbols: list[str]) -> list[str]:
    """Return license identifier symbols, skipping SPDX exception ids after WITH."""
    identifiers = []
    previous = None
    for symbol in symbols:
        if symbol not in ("(", ")", "AND", "OR", "WITH") and previous != "WITH":
            identifiers.append(symbol)
        previous = symbol
    return identifiers


def _resolve_legacy_text(text: str) -> str | None:
    """Return the SPDX id a legacy free-text license value maps to, if any."""
    normalized = text.strip()
    if normalized in SPDX_ALLOWLIST:
        return normalized
    return LEGACY_TEXT_ALIASES.get(normalized)


class LicenseCheck(Check):
    """Check `[project].license` metadata follows PEP 639."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "license"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check PEP 639 license metadata"

    def run(self) -> CheckResult:
        """Run the license check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        pyproject_path = self.project_dir / "pyproject.toml"
        if not pyproject_path.exists():
            return CheckResult(check=self.name, passed=True, issues=issues)

        try:
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            # Malformed TOML is another check's concern.
            return CheckResult(check=self.name, passed=True, issues=issues)

        project = data.get("project", {})
        license_value = project.get("license")

        if license_value is None:
            issues.append(self._missing_license_issue(pyproject_path))
        elif isinstance(license_value, dict):
            issues.append(self._table_form_issue(license_value, pyproject_path))
        elif isinstance(license_value, str):
            issue = self._string_form_issue(license_value, pyproject_path)
            if issue is not None:
                issues.append(issue)

        classifiers = project.get("classifiers", [])
        license_classifiers = [
            c for c in classifiers if isinstance(c, str) and c.startswith("License ::")
        ]
        if license_classifiers and license_value is not None:
            issues.append(self._classifier_issue(license_classifiers, pyproject_path))

        if "license-files" not in project:
            license_file = self._find_license_file()
            if license_file is not None:
                issues.append(
                    self._license_files_missing_issue(license_file, pyproject_path)
                )

        return CheckResult(check=self.name, passed=not issues, issues=issues)

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues."""
        return True

    # -- finding builders --------------------------------------------------

    def _missing_license_issue(self, pyproject_path: Path) -> Issue:
        """Build the issue for a `[project]` with no `license` at all."""
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description="pyproject.toml [project] has no `license` metadata",
            file=pyproject_path.relative_to(self.project_dir),
            impact=Impact.IMPORTANT,
            explanation=(
                "PEP 639 requires an SPDX license expression, e.g. "
                'license = "MIT", plus license-files = ["LICENSE"].'
            ),
        )

    def _table_form_issue(self, license_table: dict, pyproject_path: Path) -> Issue:
        """Build the issue for the deprecated `{ text = ... }`/`{ file = ... }` form."""
        base_explanation = (
            'PEP 639 requires the SPDX string form (e.g. license = "MIT") '
            "instead of the deprecated `{ text = ... }` / `{ file = ... }` "
            "table form. `preen fix license` can migrate simple cases "
            "automatically."
        )
        proposed_fix = None

        if "text" in license_table:
            key, value = "text", license_table["text"]
            spdx_id = (
                _resolve_legacy_text(str(value)) if isinstance(value, str) else None
            )
            if spdx_id is not None:
                diff = f'license = {{ text = "{value}" }} -> license = "{spdx_id}"'
                proposed_fix = Fix(
                    description=f"Migrate license table form to {spdx_id!r}",
                    diff=diff,
                    apply=lambda spdx_id=spdx_id: self._apply_migrate_table_form(
                        pyproject_path, spdx_id
                    ),
                )
            else:
                base_explanation += (
                    " This text could not be mapped to an SPDX identifier "
                    "automatically; set an explicit SPDX expression "
                    'manually, e.g. license = "MIT".'
                )
        elif "file" in license_table:
            key, value = "file", license_table["file"]
            base_explanation += (
                " A license expression cannot be inferred from a file "
                "reference; set an explicit SPDX expression manually, "
                'e.g. license = "MIT".'
            )
        else:
            # Neither key: reporting `{ file = "None" }` would name a key the
            # file does not contain.
            return Issue(
                check=self.name,
                severity=Severity.WARNING,
                description="license is an empty or unrecognized TOML table",
                file=pyproject_path.relative_to(self.project_dir),
                impact=Impact.IMPORTANT,
                explanation=(
                    "PEP 639 requires an SPDX license expression, e.g. "
                    'license = "MIT". A license table with neither a `text` '
                    "nor a `file` key declares nothing."
                ),
            )

        description = (
            f'license uses the deprecated TOML table form {{ {key} = "{value}" }}'
        )
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description=description,
            file=pyproject_path.relative_to(self.project_dir),
            impact=Impact.IMPORTANT,
            explanation=base_explanation,
            proposed_fix=proposed_fix,
        )

    def _string_form_issue(
        self, license_value: str, pyproject_path: Path
    ) -> Issue | None:
        """Build an issue for a string `license` value, or None if it's clean."""
        tokens = _tokenize_spdx(license_value)
        if tokens is None or not _is_structurally_valid(tokens):
            description = (
                f'license = "{license_value}" is not a valid-looking SPDX expression'
            )
            return Issue(
                check=self.name,
                severity=Severity.WARNING,
                description=description,
                file=pyproject_path.relative_to(self.project_dir),
                impact=Impact.IMPORTANT,
                explanation=(
                    "PEP 639 license strings must be SPDX license "
                    "expressions: identifiers joined by AND/OR/WITH, "
                    'optionally parenthesized, e.g. "MIT" or '
                    '"MIT OR Apache-2.0".'
                ),
            )

        unknown = [
            ident
            for ident in _license_identifiers(tokens)
            if ident not in SPDX_ALLOWLIST
        ]
        if unknown:
            return Issue(
                check=self.name,
                severity=Severity.INFO,
                description=(
                    f'license = "{license_value}" uses SPDX identifier(s) not in '
                    f"preen's known-license allowlist: {', '.join(unknown)}"
                ),
                file=pyproject_path.relative_to(self.project_dir),
                impact=Impact.INFORMATIONAL,
                explanation=(
                    "This is advisory only: verify these are valid SPDX "
                    "identifiers at https://spdx.org/licenses/."
                ),
            )
        return None

    def _classifier_issue(
        self, license_classifiers: list[str], pyproject_path: Path
    ) -> Issue:
        """Build the issue for redundant `License ::` classifiers."""
        return Issue(
            check=self.name,
            severity=Severity.WARNING,
            description=(
                "Deprecated `License ::` classifiers found alongside "
                f"`license`: {', '.join(license_classifiers)}"
            ),
            file=pyproject_path.relative_to(self.project_dir),
            impact=Impact.IMPORTANT,
            explanation=(
                "PEP 639 makes `License ::` trove classifiers redundant "
                "once `license` is set. `preen fix license` can remove "
                "them."
            ),
            proposed_fix=Fix(
                description="Remove deprecated `License ::` classifiers",
                diff="Remove:\n" + "\n".join(f"  {c}" for c in license_classifiers),
                apply=lambda: self._apply_remove_classifiers(pyproject_path),
            ),
        )

    def _license_files_missing_issue(
        self, license_file: Path, pyproject_path: Path
    ) -> Issue:
        """Build the issue for a missing `license-files` when a file exists."""
        rel_license_file = license_file.relative_to(self.project_dir)
        return Issue(
            check=self.name,
            severity=Severity.INFO,
            description=(
                f"license-files is missing but {rel_license_file} exists "
                "at the repo root"
            ),
            file=pyproject_path.relative_to(self.project_dir),
            impact=Impact.INFORMATIONAL,
            explanation=(
                "Add license-files so the license text ships in package "
                "metadata. `preen fix license` can add it."
            ),
            proposed_fix=Fix(
                description=f'Add license-files = ["{rel_license_file}"]',
                diff=f'Add license-files = ["{rel_license_file}"]',
                apply=lambda: self._apply_add_license_files(
                    pyproject_path, str(rel_license_file)
                ),
            ),
        )

    def _find_license_file(self) -> Path | None:
        """Return a LICENSE/LICENCE/COPYING file at the repo root, if any."""
        for entry in sorted(self.project_dir.iterdir()):
            if entry.is_file() and entry.stem.lower() in LICENSE_FILE_STEMS:
                return entry
        return None

    # -- fix appliers --------------------------------------------------

    def _apply_migrate_table_form(self, pyproject_path: Path, spdx_id: str) -> None:
        """Rewrite the license table form to the SPDX string form."""
        doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
        doc["project"]["license"] = spdx_id  # type: ignore[index]
        pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    def _apply_remove_classifiers(self, pyproject_path: Path) -> None:
        """Remove `License ::` classifiers from the project table."""
        doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
        classifiers = doc["project"].get("classifiers")  # type: ignore[union-attr]
        if classifiers is None:
            return
        for item in list(classifiers):
            if isinstance(item, str) and item.startswith("License ::"):
                classifiers.remove(item)
        pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    def _apply_add_license_files(self, pyproject_path: Path, license_file: str) -> None:
        """Add `license-files = [<license_file>]` to the project table."""
        doc = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
        doc["project"]["license-files"] = [license_file]  # type: ignore[index]
        pyproject_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
