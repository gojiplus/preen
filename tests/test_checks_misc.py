"""Tests for the ci-matrix and citation checks, and answer mining."""

import os
import subprocess
from pathlib import Path

from preen.adopt import detect_package_name, mine_answers
from preen.checks.ci_matrix import CIMatrixCheck
from preen.checks.citation import CitationCheck

CANON_SHIM = """\
name: CI
on: [push]
jobs:
  ci:
    uses: gojiplus/py-canon/.github/workflows/reusable-ci.yml@v1
    with:
      wheel-import: mypkg
"""

CUSTOM_MATRIX = """\
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["{versions}"]
    steps: []
"""


def _write_ci(repo: Path, content: str) -> None:
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(content)


def _write_pyproject(repo: Path, floor: str = "3.11") -> None:
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "mypkg"\nrequires-python = ">={floor}"\n'
    )


def _stub_reusable(monkeypatch, versions: set[str] | None) -> None:
    """Answer the reusable-workflow lookup without touching the network.

    Args:
        monkeypatch: pytest fixture.
        versions: What the reusable workflow defaults to, or None for offline.
    """
    monkeypatch.setattr(CIMatrixCheck, "_reusable_default", lambda self, ref: versions)


def test_ci_matrix_shim_covering_the_floor_passes(tmp_path, monkeypatch) -> None:
    _write_pyproject(tmp_path, floor="3.12")
    _write_ci(tmp_path, CANON_SHIM)
    _stub_reusable(monkeypatch, {"3.12", "3.14"})
    result = CIMatrixCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_ci_matrix_shim_with_an_unresolvable_leg_fails(tmp_path, monkeypatch) -> None:
    """A default below the floor gives CI a job that cannot install (issue #57).

    Recognising the shim was the whole check, so preen reported green on a repo
    whose 'uv sync' exits 2 on every push.
    """
    _write_pyproject(tmp_path, floor="3.13")
    _write_ci(tmp_path, CANON_SHIM)
    _stub_reusable(monkeypatch, {"3.12", "3.14"})

    result = CIMatrixCheck(tmp_path).run()

    assert not result.passed
    assert "3.12" in result.issues[0].description
    assert "below the requires-python floor 3.13" in result.issues[0].description


def test_ci_matrix_shim_never_testing_the_floor_is_advisory(
    tmp_path, monkeypatch
) -> None:
    """CI is green; only the floor claim is unverified.

    A shim inherits its matrix from py-canon, so gating here would turn every
    repo still declaring a 3.11 floor red the day canon raised its default --
    for a change none of them made. Three of the five fleet repos checked while
    writing this were in exactly that position.
    """
    _write_pyproject(tmp_path, floor="3.11")
    _write_ci(tmp_path, CANON_SHIM)
    _stub_reusable(monkeypatch, {"3.12", "3.14"})

    result = CIMatrixCheck(tmp_path).run()

    assert result.passed
    assert result.issues[0].impact.value == "info"
    assert "never the requires-python floor 3.11" in result.issues[0].description


def test_ci_matrix_shim_honors_an_explicit_python_versions_input(
    tmp_path, monkeypatch
) -> None:
    """An explicit input overrides the default, and must be read as one."""
    _write_pyproject(tmp_path, floor="3.13")
    _write_ci(
        tmp_path,
        CANON_SHIM.replace(
            "      wheel-import: mypkg\n",
            '      python-versions: \'["3.13", "3.14"]\'\n',
        ),
    )
    _stub_reusable(monkeypatch, {"3.12", "3.14"})

    result = CIMatrixCheck(tmp_path).run()

    assert result.passed


def test_ci_matrix_offline_reports_info_rather_than_passing_silently(
    tmp_path, monkeypatch
) -> None:
    """Unverifiable is not the same as verified; it must still not gate."""
    _write_pyproject(tmp_path, floor="3.13")
    _write_ci(tmp_path, CANON_SHIM)
    _stub_reusable(monkeypatch, None)

    result = CIMatrixCheck(tmp_path).run()

    assert result.passed
    assert len(result.issues) == 1
    assert result.issues[0].impact.value == "info"
    assert "Could not read the reusable workflow" in result.issues[0].description


def test_ci_matrix_covering_floor_passes(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, floor="3.11")
    _write_ci(tmp_path, CUSTOM_MATRIX.format(versions='3.11", "3.14'))
    result = CIMatrixCheck(tmp_path).run()
    assert result.passed


def test_ci_matrix_missing_floor_fails(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, floor="3.11")
    _write_ci(tmp_path, CUSTOM_MATRIX.format(versions="3.14"))
    result = CIMatrixCheck(tmp_path).run()
    assert not result.passed
    assert any("3.11" in issue.description for issue in result.issues)


