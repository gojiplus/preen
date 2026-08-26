"""Additional `preen release` coverage beyond the changelog gate."""

import io
import subprocess
from pathlib import Path

import pytest
import rich.prompt
import typer
from rich.console import Console

import preen.commands.release as release_mod
from preen.checks.base import CheckResult, Impact, Issue, Severity
from preen.commands.release import release_package


@pytest.fixture(autouse=True)
def _no_artifact_build(monkeypatch) -> None:
    """Skip the build gate, which these fixtures are too minimal to satisfy.

    `release_package` builds the distributions and runs twine over them before
    tagging. That is the point of the gate, and it has its own tests; here it
    would just make every case a 3-second `uv build` of a repo with no package
    in it. See test_release_artifacts.py.

    Args:
        monkeypatch: pytest fixture.
    """
    monkeypatch.setattr(release_mod, "_artifact_error", lambda project_dir: None)


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


def _init_repo(
    repo: Path, changelog: str | None, version: str | None = "1.2.3"
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n")
    if version is not None:
        (repo / "pyproject.toml").write_text(
            f'[project]\nname = "example"\nversion = "{version}"\n'
        )
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, no_color=True)


def test_missing_project_version_rejected(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION, version=None)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version=None, skip_checks=True, console=console)

    assert "pyproject.toml is required for release" in console.file.getvalue()


def test_dynamic_project_version_rejected(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION, version=None)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\ndynamic = ["version"]\n'
    )
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "dynamic version"], cwd=tmp_path, check=True
    )
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    assert "project.version must be declared explicitly" in console.file.getvalue()
    assert not subprocess.run(
        ["git", "tag", "-l", "v1.2.3"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_uncommitted_lockfile_cannot_be_tagged(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text("version = 1\nrevision = 3\n")
    subprocess.run(["git", "add", "uv.lock"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add lockfile"], cwd=tmp_path, check=True
    )
    lockfile.write_text("version = 1\nrevision = 3\n# dirty\n")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    assert "uv.lock has uncommitted changes" in console.file.getvalue()
    assert not subprocess.run(
        ["git", "tag", "-l", "v1.2.3"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_deleted_lockfile_cannot_be_tagged(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text("version = 1\nrevision = 3\n")
    subprocess.run(["git", "add", "uv.lock"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add lockfile"], cwd=tmp_path, check=True
    )
    lockfile.unlink()
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    assert "uv.lock has uncommitted changes" in console.file.getvalue()
    assert not subprocess.run(
        ["git", "tag", "-l", "v1.2.3"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_stale_committed_lockfile_cannot_be_tagged(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    (tmp_path / "uv.lock").write_text("version = 1\nrevision = 3\n")
    subprocess.run(["git", "add", "uv.lock"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add stale lockfile"],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    monkeypatch.setattr(
        release_mod.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "stale"),
    )
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    assert "uv.lock is not up to date" in console.file.getvalue()


def test_project_version_used_when_version_omitted(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    with pytest.raises(typer.Exit):
        release_package(tmp_path, version=None, skip_checks=True, console=_console())

    assert (
        subprocess.run(
            ["git", "tag", "-l", "v1.2.3"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        == "v1.2.3"
    )


def test_requested_version_must_match_project_version(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.4", skip_checks=True, console=console)

    assert "does not match project.version 1.2.3" in console.file.getvalue()


def test_uncommitted_project_version_cannot_be_tagged(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION, version="1.2.2")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1.2.3"\n'
    )
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    assert "pyproject.toml has uncommitted changes" in console.file.getvalue()
    assert not subprocess.run(
        ["git", "tag", "-l", "v1.2.3"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_deleted_pyproject_cannot_be_tagged(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.unlink()
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)

    assert "pyproject.toml has uncommitted changes" in console.file.getvalue()


def test_project_version_is_normalized_for_tagging(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "v1.2.3"\n'
    )
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "set version"], cwd=tmp_path, check=True
    )
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version=None, skip_checks=True, console=_console())

    assert (
        subprocess.run(
            ["git", "tag", "-l", "v1.2.3"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        == "v1.2.3"
    )


def test_non_string_project_version_rejected(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = 1.2\n'
    )
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "set malformed version"],
        cwd=tmp_path,
        check=True,
    )
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2", skip_checks=True, console=console)

    assert "project.version must be a string" in console.file.getvalue()


def test_runs_checks_when_not_skipped(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    calls = {}

    def fake_run_checks(project_dir, checks, skip=None, only=None):
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
        lambda project_dir, checks, skip=None, only=None: {
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


def test_config_skip_checks_forwarded_to_release_checks(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    (tmp_path / "pyproject.toml").write_text('[tool.preen]\nskip_checks = ["links"]\n')
    monkeypatch.setattr(rich.prompt.Confirm, "ask", lambda *a, **k: True)
    calls = {}

    def fake_run_checks(project_dir, checks, skip=None, only=None):
        calls["skip"] = skip
        return {}

    monkeypatch.setattr(release_mod, "run_checks", fake_run_checks)

    with pytest.raises(typer.Exit):
        release_package(
            tmp_path, version="1.2.3", skip_checks=False, console=_console()
        )

    assert calls["skip"] == ["links"]


def test_git_commit_failure_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="1.0.0")
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
