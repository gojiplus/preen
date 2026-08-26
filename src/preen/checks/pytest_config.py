"""Strict pytest configuration, per sp-repo-review PP301-PP309.

Each of these settings changes whether a test run *fails*, not how it reads.
Without ``filterwarnings``, a DeprecationWarning from a dependency is invisible
until the release that removes the API; without ``--strict-markers``, a typo in
a marker name silently selects nothing; without ``xfail_strict``, a test that
starts passing keeps reporting xfail forever.

These gate. They did not until py-canon 1.3.0, which put the whole set in the
template -- before that, gating would have failed every repo in the fleet for
following a standard that did not ask for this yet. It asks now, `copier update`
delivers it, and ``preen fix pytest-config`` writes it into a repo directly.

``PP301`` is the exception and stays informational: a repo with no pytest table
at all may have no tests to configure, which is a different conversation from a
repo whose table is missing settings.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import tomlkit

from .base import Check, CheckResult, Fix, Impact, Issue, Severity


@dataclass(frozen=True)
class Setting:
    """One pytest setting the standard expects.

    Attributes:
        code: The sp-repo-review code it corresponds to.
        key: The pytest ini key, or the addopts flag when ``in_addopts``.
        value: The value ``preen fix`` writes.
        why: What goes wrong without it.
        in_addopts: True when the setting is a flag inside ``addopts``.
    """

    code: str
    key: str
    value: Any
    why: str
    in_addopts: bool = False


SETTINGS: tuple[Setting, ...] = (
    Setting(
        "PP303",
        "testpaths",
        ["tests"],
        "without it pytest walks the whole tree, collecting from .venv and docs",
    ),
    Setting(
        "PP304",
        "log_level",
        "INFO",
        "logs captured during a failing test are otherwise thrown away",
    ),
    Setting(
        "PP305",
        "xfail_strict",
        True,
        "a test that starts passing keeps reporting xfail, so the fix goes unnoticed",
    ),
    Setting(
        "PP306",
        "--strict-config",
        None,
        "a typo in this very table is otherwise ignored rather than reported",
        in_addopts=True,
    ),
    Setting(
        "PP307",
        "--strict-markers",
        None,
        "a typo in a marker name otherwise selects nothing, silently",
        in_addopts=True,
    ),
    Setting(
        "PP308",
        "-ra",
        None,
        "the run otherwise ends without a summary of what was skipped or xfailed",
        in_addopts=True,
    ),
    Setting(
        "PP309",
        "filterwarnings",
        ["error"],
        (
            "a DeprecationWarning from a dependency is otherwise invisible until "
            "the release that removes the API"
        ),
    ),
)


class PytestConfigCheck(Check):
    """Check that pytest is configured to fail on what it should fail on."""

    #: The lowest pytest each table shape can be configured from.
    MIN_VERSIONS: ClassVar[dict[bool, int]] = {True: 9, False: 6}

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "pytest-config"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check pytest is configured strictly (sp-repo-review PP301-309)"

    def _load(self) -> tuple[dict[str, Any] | None, bool]:
        """Locate pytest's configuration table in pyproject.toml.

        Returns:
            The options mapping and whether it is pytest 9's native
            ``[tool.pytest]`` table, or ``(None, False)`` when there is none.
        """
        pyproject = self.project_dir / "pyproject.toml"
        if not pyproject.exists():
            return None, False
        try:
            with pyproject.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            return None, False

        legacy = data.get("tool", {}).get("pytest", {}).get("ini_options")
        if isinstance(legacy, dict):
            return legacy, False
        native = data.get("tool", {}).get("pytest")
        if isinstance(native, dict):
            return native, True
        return None, False

    def _addopts(self, options: dict[str, Any]) -> list[str]:
        """Return ``addopts`` as a list of flags.

        Args:
            options: The pytest options table.

        Returns:
            The flags, however they were spelled.
        """
        raw = options.get("addopts", [])
        if isinstance(raw, str):
            return raw.split()
        return [str(entry) for entry in raw]

    def _missing(self, options: dict[str, Any]) -> list[Setting]:
        """Return the settings the repo has not configured.

        Args:
            options: The pytest options table.

        Returns:
            The missing settings, in declaration order.
        """
        addopts = self._addopts(options)
        missing = []
        for setting in SETTINGS:
            if setting.in_addopts:
                # -ra, -rA and -rfE all satisfy PP308's "print a summary".
                present = any(
                    flag == setting.key
                    or (setting.key == "-ra" and flag.startswith("-r"))
                    for flag in addopts
                )
            else:
                present = setting.key in options
            if not present:
                missing.append(setting)
        return missing

    def _minversion_issue(self, options: dict[str, Any], native: bool) -> list[Issue]:
        """Check PP302: a declared minimum pytest.

        Args:
            options: The pytest options table.
            native: Whether the table is pytest 9's native one.

        Returns:
            At most one issue.
        """
        floor = self.MIN_VERSIONS[native]
        declared = options.get("minversion")
        if declared is not None:
            try:
                if int(str(declared).split(".", maxsplit=1)[0]) >= floor:
                    return []
            except ValueError:
                pass
        return [
            self._issue(
                "PP302",
                f"minversion is not set to at least {floor}",
                (
                    "Without it, an older pytest silently ignores the settings "
                    "below instead of refusing to run."
                ),
            )
        ]

    def _issue(
        self, code: str, description: str, explanation: str, gating: bool = True
    ) -> Issue:
        """Build one finding.

        Args:
            code: The sp-repo-review code.
            description: What is missing.
            explanation: What goes wrong without it.
            gating: Whether this should fail the check.

        Returns:
            The Issue.
        """
        return Issue(
            check=self.name,
            severity=Severity.WARNING if gating else Severity.INFO,
            description=f"{code}: {description}",
            file=Path("pyproject.toml"),
            impact=Impact.IMPORTANT if gating else Impact.INFORMATIONAL,
            explanation=explanation,
        )

    def run(self) -> CheckResult:
        """Run the pytest configuration check.

        Returns:
            CheckResult containing any issues found.
        """
        if not (self.project_dir / "pyproject.toml").exists():
            return CheckResult(check=self.name, passed=True, issues=[])

        options, native = self._load()
        if options is None:
            issue = self._issue(
                "PP301",
                "pytest has no configuration table in pyproject.toml",
                (
                    "Nothing below can be set without one. Add "
                    "[tool.pytest.ini_options]."
                ),
                gating=False,
            )
            issue.proposed_fix = self._write_fix([], minversion=True)
            return CheckResult(check=self.name, passed=True, issues=[issue])

        missing = self._missing(options)
        version_issues = self._minversion_issue(options, native)
        issues = [
            *version_issues,
            *(
                self._issue(
                    setting.code,
                    (
                        f"addopts does not include {setting.key}"
                        if setting.in_addopts
                        else f"{setting.key} is not set"
                    ),
                    f"Otherwise {setting.why}.",
                )
                for setting in missing
            ),
        ]
        if issues:
            issues[0].proposed_fix = self._write_fix(
                missing, minversion=bool(version_issues)
            )

        blocking = [issue for issue in issues if issue.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)

    def _write_fix(self, missing: list[Setting], minversion: bool) -> Fix:
        """Build a fix that writes the missing settings into pyproject.toml.

        Args:
            missing: Settings to add.
            minversion: Whether to write ``minversion`` too.

        Returns:
            The fix.
        """
        wanted = [setting for setting in missing if not setting.in_addopts]
        flags = [setting.key for setting in missing if setting.in_addopts]

        lines = [f'minversion = "{self.MIN_VERSIONS[False]}"'] if minversion else []
        # tomlkit.item renders TOML rather than Python: `true`, not `True`.
        lines += [
            f"{setting.key} = {tomlkit.item(setting.value).as_string()}"
            for setting in wanted
        ]
        if flags:
            lines.append(f"addopts += {tomlkit.item(flags).as_string()}")

        def apply() -> None:
            """Add the settings to [tool.pytest.ini_options]."""
            pyproject = self.project_dir / "pyproject.toml"
            document = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
            tool = document.setdefault("tool", tomlkit.table(is_super_table=True))
            pytest_table = tool.setdefault("pytest", tomlkit.table(is_super_table=True))
            options = pytest_table.setdefault("ini_options", tomlkit.table())

            if minversion:
                options["minversion"] = str(self.MIN_VERSIONS[False])
            for setting in wanted:
                options[setting.key] = setting.value
            if flags:
                addopts = self._addopts(dict(options))
                options["addopts"] = [*addopts, *flags]

            pyproject.write_text(tomlkit.dumps(document), encoding="utf-8")

        return Fix(
            description="Configure pytest to fail on what it should fail on",
            diff="[tool.pytest.ini_options]\n" + "\n".join(lines) + "\n",
            apply=apply,
        )

    def can_fix(self) -> bool:
        """Return True: the missing settings can be written.

        Returns:
            True.
        """
        return True
