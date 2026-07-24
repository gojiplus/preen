"""Tests for the changelog release gate in `preen release`."""

import io
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import rich.prompt
import typer
from rich.console import Console

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


def _init_repo(repo: Path, changelog: str | None) -> None:
    """Init a git repo at `repo`, optionally with a CHANGELOG.md, and commit."""
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
    _init_repo(tmp_path, UNRELEASED_EMPTY)
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
    _init_repo(tmp_path, None)
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
    _init_repo(tmp_path, UNRELEASED_NONEMPTY)
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
    _init_repo(tmp_path, UNRELEASED_NONEMPTY)
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


def test_dry_run_does_not_modify_changelog_or_create_tag(
    tmp_path: Path, monkeypatch
) -> None:
    _init_repo(tmp_path, UNRELEASED_NONEMPTY)
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
