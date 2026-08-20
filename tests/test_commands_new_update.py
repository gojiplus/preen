"""Tests for `preen new` and `preen update`: the copier boundary is mocked."""

import io
import subprocess
from pathlib import Path

import pytest
import typer
from rich.console import Console

from preen.commands.new import new_package
from preen.commands.update import (
    conflict_hunks,
    has_conflict_markers,
    project_metadata_at_risk,
    run_update,
    split_conflict_sides,
)


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


def test_update_not_a_git_repo_warns(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".copier-answers.yml").write_text("_src_path: gh:x/y\n")
    monkeypatch.setattr("copier.run_update", lambda repo, **kwargs: None)

    def fake_subprocess_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=128, stdout="", stderr="")

    monkeypatch.setattr("preen.commands.update.subprocess.run", fake_subprocess_run)
    console = _console()

    run_update(tmp_path, console=console)

    assert "Not a git repo" in console.file.getvalue()


# The shape copier produced on gojiplus/lost-years when py-canon v1.2.0
# changed two lines: the whole diverged `[project]` block became one conflict,
# and its "after updating" side was the day-one scaffold.
CONFLICTED_PYPROJECT = """\
[project]
name = "lost_years"
<<<<<<< before updating
authors = [
    { name = "Suriyan Laohaprapanon", email = "suriyant@gmail.com" },
    { name = "Gaurav Sood", email = "gsood07@gmail.com" },
]
requires-python = ">=3.12"
version = "0.8.0"
dependencies = ["pandas", "pyarrow>=15"]
=======
authors = [{ name = "Suriyan Laohaprapanon", email = "suriyant@gmail.com" }]
requires-python = ">=3.12"
version = "0.1.0"
dependencies = []
>>>>>>> after updating

[tool.ruff]
target-version = "py312"
"""


def _repo_with_conflict(tmp_path: Path, monkeypatch, text: str) -> Console:
    (tmp_path / ".copier-answers.yml").write_text("_src_path: gh:x/y\n")
    (tmp_path / "pyproject.toml").write_text(text)
    monkeypatch.setattr("copier.run_update", lambda repo, **kwargs: None)
    monkeypatch.setattr(
        "preen.commands.update.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, returncode=0, stdout="UU pyproject.toml\n", stderr=""
        ),
    )
    return _console()


def test_split_conflict_sides_recovers_both_files() -> None:
    ours, theirs = split_conflict_sides(CONFLICTED_PYPROJECT)

    assert 'version = "0.8.0"' in ours
    assert 'version = "0.1.0"' not in ours
    assert 'version = "0.1.0"' in theirs
    assert 'version = "0.8.0"' not in theirs
    # Text outside the conflict belongs to both sides.
    for side in (ours, theirs):
        assert 'name = "lost_years"' in side
        assert 'target-version = "py312"' in side
        assert not has_conflict_markers(side)


def test_split_conflict_sides_ignores_a_bare_separator_line() -> None:
    text = "Heading\n=======\n\nbody\n"

    ours, theirs = split_conflict_sides(text)

    assert ours == theirs == text


def test_project_metadata_at_risk_names_version_and_dependencies() -> None:
    at_risk = {
        key: (current, offered)
        for key, current, offered in project_metadata_at_risk(CONFLICTED_PYPROJECT)
    }

    assert at_risk["version"] == ("0.8.0", "0.1.0")
    assert at_risk["dependencies"] == (["pandas", "pyarrow>=15"], [])
    assert len(at_risk["authors"][0]) == 2
    assert len(at_risk["authors"][1]) == 1
    # requires-python is identical on both sides, so it is not at risk.
    assert "requires-python" not in at_risk


def test_project_metadata_at_risk_empty_when_unparsable() -> None:
    assert project_metadata_at_risk("<<<<<<< a\nnot: toml: at: all\n") == []


