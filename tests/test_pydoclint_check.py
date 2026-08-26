"""Tests for the pydoclint docstring-quality check."""

import subprocess
from pathlib import Path

from preen.checks.base import Impact, Severity
from preen.checks.pydoclint import PydoclintCheck


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_pydoclint_not_installed(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert issue.impact == Impact.CRITICAL
    assert "not installed" in issue.description


def test_no_issues_passes(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_a_docstring_violation_never_blocks_a_release(
    tmp_path: Path, monkeypatch
) -> None:
    """`Impact.CRITICAL` means security or a broken build; a docstring is not.

    Grading a public module's violations critical only became reachable once
    the parser started working, and it put sixteen release blocks on one fleet
    repo's `cli.py` for things like "__init__() should not have a docstring".
    canon's CI runs bare pydoclint as its own gate, so preen also refusing to
    tag adds a second veto and no information.
    """
    cli_file = tmp_path / "cli.py"
    output = f"{cli_file}:10: DOC101 Docstring contains fewer arguments\n"

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=1, stdout=output)

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()

    assert not result.passed, "the check still fails; it just does not gate"
    issue = result.issues[0]
    assert issue.impact == Impact.IMPORTANT
    assert not issue.is_blocking()
    assert issue.file == Path("cli.py")
    assert issue.line == 10


def test_flat_form_violation_in_regular_file_is_warning_and_important(
    tmp_path: Path, monkeypatch
) -> None:
    other = tmp_path / "helpers.py"
    output = f"{other}:5: DOC101 Docstring contains fewer arguments\n"

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=1, stdout=output)

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    issue = result.issues[0]
    assert issue.severity == Severity.WARNING
    assert issue.impact == Impact.IMPORTANT


def test_uses_repo_pyproject_config_when_present(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.pydoclint]\nstyle = "google"\n')
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    PydoclintCheck(tmp_path).run()
    run_cmd = calls[-1]
    assert "--config" in run_cmd
    assert "pyproject.toml" in run_cmd


def test_violations_on_stderr_are_parsed_not_reported_as_an_error(
    tmp_path: Path, monkeypatch
) -> None:
    """pydoclint writes its violations to stderr, not stdout.

    Reading only stdout meant every real finding surfaced as "pydoclint
    encountered an error" instead of as the violation it was, so the check
    could report a problem existed but never which one.
    """
    src = tmp_path / "thing.py"
    output = f"{src}:12: DOC101 Docstring contains fewer arguments\n"

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=1, stdout="", stderr=output)

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert "DOC101" in issue.description
    assert "encountered an error" not in issue.description
    assert issue.line == 12


def test_a_real_failure_to_run_is_still_reported_as_one(
    tmp_path: Path, monkeypatch
) -> None:
    """The error path must survive: output with no DOC code is a failure.

    pydoclint's own error text links to violation_codes.html#notes-on-doc103,
    so the discriminator has to be case-sensitive.
    """

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(
            cmd,
            returncode=2,
            stdout="",
            stderr="Usage: pydoclint [OPTIONS] [PATHS]...\nsee #notes-on-doc103\n",
        )

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert len(result.issues) == 1
    assert "encountered an error" in result.issues[0].description


def test_fallback_excludes_vendor_directories(tmp_path: Path, monkeypatch) -> None:
    """Without the repo's own exclude, pydoclint would walk .venv.

    On a synced repo that is every installed dependency: 34,696 lines of
    findings about OpenSSL and friends, none of them the repo's own code.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    PydoclintCheck(tmp_path).run()
    assert any(a.startswith("--exclude=") and ".venv" in a for a in calls[-1])


def test_pyproject_without_a_pydoclint_table_falls_back_to_google_style(
    tmp_path: Path, monkeypatch
) -> None:
    """Having a pyproject.toml is not the same as having [tool.pydoclint].

    pydoclint refuses to start when given ``--config`` for a file with no such
    table, so passing it unconditionally meant the check never ran: it reported
    a warning about its own invocation, and a repo with real docstring problems
    looked exactly like one with none. Eight of the twenty-six repos in
    py-canon's FLEET were in that state.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    PydoclintCheck(tmp_path).run()
    run_cmd = calls[-1]
    assert "--config" not in run_cmd
    assert "--style=google" in run_cmd


