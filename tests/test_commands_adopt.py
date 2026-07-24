"""Tests for the `preen adopt` CLI wrapper (report rendering + error path).

`adopt_repo` itself (the core adoption logic) is covered by
test_adopt_files.py / test_adopt_pyproject.py; this covers only the thin
commands/adopt.py wrapper that prints the AdoptionReport.
"""

import io

import pytest
import typer
from rich.console import Console

from preen.adopt import AdoptionReport
from preen.commands.adopt import run_adopt


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, no_color=True)


def test_missing_pyproject_exits_with_message(tmp_path, monkeypatch) -> None:
    def fake_adopt_repo(repo, release_migration=False):
        raise FileNotFoundError("no pyproject.toml found")

    monkeypatch.setattr("preen.commands.adopt.adopt_repo", fake_adopt_repo)
    console = _console()

    with pytest.raises(typer.Exit):
        run_adopt(tmp_path, console=console)

    assert "no pyproject.toml found" in console.file.getvalue()


def test_full_report_rendered(tmp_path, monkeypatch) -> None:
    report = AdoptionReport(
        written=["pyproject.toml", ".pre-commit-config.yaml"],
        skipped=["README.md (already exists)"],
        pyproject_changes=["[tool.ruff] replaced"],
        todos=["Set up trusted publishing on PyPI"],
    )

    def fake_adopt_repo(repo, release_migration=False):
        return report

    monkeypatch.setattr("preen.commands.adopt.adopt_repo", fake_adopt_repo)
    console = _console()

    result = run_adopt(tmp_path, console=console)

    assert result is report
    output = console.file.getvalue()
    assert "ADOPTION REPORT" in output
    assert "pyproject.toml" in output
    assert "README.md (already exists)" in output
    assert "[tool.ruff] replaced" in output
    assert "Set up trusted publishing on PyPI" in output
    assert "Manual TODOs" in output


def test_empty_report_shows_nothing_placeholders(tmp_path, monkeypatch) -> None:
    report = AdoptionReport()
    monkeypatch.setattr(
        "preen.commands.adopt.adopt_repo", lambda repo, release_migration=False: report
    )
    console = _console()

    run_adopt(tmp_path, console=console)

    output = console.file.getvalue()
    assert output.count("(nothing)") == 2
    assert "Manual TODOs" not in output


def test_release_migration_flag_forwarded(tmp_path, monkeypatch) -> None:
    calls = {}

    def fake_adopt_repo(repo, release_migration=False):
        calls["release_migration"] = release_migration
        return AdoptionReport()

    monkeypatch.setattr("preen.commands.adopt.adopt_repo", fake_adopt_repo)
    run_adopt(tmp_path, release_migration=True, console=_console())

    assert calls["release_migration"] is True