def test_update_exits_nonzero_and_names_what_the_merge_would_replace(
    tmp_path: Path, monkeypatch
) -> None:
    console = _repo_with_conflict(tmp_path, monkeypatch, CONFLICTED_PYPROJECT)

    with pytest.raises(typer.Exit) as exc:
        run_update(tmp_path, console=console)

    assert exc.value.exit_code == 1
    output = console.file.getvalue()
    assert "Unresolved conflicts" in output
    assert "0.8.0" in output
    assert "0.1.0" in output
    assert "per-project facts" in output


def test_update_exits_on_conflicts_without_project_changes(
    tmp_path: Path, monkeypatch
) -> None:
    unchanged = (
        '[project]\nversion = "0.8.0"\n'
        "<<<<<<< before updating\n[tool.ruff]\nline-length = 88\n"
        "=======\n[tool.ruff]\nline-length = 100\n>>>>>>> after updating\n"
    )
    console = _repo_with_conflict(tmp_path, monkeypatch, unchanged)

    with pytest.raises(typer.Exit) as exc:
        run_update(tmp_path, console=console)

    assert exc.value.exit_code == 1
    output = console.file.getvalue()
    assert "Unresolved conflicts" in output
    assert "per-project facts" not in output


# The real conflict copier produced, reduced. `version` sits ABOVE the hunk,
# so the template's side reintroduces it: the reconstructed "after" file has
# two `version` keys and does not parse as TOML at all. Reading each side of
# the hunk against its enclosing table is what makes the report possible.
REAL_CONFLICT = """\
[build-system]
requires = ["uv_build>=0.12.5,<0.13"]

[project]
name = "lost_years"
version = "0.8.0"
readme = "README.md"
<<<<<<< before updating
authors = [
    { name = "Suriyan Laohaprapanon", email = "suriyant@gmail.com" },
    { name = "Gaurav Sood", email = "gsood07@gmail.com" },
]
requires-python = ">=3.12"
dependencies = [
    # pandas.read_html needs a parser backend.
    "lxml>=5",
    "pandas",
]
=======
authors = [{ name = "Suriyan Laohaprapanon", email = "suriyant@gmail.com" }]
requires-python = ">=3.12"
version = "0.1.0"
>>>>>>> after updating
classifiers = ["Intended Audience :: Developers"]

[tool.ruff]
line-length = 88
"""


def test_whole_file_reconstruction_of_the_real_conflict_is_invalid_toml() -> None:
    import tomllib

    _, theirs = split_conflict_sides(REAL_CONFLICT)

    # Two `version` keys: the one above the conflict and the one inside it.
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads(theirs)


def test_project_metadata_at_risk_reads_version_from_outside_the_hunk() -> None:
    at_risk = {
        key: (current, offered)
        for key, current, offered in project_metadata_at_risk(REAL_CONFLICT)
    }

    # The hunk's own "before" side carries no version; the file does.
    assert at_risk["version"] == ("0.8.0", "0.1.0")
    assert at_risk["dependencies"] == (["lxml>=5", "pandas"], None)
    assert "requires-python" not in at_risk
    # Untouched keys outside the hunk are not reported.
    assert "name" not in at_risk
    assert "classifiers" not in at_risk


def test_conflict_hunks_tags_each_hunk_with_its_table() -> None:
    hunks = conflict_hunks(REAL_CONFLICT)

    assert len(hunks) == 1
    table, ours_lines, theirs_lines = hunks[0]
    assert table == "[project]"
    assert any("Gaurav Sood" in line for line in ours_lines)
    assert any('version = "0.1.0"' in line for line in theirs_lines)


def test_report_names_the_project_table_despite_rich_markup(
    tmp_path: Path, monkeypatch
) -> None:
    console = _repo_with_conflict(tmp_path, monkeypatch, REAL_CONFLICT)

    with pytest.raises(typer.Exit):
        run_update(tmp_path, console=console)

    # Rich reads a bare [project] as a style tag and would swallow it.
    assert "[project] metadata" in console.file.getvalue()
