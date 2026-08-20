"""Tests for the dropped-args check.

The three shapes in ``test_reproduces_the_bugs_this_check_was_written_for``
are reductions of real defects, all of which passed their own test suites,
CI, ruff and pyright.
"""

from pathlib import Path

import pytest

from preen.checks.dropped_args import DroppedArgsCheck


def _run(tmp_path: Path, **files: str) -> list[str]:
    """Write files into a project directory and return the descriptions found.

    Args:
        tmp_path: Directory to write into.
        **files: ``stem=source`` pairs, written as ``<stem>.py``.

    Returns:
        One description string per issue.
    """
    for stem, source in files.items():
        (tmp_path / f"{stem}.py").write_text(source)
    return [i.description for i in DroppedArgsCheck(tmp_path).run().issues]


def test_a_forwarded_parameter_is_not_flagged(tmp_path: Path) -> None:
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    return inner(x, level=level)
""",
    )

    assert found == []


def test_a_dropped_parameter_is_flagged(tmp_path: Path) -> None:
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    return inner(x)
""",
    )

    assert len(found) == 1
    assert "outer() takes 'level'" in found[0]
    assert "calls inner() without it" in found[0]


def test_a_positionally_supplied_parameter_is_not_flagged(tmp_path: Path) -> None:
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    return inner(x, level)
""",
    )

    assert found == []


def test_a_parameter_without_a_default_is_not_flagged(tmp_path: Path) -> None:
    """Omitting a required parameter is a TypeError, not a silent default."""
    found = _run(
        tmp_path,
        mod="""
def inner(x, level):
    return x * level


def outer(x, level=0.95):
    return inner(x=x, level=level)
""",
    )

    assert found == []


def test_kwargs_forwarding_is_not_flagged(tmp_path: Path) -> None:
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95, **kwargs):
    return inner(x, **kwargs)
""",
    )

    assert found == []


def test_a_name_the_caller_does_not_have_is_not_flagged(tmp_path: Path) -> None:
    """Only a parameter the caller could have forwarded counts."""
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x):
    return inner(x)
""",
    )

    assert found == []


def test_an_ambiguous_name_is_not_flagged(tmp_path: Path) -> None:
    """Two definitions of one name cannot be resolved from a bare call."""
    found = _run(
        tmp_path,
        a="""
def inner(x, level=0.95):
    return x
""",
        b="""
def inner(x):
    return x


def outer(x, level=0.95):
    return inner(x)
""",
    )

    assert found == []


def test_the_allow_comment_suppresses_a_deliberate_drop(tmp_path: Path) -> None:
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    # preen: allow-dropped-arg
    return inner(x)
""",
    )

    assert found == []


def test_the_allow_comment_covers_a_multi_line_call(tmp_path: Path) -> None:
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    return inner(  # preen: allow-dropped-arg
        x,
    )
""",
    )

    assert found == []


def test_excluded_directories_are_skipped(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "vendored.py").write_text(
        "def inner(x, level=0.95):\n    return x\n\n\n"
        "def outer(x, level=0.95):\n    return inner(x)\n"
    )

    assert DroppedArgsCheck(tmp_path).run().issues == []


@pytest.mark.parametrize(
    ("label", "source", "expected"),
    [
        (
            # `estimate` documented max_dependence_points and forwarded it from
            # the CSV entry point; the diagnostics call omitted it.
            "subsampling cap never reached the routine that subsamples",
            """
def _dependence_diagnostics(data, seed, max_dependence_points=2500):
    return data[:max_dependence_points]


def estimate(data, seed=42, max_dependence_points=2500):
    return _dependence_diagnostics(data, seed)
""",
            "max_dependence_points",
        ),
        (
            # The coverage simulation read the bootstrap interval straight off
            # the result, and built that result at the default level.
            "nominal level never arrived at the bootstrap arm",
            """
def estimate(data, ci_level=0.95, bootstrap=True):
    return data


def run_pipeline(data, ci_level=0.95, se_method="auto"):
    res = estimate(data, bootstrap=(se_method == "boot"))
    return res
""",
            "ci_level",
        ),
    ],
)
def test_reproduces_the_bugs_this_check_was_written_for(
    tmp_path: Path, label: str, source: str, expected: str
) -> None:
    found = _run(tmp_path, mod=source)

    assert len(found) == 1, f"{label}: {found}"
    assert expected in found[0]