def test_ci_matrix_missing_workflow(tmp_path: Path) -> None:
    _write_pyproject(tmp_path)
    result = CIMatrixCheck(tmp_path).run()
    assert not result.passed


def test_citation_missing(tmp_path: Path) -> None:
    result = CitationCheck(tmp_path).run()
    assert not result.passed


def test_citation_valid(tmp_path: Path) -> None:
    (tmp_path / "CITATION.cff").write_text(
        'cff-version: 1.2.0\ntitle: "x"\nauthors:\n  - family-names: "Y"\n'
    )
    result = CitationCheck(tmp_path).run()
    assert result.passed


def test_citation_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "CITATION.cff").write_text("title: [unclosed\n")
    result = CitationCheck(tmp_path).run()
    assert not result.passed


def test_citation_missing_keys(tmp_path: Path) -> None:
    (tmp_path / "CITATION.cff").write_text("title: only-a-title\n")
    result = CitationCheck(tmp_path).run()
    assert not result.passed


def _write_citation(repo: Path, version: str | None) -> None:
    """Write a CFF file, optionally carrying a version key.

    Args:
        repo: Project root.
        version: Version to record, or None to omit the key.
    """
    lines = ["cff-version: 1.2.0", 'title: "x"']
    if version is not None:
        lines.append(f"version: {version}")
    lines += ["authors:", '  - family-names: "Y"']
    (repo / "CITATION.cff").write_text("\n".join(lines) + "\n")


def test_citation_version_drift_is_important(tmp_path: Path) -> None:
    """A parseable CFF can still cite a release from a decade ago (issue #50).

    get-weather-data passed this check while CITATION.cff said 0.1.31, dated
    2016, against an actual 6.1.0 -- and that number is what a citation copies.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "6.1.0"\n'
    )
    _write_citation(tmp_path, "0.1.31")

    result = CitationCheck(tmp_path).run()

    assert not result.passed
    assert "cites version 0.1.31" in result.issues[0].description
    assert result.issues[0].proposed_fix is not None


def test_citation_version_match_passes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "6.1.0"\n'
    )
    _write_citation(tmp_path, "6.1.0")

    assert CitationCheck(tmp_path).run().passed


def test_citation_without_a_version_key_is_informational(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "6.1.0"\n'
    )
    _write_citation(tmp_path, None)

    result = CitationCheck(tmp_path).run()

    assert result.passed
    assert result.issues[0].impact.value == "info"


def test_citation_fix_rewrites_only_the_version_line(tmp_path: Path) -> None:
    """A targeted substitution, so a hand-written file keeps its comments."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "2.0.0"\n'
    )
    (tmp_path / "CITATION.cff").write_text(
        "cff-version: 1.2.0\n# cite the paper, not the code\n"
        'title: "x"\nversion: 1.0.0\nauthors:\n  - family-names: "Y"\n'
    )

    issue = CitationCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    text = (tmp_path / "CITATION.cff").read_text()
    assert "version: 2.0.0" in text
    assert "# cite the paper, not the code" in text
    assert CitationCheck(tmp_path).run().passed


def test_citation_version_is_not_compared_without_a_static_project_version(
    tmp_path: Path,
) -> None:
    """A dynamic version has nothing to disagree with."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndynamic = ["version"]\n'
    )
    _write_citation(tmp_path, "0.1.31")

    assert CitationCheck(tmp_path).run().passed


def test_mine_answers(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "my-pkg"\n'
        'description = "Does a thing"\n'
        'authors = [{ name = "Alice", email = "alice@example.com" }]\n'
        "\n"
        "[project.scripts]\n"
        'my-pkg = "my_pkg.cli:main"\n'
    )
    pkg = tmp_path / "src" / "my_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")

    answers = mine_answers(tmp_path)
    assert answers["project_name"] == "my-pkg"
    assert answers["package_name"] == "my_pkg"
    assert answers["description"] == "Does a thing"
    assert answers["author_name"] == "Alice"
    assert answers["author_email"] == "alice@example.com"
    assert answers["needs_cli"] is True
    assert answers["coverage_floor"] == 0
    assert answers["default_branch"]


def test_detect_package_name_single_src_package(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "othername"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    assert detect_package_name(tmp_path, "my-pkg") == "othername"


REUSABLE_WORKFLOW = """\
name: Reusable CI
on:
  workflow_call:
    inputs:
      python-versions:
        description: 'JSON array of Python versions to test'
        type: string
        default: '["3.12", "3.14"]'
