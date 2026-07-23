"""Tests for adopt's managed-file copy behavior."""

from pathlib import Path

import pytest

from preen.adopt import AdoptionReport, build_todos, copy_managed_files

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

    report = AdoptionReport()
    copy_managed_files(rendered, repo, "mypkg", report)

    assert ci.read_text() == "rendered ci\n"
    assert (repo / ".github" / "workflows" / "release.yml").read_text() == (
        "rendered release\n"
    )
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
