"""Tests for the skip-on-error check.

The first case is a reduction of a real suite, in which nine handlers like it
hid three failing assertions.
"""

from pathlib import Path

from preen.checks.skip_on_error import SkipOnErrorCheck, find_skip_on_error


def test_a_skip_that_hides_a_failed_assertion_is_found() -> None:
    src = """
def test_monotone():
    for x in cases:
        try:
            assert fit(x).monotone
        except Exception:
            pytest.skip("solver not available")
"""
    assert find_skip_on_error(src) == [(6, True)]


def test_bare_except_and_tuples_count_as_broad() -> None:
    src = """
try:
    run()
except:
    pytest.skip("x")
try:
    run()
except (ImportError, BaseException):
    self.skipTest("x")
"""
    assert find_skip_on_error(src) == [(4, False), (8, False)]


def test_a_specific_exception_is_not_flagged() -> None:
    src = "try:\n    import rich\nexcept ImportError:\n    pytest.skip('no rich')\n"
    assert find_skip_on_error(src) == []


def test_skipping_after_inspecting_the_error_and_reraising_is_not_flagged() -> None:
    src = """
try:
    assert optimize(x) >= best
except Exception as e:
    if "not implemented" in str(e):
        pytest.skip("not available")
    raise
"""
    assert find_skip_on_error(src) == []


def test_the_allow_marker_suppresses() -> None:
    src = (
        "try:\n    fetch()\n"
        "except Exception:  # preen: allow-skip-on-error - network only\n"
        "    pytest.skip('offline')\n"
    )
    assert find_skip_on_error(src) == []


def test_the_check_reads_test_modules_and_conftest_only(tmp_path: Path) -> None:
    body = "try:\n    assert f()\nexcept Exception:\n    pytest.skip('x')\n"
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(body)
    (tmp_path / "tests" / "conftest.py").write_text(body)
    (tmp_path / "helpers.py").write_text(body)
    result = SkipOnErrorCheck(tmp_path).run()
    assert not result.passed
    assert sorted(str(i.file) for i in result.issues) == [
        "tests/conftest.py",
        "tests/test_a.py",
    ]
    assert "failed assertion" in result.issues[0].description


# Findings from the 0.11.0 release review, one test each.


def test_a_raise_before_the_skip_makes_it_conditional() -> None:
    src = (
        "try:\n    assert False\nexcept Exception as err:\n"
        "    if not isinstance(err, ImportError):\n        raise\n"
        "    pytest.skip('unavailable')\n"
    )
    assert find_skip_on_error(src) == []


def test_an_earlier_assertion_handler_changes_the_diagnosis() -> None:
    src = (
        "try:\n    assert False\nexcept AssertionError:\n    raise\n"
        "except Exception:\n    pytest.skip('x')\n"
    )
    assert find_skip_on_error(src) == [(5, False)]


def test_a_package_exception_named_exception_is_narrow() -> None:
    src = "try:\n    assert f()\nexcept External.Exception:\n    pytest.skip('x')\n"
    assert find_skip_on_error(src) == []


def test_a_mark_is_not_a_skip() -> None:
    src = (
        "try:\n"
        "    assert f()\n"
        "except Exception:\n"
        "    pytest.mark.skip(reason='x')\n"
        "    raise\n"
    )
    assert find_skip_on_error(src) == []


def test_returned_and_aliased_skips_count() -> None:
    returned = "try:\n    assert f()\nexcept Exception:\n    return pytest.skip('x')\n"
    aliased = (
        "from pytest import skip as unavailable\n"
        "try:\n    assert f()\nexcept Exception:\n    unavailable('x')\n"
    )
    assert find_skip_on_error(returned) == [(3, True)]
    assert find_skip_on_error(aliased) == [(4, True)]


def test_the_marker_counts_only_in_a_comment() -> None:
    in_string = (
        "try:\n    f()\nexcept Exception: pytest.skip('preen: allow-skip-on-error')\n"
    )
    assert find_skip_on_error(in_string) == [(3, False)]


def test_the_marker_survives_a_line_separator_in_an_earlier_string() -> None:
    src = (
        "S = 'a\u2028b'\n"
        "try:\n    f()\nexcept Exception:  # preen: allow-skip-on-error\n"
        "    pytest.skip('offline')\n"
    )
    assert find_skip_on_error(src) == []


def test_latin1_and_bom_sources_are_scanned() -> None:
    body = "try:\n    f()\nexcept Exception:\n    pytest.skip('x')\n"
    latin1 = ("# -*- coding: latin-1 -*-\nS = 'caf\u00e9'\n" + body).encode("latin-1")
    bom = ("\ufeff" + body).encode("utf-8")
    assert len(find_skip_on_error(latin1)) == 1
    assert len(find_skip_on_error(bom)) == 1
