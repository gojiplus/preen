"""Tests for the changelog release gate in `preen release`."""

import io
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import rich.prompt
import typer
from rich.console import Console

import preen.commands.release as release_mod
from preen.checks.changelog import has_version_entry, unreleased_section_text
from preen.commands.release import release_package

UNRELEASED_NONEMPTY = """\
# Changelog

## [Unreleased]

### Added

- Something new.
"""

UNRELEASED_EMPTY = """\
# Changelog

## [Unreleased]

## [0.1.0] - 2026-01-01

- Initial release.
"""

HAS_TARGET_VERSION = """\
# Changelog

## [Unreleased]

## [1.2.3] - 2026-01-01

- Stuff.
"""


def _init_repo(repo: Path, changelog: str | None, version: str = "1.2.3") -> None:
    """Init a git repo at `repo`, optionally with a CHANGELOG.md, and commit."""
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n")
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "example"\nversion = "{version}"\n'
    )
    if changelog is not None:
        (repo / "CHANGELOG.md").write_text(changelog)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _tag_exists(repo: Path, tag: str) -> bool:
    result = subprocess.run(
        ["git", "tag", "-l", tag], cwd=repo, capture_output=True, text=True, check=True
    )
    return bool(result.stdout.strip())


def _confirm_always(value: bool) -> Callable[..., bool]:
    def _ask(prompt: str = "", **kwargs: object) -> bool:
        return value

    return _ask


def _confirm_by_keyword(
    responses: dict[str, bool], default: bool = True
) -> Callable[..., bool]:
    def _ask(prompt: str = "", **kwargs: object) -> bool:
        for keyword, value in responses.items():
            if keyword in prompt:
                return value
        return default

    return _ask


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, no_color=True)


def test_invalid_pep440_version_rejected(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(
            tmp_path,
            version="not-a-version",
            skip_checks=True,
            console=console,
        )

    output = console.file.getvalue()
    assert "not-a-version" in output
    assert not _tag_exists(tmp_path, "vnot-a-version")


def test_existing_tag_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    subprocess.run(["git", "tag", "v1.2.3"], cwd=tmp_path, check=True)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(
            tmp_path,
            version="1.2.3",
            skip_checks=True,
            console=console,
        )

    assert "already exists" in console.file.getvalue()


def test_missing_changelog_entry_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_EMPTY, version="9.9.9")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(
            tmp_path,
            version="9.9.9",
            skip_checks=True,
            console=console,
        )

    assert "no changelog entry for 9.9.9" in console.file.getvalue()
    assert not _tag_exists(tmp_path, "v9.9.9")


def test_no_changelog_file_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, None, version="1.0.0")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(
            tmp_path,
            version="1.0.0",
            skip_checks=True,
            console=console,
        )

    assert "no changelog entry for 1.0.0" in console.file.getvalue()


def test_version_heading_present_skips_rename_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(
        rich.prompt.Confirm, "ask", _confirm_by_keyword({"Rename": False})
    )
    console = _console()

    # Rename must never be offered: version heading already exists. Push
    # will fail (no remote), which is expected and not under test here.
    with pytest.raises(typer.Exit):
        release_package(
            tmp_path,
            version="1.2.3",
            skip_checks=True,
            console=console,
        )

    assert _tag_exists(tmp_path, "v1.2.3")
    assert "Rename" not in console.file.getvalue()


def test_unreleased_rename_offered_and_accepted(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="1.0.0")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()

    with pytest.raises(typer.Exit):
        # Push fails (no remote); tag + changelog rename already happened.
        release_package(
            tmp_path,
            version="1.0.0",
            skip_checks=True,
            console=console,
        )

    text = (tmp_path / "CHANGELOG.md").read_text()
    assert has_version_entry(text, "1.0.0")
    assert unreleased_section_text(text) is None
    assert _tag_exists(tmp_path, "v1.0.0")


def test_unreleased_rename_declined_aborts(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="1.0.0")
    monkeypatch.setattr(
        rich.prompt.Confirm, "ask", _confirm_by_keyword({"Rename": False})
    )
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(
            tmp_path,
            version="1.0.0",
            skip_checks=True,
            console=console,
        )

    original = (tmp_path / "CHANGELOG.md").read_text()
    assert unreleased_section_text(original) is not None
    assert not _tag_exists(tmp_path, "v1.0.0")


