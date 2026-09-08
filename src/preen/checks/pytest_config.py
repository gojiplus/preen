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
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import tomlkit
from tomlkit.items import Array, Comment, Table, Whitespace

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
        synonyms: ini keys that, set to true, satisfy it as well. pytest 9
            accepts the strict flags as settings, and ``strict`` for all of
            them, with the specific setting taking precedence.
    """

    code: str
    key: str
    value: Any
    why: str
    in_addopts: bool = False
    synonyms: tuple[str, ...] = ()


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
        synonyms=("strict_xfail", "strict"),
    ),
    Setting(
        "PP306",
        "--strict-config",
        None,
        "a typo in this very table is otherwise ignored rather than reported",
        in_addopts=True,
        synonyms=("strict_config", "strict"),
    ),
    Setting(
        "PP307",
        "--strict-markers",
        None,
        "a typo in a marker name otherwise selects nothing, silently",
        in_addopts=True,
        synonyms=("strict_markers", "strict"),
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


def _ends_with_decoration(table: Table) -> bool:
    """Whether a plain table's body ends with a comment or blank line.

    Only such a table needs rebuilding, and only a plain one can be: an
    inline table has no trailing decoration, and a dotted-key table renders
    from its keys rather than a header, so a rebuilt copy would lose the
    ``tool.`` prefix.

    Args:
        table: Whatever sits at ``tool.pytest.ini_options``.

    Returns:
        True when rebuilding is both needed and safe.
    """
    if table.is_super_table():
        return False
    body = table.value.body
    return bool(body) and body[-1][0] is None


def _split_trailing(table: Table) -> tuple[Table, list[Comment | Whitespace]]:
    """Copy a table up to its last key, returning what trailed that key.

    tomlkit adds a new key after everything already in a table, and that
    includes a trailing blank line and a comment that really introduces the
    next section (python-poetry/tomlkit#295, open). It offers no public way to
    insert earlier, so the caller builds a fresh table: the copy, the new keys,
    then the trailing items put back. Comments between keys stay where they
    were.

    Args:
        table: The parsed table.

    Returns:
        The copy, and the comment and whitespace items after its last key.
    """
    copy = tomlkit.table()
    trailing: list[Comment | Whitespace] = []
    for key, item in table.value.body:
        if key is None:
            # Only comments and whitespace go keyless in a table body.
            assert isinstance(item, Comment | Whitespace)  # noqa: S101
            trailing.append(item)
            continue
        for decoration in trailing:
            copy.add(decoration)
        trailing = []
        copy.add(key, item)
    return copy, trailing


def _as_bool(value: object) -> bool | None:
    """Read a boolean the way pytest reads an ini value.

    Args:
        value: A TOML boolean, or a string such as ``"true"`` or ``"no"``.

    Returns:
        The boolean, or None when it is neither.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "on", "1"}:
            return True
        if lowered in {"false", "no", "off", "0"}:
            return False
    return None


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

    def _missing(self, options: dict[str, Any], native: bool) -> list[Setting]:
        """Return the settings the repo has not configured.

        Args:
            options: The pytest options table.
            native: Whether the table is pytest 9's native one.

        Returns:
            The missing settings, in declaration order.
        """
        addopts = self._addopts(options)
        # The strict settings and the blanket --strict arrived in pytest 9.
        # On pytest 8 the settings are unknown and --strict only aliases
        # --strict-markers, so they count only where 9 is the floor.
        pytest9 = native or self._declared_major(options) >= 9
        return [
            s for s in SETTINGS if not self._satisfied(s, options, addopts, pytest9)
        ]

    @staticmethod
    def _declared_major(options: dict[str, Any]) -> int:
        """Read the major of a declared ``minversion``, or 0 if none parses.

        Args:
            options: The pytest options table.

        Returns:
            The major version.
        """
        declared = options.get("minversion")
        try:
            return int(str(declared).split(".", maxsplit=1)[0])
        except ValueError:
            return 0

    @staticmethod
    def _satisfied(
        setting: Setting, options: dict[str, Any], addopts: list[str], pytest9: bool
    ) -> bool:
        """Whether a setting is configured, by its own key or a synonym.

        Precedence follows pytest 9.1.1, checked by running it: a flag in
        ``addopts``, then the canonical setting (``strict_xfail`` over its
        alias ``xfail_strict``, in either order), then the blanket ``strict``.
        A specific setting written as ``false`` is the opposite of configured
        and beats ``strict``. In ``[tool.pytest.ini_options]`` a boolean may
        be spelled as a string, ``"true"`` or ``"yes"``, as in an ini file.

        Args:
            setting: The setting to look for.
            options: The pytest options table.
            addopts: ``addopts`` as a list of flags.
            pytest9: Whether the repo runs on pytest 9 or later, where the
                strict settings and the blanket ``--strict`` exist.

        Returns:
            True when the repo has it on.
        """
        # -ra, -rA and -rfE all satisfy PP308's "print a summary".
        if setting.in_addopts and any(
            flag == setting.key or (setting.key == "-ra" and flag.startswith("-r"))
            for flag in addopts
        ):
            return True
        if setting.key == "--strict-markers" and "--strict" in addopts:
            return True  # an alias in every pytest this check accepts
        for key in (k for k in setting.synonyms if k != "strict") if pytest9 else ():
            if key in options:
                return _as_bool(options[key]) is True
        if not setting.in_addopts and setting.key in options:
            # Only a boolean setting can be written as "off"; log_level = "0"
            # is a logging level, not a false.
            if isinstance(setting.value, bool):
                return _as_bool(options[setting.key]) is not False
            return True
        # pytest 9's `--strict` flag enables the strict option, as the ini does.
        blanket = _as_bool(options.get("strict")) is True or "--strict" in addopts
        return pytest9 and "strict" in setting.synonyms and blanket

    def _minversion_issue(self, options: dict[str, Any], native: bool) -> list[Issue]:
        """Check PP302: a declared minimum pytest.

        Args:
            options: The pytest options table.
            native: Whether the table is pytest 9's native one.

        Returns:
            At most one issue.
        """
        floor = self.MIN_VERSIONS[native]
        if self._declared_major(options) >= floor:
            return []
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

        missing = self._missing(options, native)
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
            current = pytest_table.setdefault("ini_options", tomlkit.table())
            if not isinstance(current, MutableMapping):
                # `ini_options = "invalid"`: pytest ignores it; write a real one.
                current = pytest_table["ini_options"] = tomlkit.table()
            rebuilt: Table | None = None
            trailing: list[Comment | Whitespace] = []
            if isinstance(current, Table) and _ends_with_decoration(current):
                rebuilt, trailing = _split_trailing(current)
            # Otherwise append in place: there is nothing to step over, and
            # that keeps an inline table inline and a dotted key dotted,
            # which a rebuild cannot.
            options = current if rebuilt is None else rebuilt

            if minversion:
                options["minversion"] = str(self.MIN_VERSIONS[False])
            for setting in wanted:
                options[setting.key] = setting.value
                # A canonical spelling already present would beat the key
                # just written (strict_xfail over xfail_strict), so flip it.
                for synonym in setting.synonyms:
                    if synonym != "strict" and synonym in options:
                        options[synonym] = True
            if flags:
                existing = options.get("addopts")
                if isinstance(existing, str):
                    # Keep the string form. Splitting it to build a list tore
                    # `-m 'not live'` into three tokens on
                    # gojiplus/get-weather-data, and pytest then looked for a
                    # test path called `live'`.
                    options["addopts"] = " ".join([existing.strip(), *flags])
                elif isinstance(existing, Array):
                    # Extending in place keeps a multi-line list multi-line.
                    existing.extend(flags)
                else:
                    options["addopts"] = flags

            if rebuilt is not None:
                for item in trailing:
                    rebuilt.add(item)
                pytest_table["ini_options"] = rebuilt
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
