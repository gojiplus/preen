"""The Python floor check, and why it is off by default.

STANDARD.md declared >=3.12 while 30 of 51 adopted repos shipped >=3.11 and
every one passed, because no check read the declared floor. This closes that,
but enabling it before the fleet migrates would put thirty repos in violation
at once, which is how a check gets switched off rather than obeyed.
"""

import pathlib
import re
import textwrap

import pytest

from preen.checks.python_floor import (
    STANDARD_FLOOR,
    PythonFloorCheck,
    declared_floor,
)


def _repo(tmp_path, requires: str, enforce: bool = True):
    extra = "\n[tool.preen]\nenforce_python_floor = true\n" if enforce else ""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(f'[project]\nname = "x"\nrequires-python = "{requires}"\n')
        + extra
    )
    return tmp_path


def test_a_floor_below_the_standard_is_flagged(tmp_path):
    result = PythonFloorCheck(_repo(tmp_path, ">=3.11")).run()
    assert not result.passed
    assert ">=3.11" in result.issues[0].description
    assert ">=3.12" in result.issues[0].description


def test_a_floor_at_the_standard_passes(tmp_path):
    assert PythonFloorCheck(_repo(tmp_path, ">=3.12")).run().passed


def test_a_floor_above_the_standard_passes(tmp_path):
    assert PythonFloorCheck(_repo(tmp_path, ">=3.13")).run().passed


def test_it_stays_silent_until_a_repo_opts_in(tmp_path):
    # 30 repos are below the floor today. Failing them all at once is how a
    # check gets disabled rather than obeyed.
    assert PythonFloorCheck(_repo(tmp_path, ">=3.11", enforce=False)).run().passed


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (">=3.12", (3, 12)),
        (">= 3.12", (3, 12)),
        (">=3.11,<3.14", (3, 11)),
        (">=3.9", (3, 9)),
        ("", None),
    ],
)
def test_the_floor_is_read_from_the_specifier(tmp_path, spec, expected):
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nrequires-python = "{spec}"\n'
    )
    assert declared_floor(tmp_path / "pyproject.toml") == expected


def test_the_mirrored_floor_matches_what_the_template_emits():
    """The constant here mirrors STANDARD.md, which is prose and unparsable.

    That mirroring is exactly the kind of drift this check exists to catch, so
    it is verified against py-canon's template whenever a checkout is beside
    this one.
    """
    template = (
        pathlib.Path(__file__).resolve().parents[2]
        / "py-canon"
        / "template"
        / "pyproject.toml.jinja"
    )
    if not template.exists():
        pytest.skip("no py-canon checkout beside this repo")
    # Read by pattern rather than declared_floor: the template is jinja, so it
    # is not valid TOML and the parser returns None for it.
    match = re.search(
        r'requires-python\s*=\s*">=\s*(\d+)\.(\d+)"', template.read_text()
    )
    assert match, "py-canon's template declares no requires-python floor"
    emitted = (int(match.group(1)), int(match.group(2)))
    assert emitted == STANDARD_FLOOR, (
        f"preen mirrors >={'.'.join(map(str, STANDARD_FLOOR))} but py-canon's "
        f"template emits >={'.'.join(map(str, emitted))}"
    )
