"""Tests for `preen new` and `preen update`: the copier boundary is mocked."""

import io
import subprocess
from pathlib import Path

import pytest
import typer
from rich.console import Console

from preen.commands.new import new_package
from preen.commands.update import run_update


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, no_color=True)


def test_new_package_calls_run_copy_with_data(tmp_path: Path, monkeypatch) -> None:
    calls = {}
    monkeypatch.chdir(tmp_path)

    def fake_run_copy(template, dest, data, unsafe):
        calls["template"] = template
        calls["dest"] = dest
        calls["data"] = data
        calls["unsafe"] = unsafe

    monkeypatch.setattr("copier.run_copy", fake_run_copy)
    console = _console()

    dest = new_package(
        "mypkg", org="acme", description="A thing", cli=True, console=console
    )

    assert dest == Path("mypkg")
    assert calls["dest"] == Path("mypkg")
    assert calls["data"] == {
        "project_name": "mypkg",
        "org": "acme",
        "description": "A thing",
        "needs_cli": True,
    }
    assert calls["unsafe"] is True
    output = console.file.getvalue()
    assert "Scaffolding" in output
    assert "Created mypkg/" in output


def test_new_package_omits_none_options(tmp_path: Path, monkeypatch) -> None:
    calls = {}
    monkeypatch.chdir(tmp_path)

    def fake_run_copy(template, dest, data, unsafe):
        calls["data"] = data

    monkeypatch.setattr("copier.run_copy", fake_run_copy)
    new_package("mypkg", console=_console())

    assert calls["data"] == {"project_name": "mypkg"}


def test_update_no_copier_answers_exits(tmp_path: Path) -> None:
    console = _console()
    with pytest.raises(typer.Exit):
        run_update(tmp_path, console=console)
    assert "not adopted" in console.file.getvalue()


def test_update_runs_copier_update_and_reports_no_changes(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".copier-answers.yml").write_text("_src_path: gh:x/y\n")
    calls = {}

    def fake_run_update(repo, **kwargs):
        calls["repo"] = repo
        calls["kwargs"] = kwargs

    monkeypatch.setattr("copier.run_update", fake_run_update)

    def fake_subprocess_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("preen.commands.update.subprocess.run", fake_subprocess_run)
    console = _console()

    run_update(tmp_path, console=console)

    assert calls["repo"] == tmp_path
    assert calls["kwargs"] == {
        "defaults": True,
        "overwrite": True,
        "conflict": "inline",
        "unsafe": True,
    }
    output = console.file.getvalue()
    assert "Already up to date" in output


def test_update_reports_changed_files(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".copier-answers.yml").write_text("_src_path: gh:x/y\n")
    monkeypatch.setattr("copier.run_update", lambda repo, **kwargs: None)

    def fake_subprocess_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout=" M pyproject.toml\n", stderr=""
        )

    monkeypatch.setattr("preen.commands.update.subprocess.run", fake_subprocess_run)
    console = _console()

    run_update(tmp_path, console=console)

    output = console.file.getvalue()
    assert "Changed files" in output
    assert "pyproject.toml" in output
    assert "conflict markers" in output


def test_update_not_a_git_repo_warns(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".copier-answers.yml").write_text("_src_path: gh:x/y\n")
    monkeypatch.setattr("copier.run_update", lambda repo, **kwargs: None)

    def fake_subprocess_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=128, stdout="", stderr="")

    monkeypatch.setattr("preen.commands.update.subprocess.run", fake_subprocess_run)
    console = _console()

    run_update(tmp_path, console=console)

    assert "Not a git repo" in console.file.getvalue()