def test_accept_rename_then_decline_final_confirm_leaves_tree_clean(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="1.0.0")
    before = (tmp_path / "CHANGELOG.md").read_text()
    monkeypatch.setattr(
        rich.prompt.Confirm,
        "ask",
        _confirm_by_keyword({"Rename": True, "Tag and push": False}, default=True),
    )
    console = _console()

    with pytest.raises(typer.Exit):
        release_package(
            tmp_path,
            version="1.0.0",
            skip_checks=True,
            console=console,
        )

    after = (tmp_path / "CHANGELOG.md").read_text()
    assert before == after
    assert not _tag_exists(tmp_path, "v1.0.0")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout.strip() == ""


def test_full_accept_commits_renamed_changelog_before_tagging(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="1.0.0")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))

    real_git = release_mod._git

    def fake_git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
        # Stub only the push step (no remote configured in the fixture);
        # everything else runs for real so we can inspect the resulting
        # commit/tag state.
        if args and args[0] == "push":
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=0, stdout="", stderr=""
            )
        return real_git(project_dir, *args)

    monkeypatch.setattr(release_mod, "_git", fake_git)
    console = _console()

    release_package(
        tmp_path,
        version="1.0.0",
        skip_checks=True,
        console=console,
    )

    assert _tag_exists(tmp_path, "v1.0.0")
    tagged_changelog = subprocess.run(
        ["git", "show", "v1.0.0:CHANGELOG.md"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert has_version_entry(tagged_changelog, "1.0.0")
    assert unreleased_section_text(tagged_changelog) is None
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout.strip() == ""


def test_dry_run_does_not_modify_changelog_or_create_tag(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="1.0.0")
    before = (tmp_path / "CHANGELOG.md").read_text()
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()

    release_package(
        tmp_path,
        version="1.0.0",
        skip_checks=True,
        dry_run=True,
        console=console,
    )

    after = (tmp_path / "CHANGELOG.md").read_text()
    assert before == after
    assert not _tag_exists(tmp_path, "v1.0.0")
    output = console.file.getvalue()
    assert "DRY RUN" in output
    assert "Rename" in output


def test_dry_run_with_existing_version_entry_no_rename_mentioned(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()

    release_package(
        tmp_path,
        version="1.2.3",
        skip_checks=True,
        dry_run=True,
        console=console,
    )

    assert not _tag_exists(tmp_path, "v1.2.3")
    output = console.file.getvalue()
    assert "DRY RUN" in output
    assert "Rename" not in output


def test_dry_run_is_fully_non_interactive(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="0.1.0")

    def _no_prompt(*args: object, **kwargs: object) -> bool:
        raise AssertionError("dry-run must not prompt")

    monkeypatch.setattr(rich.prompt.Confirm, "ask", _no_prompt)
    monkeypatch.setattr(rich.prompt.Prompt, "ask", _no_prompt)
    console = _console()

    release_package(
        tmp_path, version=None, skip_checks=True, dry_run=True, console=console
    )

    out = console.file.getvalue()
    assert "DRY RUN" in out
    assert "0.1.0" in out
    assert (tmp_path / "CHANGELOG.md").read_text() == UNRELEASED_NONEMPTY
    assert not _tag_exists(tmp_path, "v0.1.0")


def test_release_commit_excludes_prestaged_files(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="1.0.0")
    (tmp_path / "unrelated.txt").write_text("staged but not part of the release\n")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=tmp_path, check=True)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))

    real_git = release_mod._git

    def fake_git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "push":
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=0, stdout="", stderr=""
            )
        return real_git(project_dir, *args)

    monkeypatch.setattr(release_mod, "_git", fake_git)

    release_package(tmp_path, version="1.0.0", skip_checks=True, console=_console())

    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert committed == ["CHANGELOG.md"]
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "A  unrelated.txt" in status


