"""Citation file check: CITATION.cff exists and is valid YAML."""

from pathlib import Path

import yaml

from .base import Check, CheckResult, Impact, Issue, Severity

REQUIRED_KEYS = ("cff-version", "title", "authors")


class CitationCheck(Check):
    """Check that CITATION.cff exists and parses as a plausible CFF file."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "citation"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check CITATION.cff exists and is valid YAML"

    def run(self) -> CheckResult:
        """Run the citation check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        citation_path = self.project_dir / "CITATION.cff"

        if not citation_path.exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description="CITATION.cff is missing",
                    file=Path("CITATION.cff"),
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "Every fleet repo ships a CITATION.cff; 'preen adopt' "
                        "creates one from the template."
                    ),
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        try:
            data = yaml.safe_load(citation_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"CITATION.cff is not valid YAML: {exc}",
                    file=Path("CITATION.cff"),
                    impact=Impact.IMPORTANT,
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        if not isinstance(data, dict):
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description="CITATION.cff does not contain a YAML mapping",
                    file=Path("CITATION.cff"),
                    impact=Impact.IMPORTANT,
                )
            )
        else:
            missing = [key for key in REQUIRED_KEYS if key not in data]
            if missing:
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=(
                            f"CITATION.cff is missing keys: {', '.join(missing)}"
                        ),
                        file=Path("CITATION.cff"),
                        impact=Impact.IMPORTANT,
                    )
                )

        return CheckResult(check=self.name, passed=not issues, issues=issues)