def test_unreadable_pyproject_falls_back_rather_than_crashing(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("this is not = valid toml [[[\n")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    PydoclintCheck(tmp_path).run()
    assert "--style=google" in calls[-1]


def test_no_pyproject_falls_back_to_google_style(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    PydoclintCheck(tmp_path).run()
    assert "--style=google" in calls[-1]


def test_stderr_error_with_no_stdout_reported(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.5\n")
        return _completed(cmd, returncode=1, stdout="", stderr="internal error")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert "internal error" in result.issues[0].description
    assert result.issues[0].impact == Impact.INFORMATIONAL


def test_can_fix_false(tmp_path: Path) -> None:
    assert PydoclintCheck(tmp_path).can_fix() is False


BLOCK_FORM_OUTPUT = """\
src/pkg/piecewise.py
    4: DOC101: Function `f`: Docstring contains fewer arguments than in \
function signature.
    4: DOC103: Function `f`: Docstring arguments are different from function \
arguments. (Or could be other formatting issues: \
https://jsh9.github.io/pydoclint/violation_codes.html#notes-on-doc103 ). \
Arguments in the function signature but not in the docstring: [b: ].
src/pkg/other.py
    17: DOC201: Function `g` does not have a return section in docstring
"""


def test_block_form_output_is_parsed(tmp_path: Path, monkeypatch) -> None:
    """pydoclint 0.9.1 emits a per-file header, not one path per line.

    The parser only understood the flat `path:10: DOC101 ...` form, so a real
    report matched nothing, `issues` came back empty, and `passed` was True on
    a package pydoclint had just rejected (issue #58).
    """

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.9.1\n")
        return _completed(cmd, returncode=1, stdout=BLOCK_FORM_OUTPUT)

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()

    assert not result.passed
    assert [issue.description.split(":")[0] for issue in result.issues] == [
        "DOC101",
        "DOC103",
        "DOC201",
    ]
    assert [issue.file for issue in result.issues] == [
        Path("src/pkg/piecewise.py"),
        Path("src/pkg/piecewise.py"),
        Path("src/pkg/other.py"),
    ]
    assert [issue.line for issue in result.issues] == [4, 4, 17]


def test_unparsable_violations_do_not_become_a_pass(
    tmp_path: Path, monkeypatch
) -> None:
    """A non-zero pydoclint exit must never come back green.

    Whatever layout pydoclint grows next, preen failing to read it is preen's
    problem to report, not a clean bill of health for the repo.
    """

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.9.1\n")
        return _completed(
            cmd, returncode=1, stdout="{'DOC101': 'some future json layout'}\n"
        )

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    result = PydoclintCheck(tmp_path).run()

    assert not result.passed
    assert "could not parse" in result.issues[0].description


def test_target_is_relative_so_ancestor_directories_cannot_exclude_the_repo(
    tmp_path: Path, monkeypatch
) -> None:
    """An absolute target lets the repo's own exclude regex match its parents.

    preen's own `exclude = '\\.venv|tests|docs'` matches any checkout under a
    path containing "docs", which would exclude every file and exit 0.
    """
    (tmp_path / "pyproject.toml").write_text('[tool.pydoclint]\nstyle = "google"\n')
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[-1] == "--version":
            return _completed(cmd, returncode=0, stdout="pydoclint 0.9.1\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.pydoclint.subprocess.run", fake_run)
    PydoclintCheck(tmp_path).run()

    assert calls[-1][-1] == "."
    assert str(tmp_path) not in calls[-1]


def test_real_pydoclint_binary_disagreeing_with_the_check_fails_it(
    tmp_path: Path,
) -> None:
    """Run the actual tool, because a stubbed one cannot catch a format change.

    Every other test here feeds the parser a string this file wrote, so they
    all passed while the parser understood a layout pydoclint had stopped
    emitting. This one is the only test that would have caught issue #58.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pdpkg"\nversion = "0.1.0"\n\n'
        '[tool.pydoclint]\nstyle = "google"\n'
    )
    package = tmp_path / "src" / "pdpkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Package."""\n')
    (package / "mod.py").write_text(
        '"""Module."""\n\n\ndef f(a, b):\n'
        '    """Do a thing.\n\n    Args:\n        a: first.\n    """\n'
        "    return a\n"
    )

    bare = subprocess.run(
        ["pydoclint", "--quiet", "--config", "pyproject.toml", "."],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert bare.returncode != 0, "fixture must be one pydoclint rejects"

    result = PydoclintCheck(tmp_path).run()

    assert not result.passed
    reported = {issue.description.split(":")[0] for issue in result.issues}
    emitted = set(PydoclintCheck._VIOLATION_RE.findall(bare.stdout or bare.stderr))
    assert reported == emitted
