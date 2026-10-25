"""Tests for the duplicate-code check, which runs jscpd."""

from pathlib import Path

from preen.checks.duplicates import DuplicateCodeCheck

# Literal sizes at the boundary, not offsets from the module's threshold: a
# test sized from the constant follows any change to it and cannot catch one.
# Exactly 12 is the case that once slipped.
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
    _write(tmp_path / "pkg", "first.py", body)
    (tmp_path / "pkg" / "second.py").write_text(
        "# jscpd:ignore-start\n"
        f"def second(a, b):\n{body}\n    return 'second'\n"
        "# jscpd:ignore-end\n"
    )

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_scripts_beside_the_package_are_not_package_code(tmp_path: Path) -> None:
    body = _block(COPIED)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    _write(tmp_path / "scripts", "train_one.py", body)
    _write(tmp_path / "scripts", "train_two.py", body)
    _write(tmp_path, "setup_tool.py", body)

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_a_jscpd_that_cannot_run_fails_the_check(tmp_path: Path, monkeypatch) -> None:
    # A missing detector must not read as "no duplicates".
    from preen.checks import duplicates

    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)
    monkeypatch.setattr(duplicates, "_jscpd", lambda: tmp_path / "no-jscpd")

    result = DuplicateCodeCheck(tmp_path).run()

    assert not result.passed
    assert "failed to run" in result.issues[0].description


def test_runs_without_jscpd_on_path(tmp_path: Path, monkeypatch) -> None:
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


def test_a_file_that_cannot_parse_fails_the_check(tmp_path: Path) -> None:
    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)
    (tmp_path / "pkg" / "broken.py").write_text("def broken(:\n    pass\n")

    result = DuplicateCodeCheck(tmp_path).run()

    assert not result.passed
    assert "cannot parse" in result.issues[0].description


def test_namespace_packages_under_src_are_scanned(tmp_path: Path) -> None:
    body = _block(COPIED)
    widgets = tmp_path / "src" / "acme" / "widgets"  # no src/acme/__init__.py
    _write(widgets, "first.py", body)
    _write(widgets, "second.py", body)
    (widgets / "__init__.py").touch()

    assert len(DuplicateCodeCheck(tmp_path).run().issues) == 1


def test_a_tracked_file_deleted_from_the_tree_is_skipped(tmp_path: Path) -> None:
    import subprocess

    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    (tmp_path / "pkg" / "second.py").unlink()

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_a_copy_within_one_module_is_reported(tmp_path: Path) -> None:
    # pylint compared files pairwise and never a file with itself.
    body = _block(COPIED)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").touch()
    (pkg / "only.py").write_text(
        f"def first(a, b):\n{body}\n    return 1\n\n\n"
        f"def second(a, b):\n{body}\n    return 2\n"
    )

    issues = DuplicateCodeCheck(tmp_path).run().issues

    assert len(issues) == 1
    assert issues[0].description.count("pkg/only.py") == 2


def test_a_consistently_renamed_copy_is_reported(tmp_path: Path) -> None:
    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body.replace("v", "w").replace("a *", "x *"))
    (tmp_path / "pkg" / "second.py").write_text(
        (tmp_path / "pkg" / "second.py").read_text().replace("(a, b)", "(x, b)")
    )

    assert len(DuplicateCodeCheck(tmp_path).run().issues) == 1


def test_docstrings_and_signatures_do_not_count_toward_the_threshold(
    tmp_path: Path,
) -> None:
    # Parallel public wrappers share long signatures and docstrings by design.
    params = ",\n".join(f"    p{i}: int = {i}" for i in range(14))
    doc = "\n".join(f"    line {i} of the docstring" for i in range(14))
    for name in ("first", "second"):
        _write(tmp_path / "pkg", f"{name}.py", "")
        (tmp_path / "pkg" / f"{name}.py").write_text(
            f'def {name}(\n{params},\n) -> int:\n    """Doc.\n\n{doc}\n    """\n'
            f"{_block(SHORT)}\n    return {name!r}\n"
        )

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_three_copies_are_one_finding(tmp_path: Path) -> None:
    body = _block(COPIED)
    for name in ("first.py", "second.py", "third.py"):
        _write(tmp_path / "pkg", name, body)

    issues = DuplicateCodeCheck(tmp_path).run().issues

    assert len(issues) == 1
    assert all(n in issues[0].description for n in ("first", "second", "third"))


