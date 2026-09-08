"""Tests for the strict-pytest-configuration check (sp-repo-review PP301-309)."""

import tomllib
from pathlib import Path

import pytest

from preen.checks.base import Impact
from preen.checks.pytest_config import PytestConfigCheck

STRICT = """\
[project]
name = "mypkg"
version = "0.1.0"

[tool.pytest.ini_options]
minversion = "8"
testpaths = ["tests"]
log_level = "INFO"
xfail_strict = true
filterwarnings = ["error"]
addopts = ["-ra", "--strict-config", "--strict-markers"]
"""


def _codes(result) -> list[str]:
    """Return the sp-repo-review codes a result reported.

    Args:
        result: The CheckResult.

    Returns:
        The codes, in report order.
    """
    return [issue.description.split(":")[0] for issue in result.issues]


def test_a_strictly_configured_repo_reports_nothing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(STRICT)

    result = PytestConfigCheck(tmp_path).run()

    assert result.passed
    assert result.issues == []


def test_every_missing_setting_is_named(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n\n'
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )

    result = PytestConfigCheck(tmp_path).run()

    assert _codes(result) == [
        "PP302",
        "PP304",
        "PP305",
        "PP306",
        "PP307",
        "PP308",
        "PP309",
    ]


def test_a_missing_setting_gates(tmp_path: Path) -> None:
    """These were advisory until py-canon 1.3.0 put them in the template.

    Gating before that would have failed every repo in the fleet for following
    a standard that did not ask for this yet.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n\n'
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )

    result = PytestConfigCheck(tmp_path).run()

    assert not result.passed
    assert all(issue.impact == Impact.IMPORTANT for issue in result.issues)
    # Important, never critical: a missing setting is not a broken build, and
    # a release should not be refused over one.
    assert not any(issue.is_blocking() for issue in result.issues)


def test_no_pytest_table_stays_advisory(tmp_path: Path) -> None:
    """A repo with no table may have no tests, which is its own conversation."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n'
    )

    result = PytestConfigCheck(tmp_path).run()

    assert result.passed
    assert result.issues[0].impact == Impact.INFORMATIONAL


def test_no_pytest_table_at_all_is_pp301(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0"\n'
    )

    result = PytestConfigCheck(tmp_path).run()

    assert _codes(result) == ["PP301"]
    assert result.issues[0].proposed_fix is not None


def test_pytest_9_native_table_is_read_and_needs_minversion_9(tmp_path: Path) -> None:
    """pytest 9 reads `[tool.pytest]`; only 6-8 need `ini_options`."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n\n'
        '[tool.pytest]\nminversion = "8"\ntestpaths = ["tests"]\n'
    )

    result = PytestConfigCheck(tmp_path).run()

    assert "PP302" in _codes(result)


def test_addopts_as_a_string_is_still_read(tmp_path: Path) -> None:
    """pytest accepts `addopts` as one string; so must the check."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n\n'
        "[tool.pytest.ini_options]\n"
        'addopts = "-ra --strict-config --strict-markers"\n'
    )

    result = PytestConfigCheck(tmp_path).run()

    assert "PP306" not in _codes(result)
    assert "PP307" not in _codes(result)
    assert "PP308" not in _codes(result)


def test_any_summary_flag_satisfies_pp308(tmp_path: Path) -> None:
    """`-rA` and `-rfE` print a summary just as `-ra` does."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n\n'
        '[tool.pytest.ini_options]\naddopts = ["-rfE"]\n'
    )

    assert "PP308" not in _codes(PytestConfigCheck(tmp_path).run())


def test_fix_writes_toml_not_python_repr(tmp_path: Path) -> None:
    """The written file has to parse, and the preview has to be readable."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n\n'
        '# keep me\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )

    issue = PytestConfigCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    assert "xfail_strict = true" in issue.proposed_fix.preview()
    issue.proposed_fix.apply()

    text = (tmp_path / "pyproject.toml").read_text()
    options = tomllib.loads(text)["tool"]["pytest"]["ini_options"]
    assert options["xfail_strict"] is True
    assert options["filterwarnings"] == ["error"]
    assert set(options["addopts"]) == {"-ra", "--strict-config", "--strict-markers"}
    assert options["testpaths"] == ["tests"]
    assert "# keep me" in text
    assert PytestConfigCheck(tmp_path).run().issues == []


def test_fix_appends_to_existing_addopts(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n\n'
        '[tool.pytest.ini_options]\naddopts = ["--tb=short"]\n'
    )

    issue = PytestConfigCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    options = tomllib.loads((tmp_path / "pyproject.toml").read_text())["tool"][
        "pytest"
    ]["ini_options"]
    assert options["addopts"][0] == "--tb=short"


