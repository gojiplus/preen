"""Tests for adopt's managed-file copy behavior."""

from pathlib import Path

import pytest

from preen.adopt import (
    AdoptionReport,
    _preserve_ci_inputs,
    build_todos,
    copy_managed_files,
    mine_answers,
)

RENDERED_FILES = {
    ".github/workflows/ci.yml": "rendered ci\n",
    ".github/workflows/docs.yml": "rendered docs\n",
    ".github/workflows/release.yml": "rendered release\n",
    ".github/workflows/dependabot-auto-merge.yml": "rendered automerge\n",
    ".github/dependabot.yml": "rendered dependabot\n",
    ".pre-commit-config.yaml": "rendered precommit\n",
    ".copier-answers.yml": "_commit: v1.2.0\n",
    "docs/conf.py": "rendered conf\n",
    "LICENSE": "rendered license\n",
    "CITATION.cff": "rendered citation\n",
}


@pytest.fixture
def rendered(tmp_path: Path) -> Path:
    root = tmp_path / "rendered"
    for rel, content in RENDERED_FILES.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    pkg = root / "src" / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    return root


def test_workflows_always_overwritten(rendered: Path, repo: Path) -> None:
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.parent.mkdir(parents=True)
    ci.write_text("old ci\n")
    automerge = repo / ".github" / "workflows" / "dependabot-auto-merge.yml"
    automerge.write_text("old automerge\n")

    report = AdoptionReport()
    copy_managed_files(rendered, repo, "mypkg", report)

    assert ci.read_text() == "rendered ci\n"
    assert (repo / ".github" / "workflows" / "release.yml").read_text() == (
        "rendered release\n"
    )
    # A stale auto-merge workflow must be replaced, not skipped: leaving it
    # copy-if-absent stranded a broken version in every already-adopted repo.
    assert automerge.read_text() == "rendered automerge\n"
    assert (repo / ".copier-answers.yml").exists()
    assert ".github/workflows/ci.yml" in report.written


def test_if_absent_files_not_clobbered(rendered: Path, repo: Path) -> None:
    (repo / "LICENSE").write_text("my own license\n")
    (repo / ".pre-commit-config.yaml").write_text("my hooks\n")

    report = AdoptionReport()
    copy_managed_files(rendered, repo, "mypkg", report)

    assert (repo / "LICENSE").read_text() == "my own license\n"
    assert (repo / ".pre-commit-config.yaml").read_text() == "my hooks\n"
    assert "LICENSE (exists)" in report.skipped
    assert ".pre-commit-config.yaml (exists)" in report.skipped
    # Absent ones were created.
    assert (repo / "CITATION.cff").read_text() == "rendered citation\n"
    assert (repo / ".github" / "dependabot.yml").exists()


def test_docs_conf_backed_up(rendered: Path, repo: Path) -> None:
    conf = repo / "docs" / "conf.py"
    conf.parent.mkdir(parents=True)
    conf.write_text("old conf\n")

    report = AdoptionReport()
    copy_managed_files(rendered, repo, "mypkg", report)

    assert conf.read_text() == "rendered conf\n"
    assert (repo / "docs" / "conf.py.bak").read_text() == "old conf\n"


def test_py_typed_src_layout(rendered: Path, repo: Path) -> None:
    report = AdoptionReport()
    copy_managed_files(rendered, repo, "mypkg", report)
    assert (repo / "src" / "mypkg" / "py.typed").exists()


def test_py_typed_flat_layout(rendered: Path, tmp_path: Path) -> None:
    repo = tmp_path / "flat"
    (repo / "flatpkg").mkdir(parents=True)
    ((repo / "flatpkg") / "__init__.py").write_text("")

    report = AdoptionReport()
    copy_managed_files(rendered, repo, "flatpkg", report)
    assert (repo / "flatpkg" / "py.typed").exists()


def test_todos_flag_stale_workflows_and_missing_lock(repo: Path) -> None:
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("x")
    (workflows / "python-publish.yml").write_text("x")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "mypkg"\nrequires-python = ">=3.9"\n'
    )

    todos = build_todos(repo, "mypkg")
    joined = "\n".join(todos)
    assert "python-publish.yml" in joined
    assert "uv.lock" in joined
    assert "3.9" in joined


def test_todos_flag_flat_layout(tmp_path: Path) -> None:
    repo = tmp_path / "flat"
    (repo / "flatpkg").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "flatpkg"\n')
    todos = build_todos(repo, "flatpkg")
    assert any("src/" in t for t in todos)


CANON_SHIM = """\
name: CI

on:
  push:
    branches: [main]

jobs:
  ci:
    uses: gojiplus/py-canon/.github/workflows/reusable-ci.yml@v1
    with:
      wheel-import: mypkg
      coverage-floor: 70
      python-versions: '["3.12", "3.14"]'
"""

RENDERED_SHIM = """\
name: CI

on:
  push:
    branches: [main]

jobs:
  ci:
    uses: gojiplus/py-canon/.github/workflows/reusable-ci.yml@v1
    with:
      wheel-import: mypkg
      coverage-floor: 0
"""


def test_ci_inputs_preserved_across_overwrite() -> None:
    """The shim's repo-specific `with:` inputs survive adoption (issue #13)."""
    merged, preserved = _preserve_ci_inputs(CANON_SHIM, RENDERED_SHIM)
    assert "coverage-floor: 70" in merged
    assert """python-versions: '["3.12", "3.14"]'""" in merged
    assert any("coverage-floor" in p for p in preserved)
    assert any("python-versions" in p for p in preserved)
    # Everything the template owns is still the template's.
    assert "uses: gojiplus/py-canon" in merged
    assert merged.startswith("name: CI\n")


def test_ci_inputs_unchanged_when_shim_already_matches() -> None:
    merged, preserved = _preserve_ci_inputs(CANON_SHIM, CANON_SHIM)
    assert merged == CANON_SHIM
    assert preserved == []


def test_ci_inputs_left_alone_for_hand_rolled_workflow() -> None:
    """A repo's own CI workflow is not a shim; don't mine inputs from it."""
    hand_rolled = "name: CI\non: push\njobs:\n  test:\n    with:\n      foo: bar\n"
    merged, preserved = _preserve_ci_inputs(hand_rolled, RENDERED_SHIM)
    assert merged == RENDERED_SHIM
    assert preserved == []


def test_ci_workflow_copy_preserves_inputs(rendered: Path, repo: Path) -> None:
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.parent.mkdir(parents=True)
    ci.write_text(CANON_SHIM)
    (rendered / ".github" / "workflows" / "ci.yml").write_text(RENDERED_SHIM)

    report = AdoptionReport()
    copy_managed_files(rendered, repo, "mypkg", report)

    assert "coverage-floor: 70" in ci.read_text()
    assert any("ci.yml" in p for p in report.preserved)


def test_coverage_floor_mined_from_existing_shim(tmp_path: Path) -> None:
    """Else the 0 default is persisted to .copier-answers and re-clobbers."""
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text(CANON_SHIM)
    (repo / "pyproject.toml").write_text('[project]\nname = "mypkg"\n')
    assert mine_answers(repo)["coverage_floor"] == 70


def test_coverage_floor_defaults_to_zero_without_shim(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "mypkg"\n')
    assert mine_answers(repo)["coverage_floor"] == 0
