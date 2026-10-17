"""Tests for the duplicate-code check, which runs pylint's R0801 detector."""

from pathlib import Path

from preen.checks.duplicates import DuplicateCodeCheck

# Literal sizes, not offsets from the module's threshold: a test sized from the
# constant follows any change to it and cannot catch one.
COPIED = 14
SHORT = 8


def _block(n: int) -> str:
    """Return a function body of n distinct, non-trivial lines."""
    return "\n".join(f"    v{i} = a * {i} + b - {i * i}" for i in range(n))


def _write(directory: Path, name: str, body: str, marker: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        f"def {name[:-3]}(a, b):\n{marker}{body}\n    return v0\n"
    )


def test_a_copied_block_across_modules_is_reported(tmp_path: Path) -> None:
    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)

    issues = DuplicateCodeCheck(tmp_path).run().issues

    assert len(issues) == 1
    assert "first" in issues[0].description
    assert "second" in issues[0].description


def test_a_short_shared_block_is_not_reported(tmp_path: Path) -> None:
    body = _block(SHORT)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_tests_and_examples_may_repeat_themselves(tmp_path: Path) -> None:
    body = _block(COPIED)
    _write(tmp_path / "tests", "test_one.py", body)
    _write(tmp_path / "tests", "test_two.py", body)
    _write(tmp_path / "examples", "demo_one.py", body)
    _write(tmp_path / "examples", "demo_two.py", body)

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_a_deliberate_copy_can_be_marked(tmp_path: Path) -> None:
    body = _block(COPIED)
    marker = "    # pylint: disable=duplicate-code\n"
    _write(tmp_path / "pkg", "first.py", body, marker)
    _write(tmp_path / "pkg", "second.py", body, marker)

    assert DuplicateCodeCheck(tmp_path).run().passed
