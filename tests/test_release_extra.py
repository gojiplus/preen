"""Additional `preen release` coverage beyond the changelog gate

(test_release_gate.py): version suggestion/prompting, running checks,
the dirty-working-tree prompt, and git failure paths.
"""

import io
import subprocess
from pathlib import Path

import pytest
import rich.prompt
import typer
from rich.console import Console

import preen.commands.release as release_mod
from preen.checks.base import CheckResult, Impact, Issue, Severity
from preen.commands.release import _suggest_next, release_package

HAS_TARGET_VERSION = """\
# Changelog

## [Unreleased]

## [1.2.3] - 2026-01-01

- Stuff.
"""

UNRELEASED_NONEMPTY = """\
# Changelog

## [Unreleased]

### Added

- Something new.
"""


def _init_repo(repo: Path, changelog: str | None) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n")
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, no_color=True)


def test_suggest_next_bumps_patch() -> None:
    assert _suggest_next("v1.2.3") == "1.2.4"
    assert _suggest_next("1.2.3") == "1.2.4"


def test_suggest_next_no_tag_defaults_to_initial() -> None:
    assert _suggest_next(None) == "0.1.0"


def test_suggest_next_unparseable_tag_defaults_to_initial() -> None:
    assert _suggest_next("not-a-version") == "0.1.0"


def test_version_prompted_when_omitted(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    subprocess.run(["git", "tag", "v1.2.3"], cwd=tmp_path, check=True)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    monkeypatch.setattr(rich.prompt.Prompt, "ask", lambda *a, **k: "9.9.9")
    console = _console()

    with pytest.raises(typer.Exit):
        # No changelog entry for 9.9.9 -> aborts, but only after the
        # version prompt ran and was used.
        release_package(tmp_path, version=None, skip_checks=True, console=console)

    assert "no changelog entry for 9.9.9" in console.file.getvalue()


def test_runs_checks_when_not_skipped(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    calls = {}

    def fake_run_checks(project_dir, checks):
        calls["ran"] = True
        return {}

    monkeypatch.setattr(release_mod, "run_checks", fake_run_checks)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=False, console=console)

    assert calls["ran"] is True
    assert "Running pre-release checks" in console.file.getvalue()


def test_critical_check_failure_cancels_release(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    issue = Issue(
        check="deptree",
        severity=Severity.ERROR,
        description="circular import",
        impact=Impact.CRITICAL,
    )
    monkeypatch.setattr(
        release_mod,
        "run_checks",
        lambda project_dir, checks: {
            "deptree": CheckResult(check="deptree", passed=False, issues=[issue])
        },
    )
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=False, console=console)

    assert "Release cancelled" in console.file.getvalue()


def test_dirty_tree_prompt_declined_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    (tmp_path / "README.md").write_text("dirty change\n")

    def fake_confirm(prompt="", **kwargs):
        return "Tag anyway" not in prompt  # decline the dirty-tree prompt only

    monkeypatch.setattr(rich.prompt.Confirm, "ask", fake_confirm)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    assert "not clean" in console.file.getvalue()


def test_dirty_tree_prompt_accepted_continues(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    (tmp_path / "README.md").write_text("dirty change\n")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    # Push fails (no remote) -> still raises, but only after accepting the
    # dirty-tree prompt and creating the tag.
    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    result = subprocess.run(
        ["git", "tag", "-l", "v1.2.3"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "v1.2.3"


def test_git_add_failure_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)

    real_git = release_mod._git

    def fake_git(project_dir, *args):
        if args and args[0] == "add":
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=1, stdout="", stderr="add failed"
            )
        return real_git(project_dir, *args)

    monkeypatch.setattr(release_mod, "_git", fake_git)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.0.0", skip_checks=True, console=console)

    assert "git add failed" in console.file.getvalue()


def test_git_commit_failure_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)

    real_git = release_mod._git

    def fake_git(project_dir, *args):
        if args and args[0] == "commit":
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=1, stdout="", stderr="commit failed"
            )
        return real_git(project_dir, *args)

    monkeypatch.setattr(release_mod, "_git", fake_git)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.0.0", skip_checks=True, console=console)

    assert "git commit failed" in console.file.getvalue()


def test_git_tag_failure_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)

    real_git = release_mod._git

    def fake_git(project_dir, *args):
        if args and args[0] == "tag" and len(args) > 1:
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=1, stdout="", stderr="tag failed"
            )
        return real_git(project_dir, *args)

    monkeypatch.setattr(release_mod, "_git", fake_git)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    assert "git tag failed" in console.file.getvalue()


def test_git_push_failure_keeps_local_tag(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    output = console.file.getvalue()
    assert "git push failed" in output
    assert "still exists; push it manually" in output
    result = subprocess.run(
        ["git", "tag", "-l", "v1.2.3"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "v1.2.3"
