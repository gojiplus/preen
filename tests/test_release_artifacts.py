"""Tests for the build/artifact gate and the version-bearing-file bumps."""

import subprocess
from pathlib import Path

import preen.commands.release as release_mod
from preen.commands.release import (
    VERSION_WRITERS,
    _artifact_error,
    _citation_bump,
    _version_bumps,
)

PYPROJECT = """\
[project]
name = "demo"
version = "1.0.0"
description = "A demo"
readme = "README.md"

[build-system]
requires = ["uv_build>=0.12.5,<0.13"]
build-backend = "uv_build"
"""


def _package(repo: Path) -> None:
    """Write a minimal, genuinely buildable src-layout package.

    Args:
        repo: Project root.
    """
    (repo / "pyproject.toml").write_text(PYPROJECT)
    (repo / "README.md").write_text("# demo\n")
    package = repo / "src" / "demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Demo."""\n')


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    """Build a CompletedProcess stand-in.

    Args:
        returncode: Exit status.
        stdout: Captured stdout.
        stderr: Captured stderr.

    Returns:
        The completed process.
    """
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_a_publishable_package_passes_the_gate(tmp_path: Path) -> None:
    """Runs the real uv build and the real twine, because that is the gate.

    A stubbed version would only prove the plumbing calls something.
    """
    _package(tmp_path)

    assert _artifact_error(tmp_path) is None


def test_uv_writes_a_gitignore_that_must_not_reach_twine(tmp_path: Path) -> None:
    """`uv build --out-dir` drops a .gitignore beside the artifacts.

    Passing every file in that directory to twine made it reject the whole
    invocation with "Unknown distribution format: '.gitignore'" -- a gate that
    fails on every repo is not a gate.
    """
    _package(tmp_path)
    seen: list[list[str]] = []
    real = release_mod._run_tool

    def recording(argv: list[str], project_dir: Path):
        seen.append(argv)
        return real(argv, project_dir)

    release_mod._run_tool = recording
    try:
        assert _artifact_error(tmp_path) is None
    finally:
        release_mod._run_tool = real

    twine = next(argv for argv in seen if "twine" in argv)
    assert all(not arg.endswith(".gitignore") for arg in twine)
    assert any(arg.endswith(".whl") for arg in twine)
    assert any(arg.endswith(".tar.gz") for arg in twine)


def test_a_failing_build_is_reported(tmp_path: Path, monkeypatch) -> None:
    _package(tmp_path)
    monkeypatch.setattr(
        release_mod,
        "_run_tool",
        lambda argv, project_dir: _completed(1, stderr="no build backend"),
    )

    error = _artifact_error(tmp_path)

    assert error is not None
    assert "uv build failed" in error


def test_twine_rejecting_the_artifacts_is_reported(tmp_path: Path, monkeypatch) -> None:
    _package(tmp_path)
    real = release_mod._run_tool

    def selective(argv: list[str], project_dir: Path):
        if "twine" in argv:
            return _completed(1, stdout="ERROR InvalidDistribution")
        return real(argv, project_dir)

    monkeypatch.setattr(release_mod, "_run_tool", selective)

    error = _artifact_error(tmp_path)

    assert error is not None
    assert "twine check rejected" in error


def test_a_tool_that_cannot_be_fetched_does_not_block(
    tmp_path: Path, monkeypatch
) -> None:
    """No network is not the repo's fault; a failing check is.

    Same rule the remote-tag query already follows: an unanswerable question
    does not gate a release.
    """
    _package(tmp_path)
    monkeypatch.setattr(release_mod, "_run_tool", lambda argv, project_dir: None)

    assert _artifact_error(tmp_path) is None


def test_run_tool_returns_none_when_the_binary_is_absent(tmp_path: Path) -> None:
    assert release_mod._run_tool(["definitely-not-a-real-binary"], tmp_path) is None


def test_citation_version_drift_is_offered_as_a_bump(tmp_path: Path) -> None:
    """Whoever cites the package copies this number.

    A stale one outlives the release in someone else's bibliography, so the
    release flow offers it alongside the plugin manifest (issue #50).
    """
    (tmp_path / "CITATION.cff").write_text(
        'cff-version: 1.2.0\ntitle: "demo"\nversion: "0.9.0"\n'
    )

    bump = _citation_bump(tmp_path, "1.0.0")

    assert bump is not None
    assert bump.rel == "CITATION.cff"
    assert bump.current == "0.9.0"


def test_citation_already_at_the_released_version_is_not_offered(
    tmp_path: Path,
) -> None:
    (tmp_path / "CITATION.cff").write_text('cff-version: 1.2.0\nversion: "1.0.0"\n')

    assert _citation_bump(tmp_path, "1.0.0") is None


def test_citation_without_a_version_key_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "CITATION.cff").write_text('cff-version: 1.2.0\ntitle: "demo"\n')

    assert _citation_bump(tmp_path, "1.0.0") is None


def test_citation_write_keeps_the_rest_of_the_file(tmp_path: Path) -> None:
    citation = tmp_path / "CITATION.cff"
    citation.write_text(
        "cff-version: 1.2.0\n# cite the paper, not the code\n"
        'title: "demo"\nversion: 0.9.0\nauthors:\n  - family-names: "Y"\n'
    )

    VERSION_WRITERS["CITATION.cff"](citation, "1.0.0")

    text = citation.read_text()
    assert 'version: "1.0.0"' in text
    assert "# cite the paper, not the code" in text
    assert 'family-names: "Y"' in text


def test_both_version_bearing_files_are_collected(tmp_path: Path) -> None:
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        '{\n  "name": "demo",\n  "version": "0.9.0"\n}\n'
    )
    (tmp_path / "CITATION.cff").write_text('cff-version: 1.2.0\nversion: "0.9.0"\n')

    bumps = _version_bumps(tmp_path, "1.0.0")

    assert [bump.rel for bump in bumps] == [
        ".claude-plugin/plugin.json",
        "CITATION.cff",
    ]
    assert {bump.rel for bump in bumps} <= set(VERSION_WRITERS)