def test_repetitive_code_matching_itself_is_not_a_copy(tmp_path: Path) -> None:
    # A run of near-identical lines matches a shifted copy of itself.
    lines = "\n".join(f"    total = total + values[{i % 2}]" for i in range(30))
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").touch()
    (tmp_path / "pkg" / "sums.py").write_text(
        f"def accumulate(values):\n    total = 0\n{lines}\n    return total\n"
    )

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_copied_decorator_arguments_count(tmp_path: Path) -> None:
    # Tool schemas and click options live in decorator arguments.
    schema = "\n".join(
        f'        "field{i}": {{"type": "number", "min": {i}}},' for i in range(14)
    )
    for name in ("first", "second"):
        _write(tmp_path / "pkg", f"{name}.py", "")
        (tmp_path / "pkg" / f"{name}.py").write_text(
            f"@tool(\n    schema={{\n{schema}\n    }},\n)\n"
            f"def {name}(a, b):\n    return {name!r}\n"
        )

    assert len(DuplicateCodeCheck(tmp_path).run().issues) == 1


def test_decorators_on_a_class_first_method_count(tmp_path: Path) -> None:
    # The class's signature ends where its body starts; the first method's
    # decorators are body, not signature.
    schema = "\n".join(
        f'        "field{i}": {{"type": "number", "min": {i}}},' for i in range(14)
    )
    for name in ("First", "Second"):
        _write(tmp_path / "pkg", f"{name.lower()}.py", "")
        (tmp_path / "pkg" / f"{name.lower()}.py").write_text(
            f"class {name}:\n    @tool(\n        schema={{\n{schema}\n        }},\n"
            f"    )\n    def run(self, a, b):\n        return {name!r}\n"
        )

    assert len(DuplicateCodeCheck(tmp_path).run().issues) == 1


def test_copies_that_differ_only_in_comments_are_reported(tmp_path: Path) -> None:
    lines = [f"    v{i} = a * {i} + b - {i * i}" for i in range(COPIED)]
    _write(
        tmp_path / "pkg",
        "first.py",
        "\n".join(f"{line}  # first {i}" for i, line in enumerate(lines)),
    )
    _write(
        tmp_path / "pkg",
        "second.py",
        "\n".join(f"{line}  # second note {i}" for i, line in enumerate(lines)),
    )

    assert len(DuplicateCodeCheck(tmp_path).run().issues) == 1


def test_non_ascii_text_does_not_stretch_a_short_copy(tmp_path: Path) -> None:
    # jscpd reports byte columns; a partly matched last line with multibyte
    # text before the difference must still not count.
    body = _block(SHORT)
    for name, tail in (("first", "one"), ("second", "two")):
        _write(
            tmp_path / "pkg",
            f"{name}.py",
            f'{body}\n    r = "你好世界你好世界" + "{tail}"',
        )

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_non_ascii_text_on_full_lines_still_counts(tmp_path: Path) -> None:
    body = "\n".join(f'    v{i} = "名前{i}" * {i} + b' for i in range(COPIED))
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)

    assert len(DuplicateCodeCheck(tmp_path).run().issues) == 1


def test_files_python_can_read_are_measured(tmp_path: Path) -> None:
    # A BOM and a coding declaration are valid source, not parse failures.
    pkg = tmp_path / "pkg"
    _write(pkg, "plain.py", _block(SHORT))
    (pkg / "bom.py").write_bytes(b"\xef\xbb\xbfdef f(a, b):\n    return a\n")
    (pkg / "latin.py").write_bytes(
        b"# coding: latin-1\ndef g(a, b):\n    return 'caf\xe9'\n"
    )

    assert DuplicateCodeCheck(tmp_path).run().passed


def test_a_repository_jscpd_config_does_not_change_the_check(tmp_path: Path) -> None:
    body = _block(COPIED)
    _write(tmp_path / "pkg", "first.py", body)
    _write(tmp_path / "pkg", "second.py", body)
    (tmp_path / ".jscpd.json").write_text(
        '{"threshold": 0, "reportName": "clones", "minLines": 100}'
    )

    issues = DuplicateCodeCheck(tmp_path).run().issues

    assert len(issues) == 1
    assert "duplicated lines" in issues[0].description


def test_finds_a_jscpd_installed_outside_the_interpreter_scripts_dir(
    tmp_path: Path, monkeypatch
) -> None:
    # pip --user puts scripts in the user base, not beside the interpreter.
    import sysconfig

    from preen.checks import duplicates

    real = duplicates._jscpd()
    monkeypatch.setattr(sysconfig, "get_path", lambda *a, **k: str(tmp_path / "x"))
    monkeypatch.setenv("PATH", "")

    assert duplicates._jscpd() == real


def test_a_bom_does_not_shift_the_first_line_out_of_a_copy(tmp_path: Path) -> None:
    # jscpd counts the BOM's three bytes in line 1's columns.
    pkg = tmp_path / "pkg"
    _write(pkg, "unused.py", "    return None")
    body = "".join(f"v{i} = {i} * 7 + {i * i}\n" for i in range(COPIED))
    (pkg / "first.py").write_bytes(b"\xef\xbb\xbf" + body.encode() + b"w = 1\n")
    (pkg / "second.py").write_text(body + "w = 2\n")

    assert len(DuplicateCodeCheck(tmp_path).run().issues) == 1
