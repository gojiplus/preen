"""Tests for the duplicate-code check, which runs pylint's R0801 detector."""

from pathlib import Path

from preen.checks.duplicates import DuplicateCodeCheck

# Literal sizes at the boundary, not offsets from the module's threshold: a
# test sized from the constant follows any change to it and cannot catch one.
# pylint compares strictly, so exactly 12 is the case that once slipped.
COPIED = 12
SHORT = 11


def _block(n: int) -> str:
    """Return a function body of n distinct, non-trivial lines."""
    return "\n".join(f"    v{i} = a * {i} + b - {i * i}" for i in range(n))


def _write(directory: Path, name: str, body: str, marker: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if directory.name == "pkg":
        (directory / "__init__.py").touch()
    (directory / name).write_text(
        # A distinct return per copy, so the shared run is exactly the body.
        f"def {name[:-3]}(a, b):\n{marker}{body}\n    return {name[:-3]!r}\n"
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


def test_scripts_beside_the_package_are_not_package_code(tmp_path: Path) -> None:
    body = _block(COPIED)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    _write(tmp_path / "scripts", "train_one.py", body)
    _write(tmp_path / "scripts", "train_two.py", body)
    _write(tmp_path, "setup_tool.py", body)

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_a_pylint_that_cannot_run_fails_the_check(tmp_path: Path) -> None:
    # pylint exits 32 on a bad configuration with nothing on stdout, which
    # once read as "no duplicates".
    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)
    (tmp_path / ".pylintrc").write_text("[MAIN]\njobs=auto\n")

    result = DuplicateCodeCheck(tmp_path).run()

    assert not result.passed
    assert "failed to run" in result.issues[0].description


def test_runs_without_pylint_on_path(tmp_path: Path, monkeypatch) -> None:
    # uv tool and pipx expose only preen's own entry point.
    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)
    monkeypatch.setenv("PATH", "")

    assert len(DuplicateCodeCheck(tmp_path).run().issues) == 1


def test_git_ignored_files_in_the_package_are_skipped(tmp_path: Path) -> None:
    import subprocess

    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg" / "scratch", "second.py", body)
    (tmp_path / ".gitignore").write_text("pkg/scratch/\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    assert DuplicateCodeCheck(tmp_path).run().passed