def test_accepted_flow_prints_branch_push_reminder(tmp_path: Path, monkeypatch) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY, version="1.0.0")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))

    real_git = release_mod._git

    def fake_git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "push":
            return subprocess.CompletedProcess(
                args=["git", *args], returncode=0, stdout="", stderr=""
            )
        return real_git(project_dir, *args)

    monkeypatch.setattr(release_mod, "_git", fake_git)
    console = _console()

    release_package(tmp_path, version="1.0.0", skip_checks=True, console=console)

    out = console.file.getvalue()
    assert "local-only" in out
    assert "git push" in out


PRERELEASE_ONLY = """\
# Changelog

## [0.2.0rc1] - 2026-01-01

- Release candidate.
"""


def test_prerelease_heading_does_not_satisfy_final_release(
    tmp_path: Path, monkeypatch
) -> None:
    """`## [0.2.0rc1]` must not gate-pass releasing 0.2.0 (issue #14)."""
    _init_repo(tmp_path, PRERELEASE_ONLY, version="0.2.0")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()
    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="0.2.0", skip_checks=True, console=console)
    assert "no changelog entry for 0.2.0" in console.file.getvalue()
    assert not _tag_exists(tmp_path, "v0.2.0")


def test_prerelease_matches_its_own_heading_without_rename(
    tmp_path: Path, monkeypatch
) -> None:
    """Releasing 0.2.0rc1 finds its heading instead of forcing the rename."""
    _init_repo(tmp_path, PRERELEASE_ONLY, version="0.2.0rc1")
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    console = _console()
    release_package(
        tmp_path, version="0.2.0rc1", skip_checks=True, dry_run=True, console=console
    )
    output = console.file.getvalue()
    assert "Rename [Unreleased]" not in output
    assert "git tag v0.2.0rc1" in output


def test_remote_tag_aborts_before_touching_the_tree(
    tmp_path: Path, monkeypatch
) -> None:
    """An unfetched remote tag must fail early, not at push (issue #18)."""
    _init_repo(tmp_path, UNRELEASED_NONEMPTY)
    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    monkeypatch.setattr(release_mod, "_remote_tag_exists", lambda *a: True)
    console = _console()
    with pytest.raises(typer.Exit):
        release_package(tmp_path, version="1.2.3", skip_checks=True, console=console)
    assert "already exists on origin" in console.file.getvalue()
    assert "## [Unreleased]" in (tmp_path / "CHANGELOG.md").read_text()


def test_offline_remote_check_does_not_block(tmp_path: Path) -> None:
    """No origin configured: the query fails, and that is not an answer."""
    _init_repo(tmp_path, UNRELEASED_NONEMPTY)
    assert release_mod._remote_tag_exists(tmp_path, "v1.2.3") is False


def test_plugin_manifest_version_bumped_and_committed(
    tmp_path: Path, monkeypatch
) -> None:
    """plugin.json is hand-versioned and drifts behind the tags (issue #18)."""
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    manifest = tmp_path / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text('{\n  "name": "x",\n  "version": "0.2.0"\n}\n')
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "manifest"], cwd=tmp_path, check=True)

    monkeypatch.setattr(rich.prompt.Confirm, "ask", _confirm_always(True))
    monkeypatch.setattr(release_mod, "_remote_tag_exists", lambda *a: False)
    pushed: list[tuple[str, ...]] = []
    real_git = release_mod._git

    def fake_git(project_dir: Path, *args: str):
        if args[:1] == ("push",):
            pushed.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")
        return real_git(project_dir, *args)

    monkeypatch.setattr(release_mod, "_git", fake_git)
    release_package(tmp_path, version="1.2.3", skip_checks=True, console=_console())

    assert '"version": "1.2.3"' in manifest.read_text()
    # Key order and formatting survive the rewrite.
    assert manifest.read_text().startswith('{\n  "name": "x",')
    # And the bump is in the tagged commit, not left dirty.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    )
    assert status.stdout.strip() == ""
    assert pushed


def test_plugin_manifest_untouched_when_version_matches(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, HAS_TARGET_VERSION)
    manifest = tmp_path / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text('{"version": "1.2.3"}')
    assert release_mod._plugin_manifest_bump(tmp_path, "1.2.3") is None


def test_plugin_manifest_without_version_key_ignored(tmp_path: Path) -> None:
    manifest = tmp_path / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name": "x"}')
    assert release_mod._plugin_manifest_bump(tmp_path, "1.2.3") is None