jobs:
  lint:
    runs-on: ubuntu-latest
"""


def test_reusable_default_is_read_from_a_bare_on_key(tmp_path, monkeypatch) -> None:
    """YAML 1.1 files a workflow's `on:` block under the boolean True.

    Looking it up as the string "on" finds nothing, and a lookup that finds
    nothing reads as "no default declared" -- another silent pass.
    """

    class _Response:
        def read(self):
            return REUSABLE_WORKFLOW.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "preen.checks.ci_matrix.urllib.request.urlopen",
        lambda url, timeout: _Response(),
    )

    versions = CIMatrixCheck(tmp_path)._reusable_default(
        {
            "owner": "gojiplus",
            "repo": "py-canon",
            "path": ".github/workflows/reusable-ci.yml",
            "ref": "v1",
        }
    )

    assert versions == {"3.12", "3.14"}


def _git_repo_with_tag(repo: Path, version: str, date: str) -> None:
    """Init a repo carrying a tag for `version` committed on `date`.

    Args:
        repo: Directory to initialize.
        version: Version to tag (as ``vX.Y.Z``).
        date: Commit date, as ``YYYY-MM-DD``.
    """
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": f"{date}T12:00:00",
        "GIT_COMMITTER_DATE": f"{date}T12:00:00",
    }
    for argv in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "T"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "init"],
        ["git", "tag", f"v{version}"],
    ):
        subprocess.run(argv, cwd=repo, check=True, env=env, capture_output=True)


def test_citation_fix_preserves_the_repo_s_quoting(tmp_path: Path) -> None:
    """`version: "0.6.0"` must not come back as `version: 0.9.0`.

    Found by running the fix across the fleet: two repos quote their values and
    the rewrite stripped the quotes, turning a one-line diff into a
    style change nobody asked for.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.9.0"\n'
    )
    (tmp_path / "CITATION.cff").write_text(
        'cff-version: 1.2.0\ntitle: "x"\nversion: "0.6.0"\n'
        'authors:\n  - family-names: "Y"\n'
    )

    issue = CitationCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    assert 'version: "0.9.0"' in (tmp_path / "CITATION.cff").read_text()


def test_citation_fix_moves_the_release_date_with_the_version(tmp_path: Path) -> None:
    """A right version beside a wrong date is not an improvement.

    get-weather-data would have been left claiming 6.1.0 was released on
    2016-07-17, when the tag naming it is dated 2026-07-25.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "6.1.0"\n'
    )
    (tmp_path / "CITATION.cff").write_text(
        'cff-version: 1.2.0\ntitle: "x"\nversion: 0.1.31\n'
        "date-released: 2016-07-17\n"
        'authors:\n  - family-names: "Y"\n'
    )
    _git_repo_with_tag(tmp_path, "6.1.0", "2026-07-25")

    issue = CitationCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    assert "release date to 2026-07-25" in issue.proposed_fix.description
    issue.proposed_fix.apply()

    text = (tmp_path / "CITATION.cff").read_text()
    assert "version: 6.1.0" in text
    assert "date-released: 2026-07-25" in text


def test_citation_fix_leaves_the_date_alone_without_a_tag(tmp_path: Path) -> None:
    """No tag names the version, so there is no date to be confident about.

    alsgls declares 1.2.0 and has never tagged it; inventing a date would be
    worse than leaving the old one visible.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.2.0"\n'
    )
    (tmp_path / "CITATION.cff").write_text(
        'cff-version: 1.2.0\ntitle: "x"\nversion: 0.1.0\n'
        "date-released: 2024-01-01\n"
        'authors:\n  - family-names: "Y"\n'
    )

    issue = CitationCheck(tmp_path).run().issues[0]
    assert issue.proposed_fix is not None
    issue.proposed_fix.apply()

    text = (tmp_path / "CITATION.cff").read_text()
    assert "version: 1.2.0" in text
    assert "date-released: 2024-01-01" in text


def test_a_lowercase_citation_file_is_reported(tmp_path: Path) -> None:
    """GitHub reads CITATION.cff and no other spelling.

    A macOS checkout resolves the exact name to a file called `citation.cff`,
    so an existence test alone reports a file that GitHub -- and a
    case-sensitive CI runner -- never sees. finite-sample/rmcp ships one.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n'
    )
    (tmp_path / "citation.cff").write_text(
        'cff-version: 1.2.0\ntitle: "x"\nversion: 1.0.0\n'
        'authors:\n  - family-names: "Y"\n'
    )

    result = CitationCheck(tmp_path).run()

    assert not result.passed
    assert "GitHub reads 'CITATION.cff'" in result.issues[0].description
