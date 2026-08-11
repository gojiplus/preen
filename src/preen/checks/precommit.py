"""pre-commit configuration check.

The py-canon template ships `.pre-commit-config.yaml`, so every adopted repo
starts with hooks -- and until now nothing ever looked at the file again. A
config that is shipped but never checked is worse than one that was never
shipped: it rots quietly, and the repo keeps reporting healthy while the hooks
have silently stopped meaning anything.

Deliberately narrow. sp-repo-review devotes a whole family (PC1xx) to *which*
hooks are configured; that would be redundant here, because ruff, pyright,
pydoclint and codespell already run in reusable-ci. CI is the gate. Hooks are
a convenience that shortens the loop, so the only questions worth asking are
whether the file is there and whether it is valid.
"""

from pathlib import Path

import yaml

from .base import Check, CheckResult, Impact, Issue, Severity

CONFIG_NAMES = (".pre-commit-config.yaml", ".pre-commit-config.yml")


class PreCommitCheck(Check):
    """Check that a pre-commit config exists and parses."""

    @property
    def name(self) -> str:
        """Return the name of this check.

        Returns:
            The check name.
        """
        return "precommit"

    @property
    def description(self) -> str:
        """Return a description of what this check does.

        Returns:
            The check description.
        """
        return "Check pre-commit config is present and valid"

    def _config_path(self) -> Path | None:
        """Locate the pre-commit config.

        Returns:
            The config path, or None if the repo has none.
        """
        for name in CONFIG_NAMES:
            candidate = self.project_dir / name
            if candidate.exists():
                return candidate
        return None

    def run(self) -> CheckResult:
        """Run the pre-commit check.

        Returns:
            The check result.
        """
        path = self._config_path()

        if path is None:
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=(
                            "No pre-commit config. The py-canon template ships "
                            f"{CONFIG_NAMES[0]}; its absence means the repo was "
                            "adopted before that, or the file was removed."
                        ),
                        impact=Impact.IMPORTANT,
                    )
                ],
            )

        issues = []
        try:
            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            # An unparseable config is the failure worth catching: pre-commit
            # errors out rather than running, so the hooks stop happening and
            # nothing else reports it.
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"{path.name} does not parse: {exc}",
                    file=Path(path.name),
                    impact=Impact.CRITICAL,
                )
            )
        else:
            if not isinstance(parsed, dict) or not parsed.get("repos"):
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        description=(
                            f"{path.name} has no `repos:` entries, so pre-commit "
                            "runs nothing. An empty config passes silently, which "
                            "is the state this check exists to surface."
                        ),
                        file=Path(path.name),
                        impact=Impact.IMPORTANT,
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
            False; writing someone a hook config they did not choose is not a fix.
        """
        return False