def test_missing_pyproject_passes_silently(tmp_path: Path) -> None:
    result = PytestConfigCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_a_string_addopts_stays_a_string(tmp_path: Path) -> None:
    """Splitting it to build a list tears quoted arguments apart.

    gojiplus/get-weather-data writes `addopts = "-v --tb=short -m 'not live'"`.
    Rewriting that as a list produced `["-m", "'not", "live'"]`, and pytest
    then looked for a test path called `live'`.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "gwd"\nversion = "1.0.0"\n\n'
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        "addopts = \"-v --tb=short -m 'not live'\"\n"
    )

    issue = PytestConfigCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    addopts = tomllib.loads((tmp_path / "pyproject.toml").read_text())["tool"][
        "pytest"
    ]["ini_options"]["addopts"]

    assert isinstance(addopts, str)
    assert "-m 'not live'" in addopts
    for flag in ("-ra", "--strict-config", "--strict-markers"):
        assert flag in addopts
    assert PytestConfigCheck(tmp_path).run().issues == []


def test_fix_leaves_a_trailing_comment_where_it_was(tmp_path: Path) -> None:
    """New keys go after the last key, not after a comment about the next table.

    themains/piedomains ends its pytest table with a blank line and a comment
    introducing the section below. Appending at the end of the table put four
    pytest settings under `# mypy configuration`, glued the next header to
    them, and reflowed a multi-line `addopts` onto one line.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "piedomains"\nversion = "1.0.0"\n\n'
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        "addopts = [\n"
        '    "-ra",\n'
        '    "-m",\n'
        '    "not slow",\n'
        "]\n"
        "\n"
        "# mypy configuration\n"
        "[tool.coverage.run]\n"
        'source = ["src"]\n'
    )

    issue = PytestConfigCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    text = (tmp_path / "pyproject.toml").read_text()
    assert text == (
        '[project]\nname = "piedomains"\nversion = "1.0.0"\n\n'
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        "addopts = [\n"
        '    "-ra",\n'
        '    "-m",\n'
        '    "not slow",\n'
        '    "--strict-config",\n'
        '    "--strict-markers",\n'
        "]\n"
        'minversion = "6"\n'
        'log_level = "INFO"\n'
        "xfail_strict = true\n"
        'filterwarnings = ["error"]\n'
        "\n"
        "# mypy configuration\n"
        "[tool.coverage.run]\n"
        'source = ["src"]\n'
    )
    assert PytestConfigCheck(tmp_path).run().issues == []


def test_fix_handles_an_inline_pytest_table(tmp_path: Path) -> None:
    """`pytest = {ini_options = {...}}` is valid TOML and worked at 0.5.0.

    Rebuilding the options as a regular table broke it: tomlkit refuses a
    table inside an inline table.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n\n'
        "[tool]\n"
        'pytest = {ini_options = {testpaths = ["tests"]}}\n'
    )

    issue = PytestConfigCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    options = tomllib.loads((tmp_path / "pyproject.toml").read_text())["tool"][
        "pytest"
    ]["ini_options"]
    assert options["xfail_strict"] is True
    assert options["testpaths"] == ["tests"]
    assert PytestConfigCheck(tmp_path).run().issues == []


def test_fix_keeps_a_dotted_key_pytest_table_dotted(tmp_path: Path) -> None:
    """`pytest.ini_options.testpaths = [...]` under `[tool]` worked at 0.5.0."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n\n'
        "[tool]\n"
        'pytest.ini_options.testpaths = ["tests/unit"]\n'
        "\n# next\n"
        "[tool.coverage.run]\n"
        'source = ["src"]\n'
    )
    issue = PytestConfigCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    text = (tmp_path / "pyproject.toml").read_text()
    options = tomllib.loads(text)["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["tests/unit"]
    assert options["xfail_strict"] is True
    assert "[pytest.ini_options]" not in text
    assert PytestConfigCheck(tmp_path).run().issues == []


def test_fix_handles_several_dotted_pytest_keys(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n\n'
        "[tool]\n"
        'pytest.ini_options.testpaths = ["tests"]\n'
        'pytest.ini_options.addopts = ["-ra"]\n'
    )
    issue = PytestConfigCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()
    assert PytestConfigCheck(tmp_path).run().issues == []


def test_fix_replaces_an_ini_options_that_is_not_a_table(tmp_path: Path) -> None:
    """pytest ignores a non-table `ini_options`; the fix writes a real one."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n\n'
        "[tool.pytest]\n"
        'ini_options = "invalid"\n'
    )
    issue = PytestConfigCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()
    assert PytestConfigCheck(tmp_path).run().issues == []


@pytest.mark.parametrize(
    "extra",
    [
        "strict_config = true\nstrict_markers = true\nstrict_xfail = true\n",
        "strict = true\n",
    ],
)
def test_pytest_9_ini_spellings_of_strictness_count(tmp_path: Path, extra: str) -> None:
    """pytest 9 accepts the strict flags as ini settings, and `strict` for all."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nversion = "0.1.0"\n\n'
        "[tool.pytest.ini_options]\n"
        'minversion = "9"\n'
        'testpaths = ["tests"]\n'
        'log_level = "INFO"\n'
        'filterwarnings = ["error"]\n'
        'addopts = ["-ra"]\n' + extra
    )
    result = PytestConfigCheck(tmp_path).run()
    assert result.issues == []
