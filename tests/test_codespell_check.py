"""Tests for the codespell check: subprocess boundary + a live integration."""

import subprocess
from pathlib import Path

import pytest

from preen.checks.base import Impact, Issue, Severity
from preen.checks.codespell import CodespellCheck, is_auto_fixable

# Assembled rather than written literally so this file's own source text
# never contains a misspelling that codespell (including preen's own
# `codespell` check running on this repo) would flag.
_TEH = "t" + "eh"
_MISPELLING = "misp" + "elling"


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_codespell_not_installed(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("preen.checks.codespell.subprocess.run", fake_run)
    result = CodespellCheck(tmp_path).run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert issue.impact == Impact.CRITICAL
    assert "not installed" in issue.description


def test_clean_repo_passes(tmp_path: Path, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd == ["codespell", "--version"]:
            return _completed(cmd, returncode=0, stdout="codespell 2.4\n")
        return _completed(cmd, returncode=0, stdout="")

    monkeypatch.setattr("preen.checks.codespell.subprocess.run", fake_run)
    result = CodespellCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_misspellings_parsed_into_issues(tmp_path: Path, monkeypatch) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"{_TEH} quick fox\n")
    output = f"{readme}:1: {_TEH} ==> the\n"

    def fake_run(cmd, **kwargs):
        if cmd == ["codespell", "--version"]:
            return _completed(cmd, returncode=0, stdout="codespell 2.4\n")
        if "--diff" in cmd:
            return _completed(cmd, returncode=1, stdout="--- diff ---\n")
        return _completed(cmd, returncode=1, stdout=output)

    monkeypatch.setattr("preen.checks.codespell.subprocess.run", fake_run)
    result = CodespellCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.WARNING
    assert issue.impact == Impact.CRITICAL  # README is a critical file
    assert _TEH in issue.description
    assert "the" in issue.description
    assert issue.file == Path("README.md")
    assert issue.line == 1
    assert issue.proposed_fix is not None
    assert issue.proposed_fix.diff == "--- diff ---\n"


def test_impact_downgraded_for_non_doc_files(tmp_path: Path, monkeypatch) -> None:
    misc = tmp_path / "config.yaml"
    misc.write_text("{}\n")
    output = f"{misc}:1: {_TEH} ==> the\n"

    def fake_run(cmd, **kwargs):
        if cmd == ["codespell", "--version"]:
            return _completed(cmd, returncode=0, stdout="codespell 2.4\n")
        if "--diff" in cmd:
            return _completed(cmd, returncode=1, stdout="")
        return _completed(cmd, returncode=1, stdout=output)

    monkeypatch.setattr("preen.checks.codespell.subprocess.run", fake_run)
    result = CodespellCheck(tmp_path).run()
    assert result.issues[0].impact == Impact.INFORMATIONAL


def test_nonzero_exit_with_stderr_only_parses_as_output(
    tmp_path: Path, monkeypatch
) -> None:
    """Misspellings can land on stderr; they're parsed the same as stdout."""
    readme = tmp_path / "README.md"
    readme.write_text(f"{_TEH}\n")
    output = f"{readme}:1: {_TEH} ==> the\n"

    def fake_run(cmd, **kwargs):
        if cmd == ["codespell", "--version"]:
            return _completed(cmd, returncode=0, stdout="codespell 2.4\n")
        if "--diff" in cmd:
            return _completed(cmd, returncode=1, stdout="")
        return _completed(cmd, returncode=1, stdout="", stderr=output)

    monkeypatch.setattr("preen.checks.codespell.subprocess.run", fake_run)
    result = CodespellCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert _TEH in result.issues[0].description


def test_nonzero_exit_truly_no_output_reports_error(
    tmp_path: Path, monkeypatch
) -> None:
    """A non-zero exit with nothing on stdout or stderr degrades to a

    single informational "codespell error" note instead of silently
    passing.
    """
    (tmp_path / "README.md").write_text("ordinary text\n")

    def fake_run(cmd, **kwargs):
        if cmd == ["codespell", "--version"]:
            return _completed(cmd, returncode=0, stdout="codespell 2.4\n")
        return _completed(cmd, returncode=1, stdout="", stderr="")

    monkeypatch.setattr("preen.checks.codespell.subprocess.run", fake_run)
    result = CodespellCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.impact == Impact.INFORMATIONAL
    assert "codespell exited with code 1" in issue.description


def test_can_fix_true(tmp_path: Path) -> None:
    assert CodespellCheck(tmp_path).can_fix() is True


def test_live_codespell_on_clean_and_dirty_fixture(tmp_path: Path) -> None:
    """Real codespell binary against a tmp fixture -- no network, fast."""
    (tmp_path / "README.md").write_text("This is a perfectly normal sentence.\n")
    result = CodespellCheck(tmp_path).run()
    assert result.passed

    (tmp_path / "README.md").write_text(f"This has an {_MISPELLING} in it.\n")
    result = CodespellCheck(tmp_path).run()
    assert not result.passed
    assert any(_MISPELLING in i.description for i in result.issues)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("README.md", True),
        ("docs/guide.rst", True),
        ("src/pkg/mod.py", True),
        ("notes.txt", True),
        # Data fixtures: a "misspelling" may be a real proper noun.
        ("tests/data/transcript.txt", False),
        ("tests/fixtures/names.md", False),
        ("testdata/x.py", False),
        ("samples/y.txt", False),
        # Non-prose formats preen has no business rewriting unattended.
        ("data.json", False),
        ("config.yaml", False),
        ("table.csv", False),
    ],
)
def test_auto_fixable_classification(path: str, expected: bool) -> None:
    assert is_auto_fixable(Path(path)) is expected


