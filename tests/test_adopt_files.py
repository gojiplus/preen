"""Tests for adopt's managed-file copy behavior."""

from pathlib import Path

import pytest

from preen.adopt import (
    AdoptionReport,
    _preserve_shim_inputs,
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
    merged, preserved = _preserve_shim_inputs(
        CANON_SHIM, RENDERED_SHIM, "reusable-ci.yml"
    )
    assert "coverage-floor: 70" in merged
    assert """python-versions: '["3.12", "3.14"]'""" in merged
    assert any("coverage-floor" in p for p in preserved)
    assert any("python-versions" in p for p in preserved)
    # Everything the template owns is still the template's.
    assert "uses: gojiplus/py-canon" in merged
    assert merged.startswith("name: CI\n")


def test_ci_inputs_unchanged_when_shim_already_matches() -> None:
    merged, preserved = _preserve_shim_inputs(CANON_SHIM, CANON_SHIM, "reusable-ci.yml")
    assert merged == CANON_SHIM
    assert preserved == []


def test_ci_inputs_left_alone_for_hand_rolled_workflow() -> None:
    """A repo's own CI workflow is not a shim; don't mine inputs from it."""
    hand_rolled = "name: CI\non: push\njobs:\n  test:\n    with:\n      foo: bar\n"
    merged, preserved = _preserve_shim_inputs(
        hand_rolled, RENDERED_SHIM, "reusable-ci.yml"
    )
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


def test_pin_answers_commit_rewrites_moving_tag(tmp_path: Path) -> None:
    """git describe can record `v1`; the pin forces the concrete release tag."""
    from preen.adopt import _pin_answers_commit

    answers = tmp_path / ".copier-answers.yml"
    answers.write_text(
        "# Managed by copier\n_commit: v1\n_src_path: gh:gojiplus/py-canon\n"
    )
    _pin_answers_commit(tmp_path, "v1.0.1")
    assert "_commit: v1.0.1\n" in answers.read_text()
    assert "_src_path: gh:gojiplus/py-canon" in answers.read_text()


def test_pin_answers_commit_tolerates_missing_file(tmp_path: Path) -> None:
    from preen.adopt import _pin_answers_commit

    _pin_answers_commit(tmp_path, "v1.0.1")


CANON_DOCS_SHIM = """\
name: Docs
on:
  push:
    branches: [main]
jobs:
  docs:
    uses: gojiplus/py-canon/.github/workflows/reusable-docs.yml@v1
    with:
      deploy: true
      docs-dir: docs/source
      run-doctests: false
"""

RENDERED_DOCS_SHIM = """\
name: Docs
on:
  push:
    branches: [main]
jobs:
  docs:
    uses: gojiplus/py-canon/.github/workflows/reusable-docs.yml@v1
    with:
      deploy: true
"""

CUSTOM_CONF = """\
\"\"\"Sphinx configuration.\"\"\"

from pycanon_docs import *  # noqa: F403

project = "sharepack"

# Build the three live demos linked from docs/index.md.
html_extra_path = ["_demos"]
"""


def _write(path: Path, text: str) -> None:
    """Write a file, creating parents.

    Args:
        path: Destination.
        text: Contents.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_docs_shim_inputs_survive_the_overwrite(rendered: Path, repo: Path) -> None:
    """Input preservation covered ci.yml alone (issue #51).

    docs.yml, release.yml and dependabot-auto-merge.yml fell through to a blind
    copy, so `docs-dir: docs/source` and `run-doctests: false` were deleted on
    every adopt and the repo's docs build broke.
    """
    _write(repo / ".github" / "workflows" / "docs.yml", CANON_DOCS_SHIM)
    _write(rendered / ".github" / "workflows" / "docs.yml", RENDERED_DOCS_SHIM)
    report = AdoptionReport()

    copy_managed_files(rendered, repo, "mypkg", report)

    merged = (repo / ".github" / "workflows" / "docs.yml").read_text()
    assert "docs-dir: docs/source" in merged
    assert "run-doctests: false" in merged
    assert "uses: gojiplus/py-canon" in merged
    assert any("docs-dir" in entry for entry in report.preserved)


def test_conf_py_follows_a_declared_docs_dir(rendered: Path, repo: Path) -> None:
    """The shim says where the docs live; assuming docs/ wrote a second config."""
    _write(repo / ".github" / "workflows" / "docs.yml", CANON_DOCS_SHIM)
    _write(repo / "docs" / "source" / "conf.py", CUSTOM_CONF)
    report = AdoptionReport()

    copy_managed_files(rendered, repo, "mypkg", report)

    assert (repo / "docs" / "source" / "conf.py").read_text() == "rendered conf\n"
    assert (repo / "docs" / "source" / "conf.py.bak").read_text() == CUSTOM_CONF
    assert not (repo / "docs" / "conf.py").exists()


def test_conf_py_is_found_under_docs_without_a_shim(rendered: Path, repo: Path) -> None:
    """No docs.yml to ask, so look for the conf.py the repo actually has."""
    _write(repo / "docs" / "source" / "conf.py", CUSTOM_CONF)
    report = AdoptionReport()

    copy_managed_files(rendered, repo, "mypkg", report)

    assert (repo / "docs" / "source" / "conf.py").read_text() == "rendered conf\n"
    assert not (repo / "docs" / "conf.py").exists()


def test_overwriting_a_customized_conf_py_raises_a_todo(
    rendered: Path, repo: Path
) -> None:
    """A .bak on disk is not a report (issue #48).

    sharepack's adoption overwrote a conf.py that built the three live demos
    linked from docs/index.md, and the report line was indistinguishable from a
    routine write. An unattended adopt would have shipped broken docs.
    """
    _write(repo / "docs" / "conf.py", CUSTOM_CONF)
    report = AdoptionReport()

    copy_managed_files(rendered, repo, "mypkg", report)

    assert report.todos, "an overwritten custom conf.py must reach Manual TODOs"
    todo = report.todos[-1]
    assert "docs/conf.py" in todo
    assert "docs/conf.py.bak" in todo


def test_replacing_an_unchanged_canon_conf_py_raises_no_todo(
    rendered: Path, repo: Path
) -> None:
    """Only work the template would destroy is worth a human's attention."""
    _write(repo / "docs" / "conf.py", "rendered conf\n")
    report = AdoptionReport()

    copy_managed_files(rendered, repo, "mypkg", report)

    assert report.todos == []


def test_a_fresh_conf_py_raises_no_todo(rendered: Path, repo: Path) -> None:
    report = AdoptionReport()

    copy_managed_files(rendered, repo, "mypkg", report)

    assert (repo / "docs" / "conf.py").read_text() == "rendered conf\n"
    assert report.todos == []


def test_adopt_and_the_workflows_check_agree_on_canon_workflows() -> None:
    """Two copies of the same map; a divergence silently drops preservation."""
    from preen import adopt
    from preen.checks import workflows

    assert adopt.CANON_WORKFLOWS == workflows.CANON_WORKFLOWS


def test_copy_time_todos_survive_build_todos(tmp_path: Path, monkeypatch) -> None:
    """`report.todos = build_todos(...)` discarded whatever the copy raised.

    build_todos runs after copy_managed_files and takes only (repo,
    package_name), so it has no view of what the copy did — an overwritten
    conf.py TODO would have been assigned away before anyone saw it.
    """
    from preen import adopt as adopt_mod

    def fake_copy(rendered, repo, package_name, report):
        report.todos.append("docs/conf.py had 5 line(s) the template does not")

    monkeypatch.setattr(adopt_mod, "copy_managed_files", fake_copy)
    monkeypatch.setattr(adopt_mod, "render_template", lambda *a, **k: None)
    monkeypatch.setattr(adopt_mod, "_pin_answers_commit", lambda *a, **k: None)
    monkeypatch.setattr(adopt_mod, "mine_answers", lambda repo: {"package_name": "x"})
    monkeypatch.setattr(adopt_mod, "rewrite_pyproject", lambda *a, **k: ([], []))
    monkeypatch.setattr(adopt_mod, "build_todos", lambda repo, name: ["something else"])
    monkeypatch.setattr("preen.checks.template.latest_canon_tag", lambda **k: "v1.2.0")

    report = adopt_mod.adopt_repo(tmp_path)

    assert "docs/conf.py had 5 line(s) the template does not" in report.todos
    assert "something else" in report.todos


def test_an_overwritten_workflow_is_backed_up_and_flagged(
    rendered: Path, repo: Path
) -> None:
    """Input preservation covers `with:`; the rest of the file is overwritten.

    piedomains' docs.yml carried a `cancel-in-progress` guard with a comment
    explaining it must never cancel a main-branch build midway through a Pages
    deploy. The overwrite replaced it with a bare `true`, reintroducing exactly
    the cancelled deploys the comment was added to stop, and nothing said so.
    """
    _write(
        repo / ".github" / "workflows" / "docs.yml",
        "name: Docs\nconcurrency:\n"
        "  # never cancel a Pages deploy midway\n"
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n"
        "jobs:\n  docs:\n"
        "    uses: gojiplus/py-canon/.github/workflows/reusable-docs.yml@v1\n",
    )
    _write(
        rendered / ".github" / "workflows" / "docs.yml",
        "name: Docs\nconcurrency:\n  cancel-in-progress: true\njobs:\n  docs:\n"
        "    uses: gojiplus/py-canon/.github/workflows/reusable-docs.yml@v1\n",
    )
    report = AdoptionReport()

    copy_managed_files(rendered, repo, "mypkg", report)

    backup = repo / ".github" / "workflows" / "docs.yml.bak"
    assert backup.exists()
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in (
        backup.read_text()
    )
    assert any("docs.yml differed from the template" in t for t in report.todos)


def test_an_unchanged_workflow_raises_no_todo(rendered: Path, repo: Path) -> None:
    """Only a file the overwrite actually changes is worth a human's attention."""
    shim = (
        "name: Docs\njobs:\n  docs:\n"
        "    uses: gojiplus/py-canon/.github/workflows/reusable-docs.yml@v1\n"
    )
    _write(repo / ".github" / "workflows" / "docs.yml", shim)
    _write(rendered / ".github" / "workflows" / "docs.yml", shim)
    report = AdoptionReport()

    copy_managed_files(rendered, repo, "mypkg", report)

    assert report.todos == []
    assert not (repo / ".github" / "workflows" / "docs.yml.bak").exists()


def test_comments_count_toward_what_an_overwrite_destroys() -> None:
    """The comment is often the only record of why a setting is what it is.

    Counting code lines alone reported "2 lines" for piedomains' fifteen-line
    conf.py block, whose value was mostly the reasoning.
    """
    from preen.adopt import _custom_conf_lines

    template = '"""Config."""\n\nfrom py_canon.sphinx import configure\n'
    existing = template + (
        "\n# Without this, napoleon emits duplicate objects and CI builds\n"
        "# docs with -W, so the build fails.\nnapoleon_use_ivar = True\n"
    )

    assert _custom_conf_lines(existing, template) == 3
