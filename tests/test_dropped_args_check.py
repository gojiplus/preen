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


def test_the_allow_comment_may_open_a_multi_line_rationale(tmp_path: Path) -> None:
    """The marker on the first line of a comment block still counts.

    A reason that takes a few lines naturally starts with the marker, which
    then sits more than one line above the call. Two fleet repositories had to
    restructure their comments, and split a wrapped call, to be heard.
    """
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    # preen: allow-dropped-arg -- the rationale runs to several lines,
    # because the reason this argument is deliberately not forwarded
    # takes more than one line to explain properly.
    return inner(x)
""",
    )

    assert found == []


def test_the_allow_comment_does_not_reach_across_code(tmp_path: Path) -> None:
    """A marker above an unrelated statement must not cover the next call."""
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    # preen: allow-dropped-arg
    y = x + 1
    return inner(y)
""",
    )

    assert len(found) == 1


def test_a_trailing_marker_covers_only_its_own_line(tmp_path: Path) -> None:
    """A marker after code on one line says nothing about the next line."""
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    a = inner(x)  # preen: allow-dropped-arg
    b = inner(x)
    return a + b
""",
    )

    assert len(found) == 1


def test_a_marker_on_the_first_line_of_a_statement_covers_the_call(
    tmp_path: Path,
) -> None:
    """The call starts a line below the marker, but it is the same statement."""
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    result = (  # preen: allow-dropped-arg
        inner(x)
    )
    return result
""",
    )

    assert found == []


def test_a_marker_on_a_compound_header_does_not_cover_its_body(tmp_path: Path) -> None:
    found = _run(
        tmp_path,
        mod="""
def inner(x, level=0.95):
    return x * level


def outer(x, level=0.95):
    if x:  # preen: allow-dropped-arg
        return inner(x)
    return 0
""",
    )

    assert len(found) == 1


INNER = """
def inner(x, level=0.95):
    return x * level
"""


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # A comment marker inside the body covers the return, not the header.
        (
            "    if inner(x):\n"
            "        # preen: allow-dropped-arg\n"
            "        return inner(x)\n"
            "    return 0\n",
            1,
        ),
        # A one-line compound statement: the marker covers the call on it.
        ("    if inner(x): pass  # preen: allow-dropped-arg\n    return 0\n", 0),
        # match has cases, not a body; a marker on its subject line covers it.
        (
            "    match inner(x):  # preen: allow-dropped-arg\n"
            "        case _:\n"
            "            return inner(x)\n",
            1,
        ),
        # An except header is not a statement; its own marker still counts.
        (
            "    try:\n"
            "        return 0\n"
            "    except inner(x):  # preen: allow-dropped-arg\n"
            "        return 1\n",
            0,
        ),
    ],
)
def test_calls_in_compound_headers_are_covered_only_by_their_own_lines(
    tmp_path: Path, body: str, expected: int
) -> None:
    found = _run(tmp_path, mod=INNER + "\n\ndef outer(x, level=0.95):\n" + body)
    assert len(found) == expected


def test_calls_in_defaults_and_decorators_are_still_seen(tmp_path: Path) -> None:
    """The function's signature is part of the function, not just its body."""
    found = _run(
        tmp_path,
        mod=INNER
        + """

def deco(value):
    return lambda f: f


@deco(inner(1))
def outer(x, level=0.95, y=inner(2)):
    return x
""",
    )
    assert len(found) == 2


def test_a_marker_on_a_wrapped_header_covers_the_call_in_it(tmp_path: Path) -> None:
    """The header of a compound statement may wrap; its marker still counts."""
    found = _run(
        tmp_path,
        mod=INNER
        + """

def outer(x, level=0.95):
    if (  # preen: allow-dropped-arg
        inner(x)
    ):
        return 1
    return 0
""",
    )
    assert found == []


def test_a_marker_above_a_def_covers_calls_in_its_signature(tmp_path: Path) -> None:
    found = _run(
        tmp_path,
        mod=INNER
        + """

# preen: allow-dropped-arg
def outer(
    x,
    level=0.95,
    y=inner(1),
):
    return x
""",
    )
    assert found == []


def test_a_marker_on_a_decorator_line_covers_that_call(tmp_path: Path) -> None:
    """A def's header begins at its first decorator, not at `def`."""
    found = _run(
        tmp_path,
        mod=INNER
        + """

def outer(x, level=0.95):
    @inner(x)  # preen: allow-dropped-arg
    def helper():
        return 1

    return helper()
""",
    )
    assert found == []


def test_a_very_deep_expression_does_not_overflow(tmp_path: Path) -> None:
    """ast.parse copes with a 1,200-term sum; so must the walk over it."""
    terms = " + ".join(["inner(x)"] * 1200)
    found = _run(
        tmp_path,
        mod=INNER + f"\n\ndef outer(x, level=0.95):\n    return {terms}\n",
    )
    assert len(found) == 1200


def test_many_calls_in_one_statement_stay_fast(tmp_path: Path) -> None:
    import time

    entries = ",\n".join(["    inner(x)"] * 10000)
    started = time.time()
    found = _run(
        tmp_path,
        mod=INNER + f"\n\ndef outer(x, level=0.95):\n    return [\n{entries}\n]\n",
    )
    assert len(found) == 10000
    assert time.time() - started < 5