def test_codespell_reads_pyproject_config(tmp_path: Path) -> None:
    """codespell only honors [tool.codespell] when given --toml (issue #19)."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    cmd = CodespellCheck(tmp_path)._get_codespell_command()
    assert "--toml" in cmd
    assert cmd[cmd.index("--toml") + 1] == str(tmp_path / "pyproject.toml")


def test_codespell_target_is_relative(tmp_path: Path) -> None:
    """Absolute targets make repo-relative skip globs unmatchable."""
    assert CodespellCheck(tmp_path)._get_codespell_command()[-1] == "."
    assert (
        CodespellCheck(tmp_path)._get_codespell_command(Path("a/b.md"))[-1] == "a/b.md"
    )


def test_candidate_files_honor_gitignore_and_skip_data(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("cache/\n")
    (tmp_path / "README.md").write_text("checked\n")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "page.html").write_text("ignored\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "training.txt").write_text("external text\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("checked = True\n")

    assert CodespellCheck(tmp_path)._candidate_files() == [
        Path("README.md"),
        Path("src/module.py"),
    ]


def test_candidate_files_fall_back_when_git_fails(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("checked\n")

    def fail_git(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("preen.checks.codespell.subprocess.run", fail_git)

    assert CodespellCheck(tmp_path)._candidate_files() == [Path("README.md")]


def test_candidate_files_are_batched(tmp_path: Path, monkeypatch) -> None:
    candidates = [Path(f"docs/page-{index}.md") for index in range(201)]
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        if cmd == ["codespell", "--version"]:
            return _completed(cmd, returncode=0, stdout="codespell 2.4\n")
        calls.append(cmd)
        return _completed(cmd, returncode=0)

    monkeypatch.setattr(CodespellCheck, "_candidate_files", lambda self: candidates)
    monkeypatch.setattr("preen.checks.codespell.subprocess.run", fake_run)

    assert CodespellCheck(tmp_path).run().passed
    assert len(calls) == 2
    assert calls[0][-200:] == [str(path) for path in candidates[:200]]
    assert calls[1][-1] == str(candidates[-1])


def test_fix_per_file_and_data_needs_confirmation(tmp_path: Path) -> None:
    check = CodespellCheck(tmp_path)
    issues = [
        Issue(
            check="codespell",
            severity=Severity.WARNING,
            description="a",
            file=Path("README.md"),
            line=1,
        ),
        Issue(
            check="codespell",
            severity=Severity.WARNING,
            description="b",
            file=Path("README.md"),
            line=2,
        ),
        Issue(
            check="codespell",
            severity=Severity.WARNING,
            description="c",
            file=Path("tests/data/names.txt"),
            line=1,
        ),
    ]
    check._attach_fixes(issues)

    # One fix per file, attached to that file's first issue.
    assert issues[0].proposed_fix is not None
    assert issues[1].proposed_fix is None
    assert issues[2].proposed_fix is not None

    assert issues[0].proposed_fix.requires_confirmation is False
    assert issues[2].proposed_fix.requires_confirmation is True
    assert "2 spelling error(s)" in issues[0].proposed_fix.description
