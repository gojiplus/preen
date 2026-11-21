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
