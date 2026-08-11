"""Presence of the files a package is expected to carry.

Separate from the `structure` check on purpose. That one asks whether things
are in the right *place* -- tests/ at the root rather than inside the package.
This asks whether they exist at all. Folding the two together made
`test_clean_src_layout_passes` fail for want of a README, which is not what
that test claims to be about, and the split is also how sp-repo-review divides
it (PY002 and PY008 sit in `general`, not with the layout rules).

These are near-worthless on a repo generated from the py-canon template, which
ships both files. They earn their place when assessing an existing repo for
adoption, where the real question is whether the thing is a maintained package
or an abandoned script -- and "no README" answers that faster than anything
else available.
"""

from .base import Check, CheckResult, Fix, Impact, Issue, Severity

# Accepted README spellings, in the order a reader would look for them.
README_NAMES = ("README.md", "README.rst", "README.txt", "README")

GITIGNORE_DEFAULTS = """# Python artifacts
**/__pycache__/
*.pyc
*.pyo
*.pyd
build/
dist/
*.egg-info/
.venv/
"""


class RequiredFilesCheck(Check):
    """Check that a package carries a README and a .gitignore."""

    @property
    def name(self) -> str:
        """Return the name of this check.

        Returns:
            The check name.
        """
        return "files"

    @property
    def description(self) -> str:
        """Return a description of what this check does.

        Returns:
            The check description.
        """
        return "Check the files every package should carry are present"

    def _write_gitignore(self) -> None:
        """Create a .gitignore with the usual Python artifacts."""
        (self.project_dir / ".gitignore").write_text(
            GITIGNORE_DEFAULTS, encoding="utf-8"
        )

    def run(self) -> CheckResult:
        """Run the required-files check.

        Returns:
            The check result.
        """
        issues = []

        if not any((self.project_dir / n).exists() for n in README_NAMES):
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"No README found. Expected one of: {', '.join(README_NAMES)}"
                    ),
                    impact=Impact.IMPORTANT,
                )
            )

        if not (self.project_dir / ".gitignore").exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        "No .gitignore. Python builds drop __pycache__ and *.pyc "
                        "into the tree, and without one they get committed."
                    ),
                    proposed_fix=Fix(
                        description="Create .gitignore with the usual Python artifacts",
                        diff=GITIGNORE_DEFAULTS,
                        apply=self._write_gitignore,
                    ),
                )
            )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        """Return True if this check can automatically fix issues.

        Returns:
            True; a missing .gitignore can be written. A missing README cannot
            be, and deliberately is not -- generating one would satisfy the
            check while leaving the repo just as undocumented.
        """
        return True
