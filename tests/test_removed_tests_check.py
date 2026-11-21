"""Tests for the removed-tests check.

``test_reproduces_the_commit_this_check_was_written_for`` is a reduction of a
real change: moving URL fetching onto another library deleted three tests of
properties the new code was still meant to have.
"""

import subprocess
from pathlib import Path

import pytest

from preen.checks.removed_tests import (
    RemovedTestsCheck,
    _matches,
    inventory,
    removed,
)

BEFORE = """
import pytest


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/x.pdf", "http://[::1]/x.pdf", "ftp://8.8.8.8/x.pdf"],
)
def test_non_public_urls_are_refused(url):
    with pytest.raises(ValueError, match="refusing"):
        check_public_url(url)


def test_public_ip_is_allowed():
    check_public_url("https://8.8.8.8/x.pdf")


def test_redirects_are_rechecked(monkeypatch):
    monkeypatch.setattr(requests, "get", redirect_to("http://127.0.0.1/"))
    with pytest.raises(ValueError, match="non-public"):
        get_public("https://8.8.8.8/start.pdf")
"""

AFTER = """
import pytest


@pytest.mark.parametrize("url", ["http://127.0.0.1/x.pdf"])
def test_non_public_addresses_are_refused_before_connecting(url):
    with pytest.raises(InvalidIPAddress):
        get_public(url)


@pytest.mark.parametrize("url", ["ftp://8.8.8.8/x.pdf"])
def test_non_http_schemes_are_refused(url):
    with pytest.raises(ValueError, match="only http and https"):
        get_public(url)
"""


def _gone(before: str, after: str, path: str = "tests/test_lit.py") -> list[str]:
    """Compare two versions of one test module.

    Args:
        before: Source at the base.
        after: Source now.
        path: The module's path.

    Returns:
        What :func:`removed` reports.
    """
    return removed(inventory(path, before), inventory(path, after))


def test_reproduces_the_commit_this_check_was_written_for() -> None:
    # The rewritten test checks a different call and exception, so it is a
    # replacement, not a rename, and the old one is reported whole.
    assert _gone(BEFORE, AFTER) == [
        "tests/test_lit.py::test_non_public_urls_are_refused",
        "tests/test_lit.py::test_public_ip_is_allowed",
        "tests/test_lit.py::test_redirects_are_rechecked",
    ]


def test_a_dropped_parametrize_case_is_reported_by_itself() -> None:
    after = BEFORE.replace('"http://[::1]/x.pdf", ', "")
    assert _gone(BEFORE, after) == [
        "tests/test_lit.py::test_non_public_urls_are_refused[url='http://[::1]/x.pdf']"
    ]


def test_a_case_moved_to_a_sibling_test_is_kept() -> None:
    before = (
        "@pytest.mark.parametrize('u', ['a', 'b'])\ndef test_x(u):\n    assert ok(u)\n"
    )
    after = (
        "@pytest.mark.parametrize('u', ['a'])\ndef test_x(u):\n    assert ok(u)\n"
        "@pytest.mark.parametrize('u', ['b'])\n"
        "def test_y(u):\n    assert ok(u, strict=True)\n"
    )
    assert _gone(before, after) == []


def test_an_exact_trailer_matches_an_id_with_brackets() -> None:
    node = "tests/test_lit.py::test_x[url='http://[::1]/x.pdf']"
    assert _matches(node, node)
    assert not _matches(node, "tests/test_lit.py::test_y*")


def test_reformatting_removes_nothing() -> None:
    src = "def test_a():\n    assert f(1, 2) == 3\n"
    wrapped = "def test_a():\n    assert f(\n        1,\n        2,\n    ) == 3\n"
    assert _gone(src, wrapped) == []


def test_a_rename_with_the_same_body_is_not_a_removal() -> None:
    assert (
        _gone(
            "def test_old():\n    assert f() == 1\n",
            "def test_new():\n    assert f() == 1\n",
        )
        == []
    )


def test_a_rename_that_also_renames_a_variable_is_not_a_removal() -> None:
    before = (
        "def test_per_km_share():\n"
        "    per_km = share(frames)\n"
        "    assert per_minute == approx(50 / 120)\n"
        "    assert per_km == approx(0.25)\n"
    )
    after = before.replace("per_km", "per_mile")
    assert _gone(before, after) == []


def test_a_move_to_another_file_is_not_a_removal() -> None:
    src = "def test_a():\n    assert f() == 1\n"
    before = inventory("tests/test_old.py", src)
    after = inventory("tests/test_new.py", src)
    assert removed(before, after) == []


def test_a_replacement_that_checks_something_else_is_a_removal() -> None:
    before = "def test_a():\n    assert parse('01-01-2026') == '2026-01-01'\n"
    after = "def test_b():\n    assert isinstance(Config(), Config)\n"
    assert _gone(before, after) == ["tests/test_lit.py::test_a"]


def test_methods_of_test_classes_are_inventoried() -> None:
    before = (
        "class TestA:\n"
        "    class TestInner:\n"
        "        def test_x(self):\n"
        "            assert 1\n"
    )
    assert [e.node_id for e in inventory("t/test_a.py", before)] == [
        "t/test_a.py::TestA::TestInner::test_x"
    ]
    assert _gone(before, "", "t/test_a.py") == ["t/test_a.py::TestA::TestInner::test_x"]


def test_non_literal_parametrize_values_are_tracked_by_function_only() -> None:
    src = "@pytest.mark.parametrize('x', CASES)\ndef test_a(x):\n    assert x\n"
    (entry,) = inventory("tests/test_a.py", src)
    assert entry.cases == frozenset()


def _git(repo: Path, *args: str) -> None:
    """Run git in a test repository.

    Args:
        repo: The repository.
        *args: git arguments.
    """
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository whose base commit holds ``BEFORE``, on a feature branch.

    Args:
        tmp_path: Directory to create it in.
        monkeypatch: To point the check at the base.

    Returns:
        The repository root.
    """
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.org")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_lit.py").write_text(BEFORE)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    monkeypatch.setenv("PREEN_BASE_REF", "main")
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    return tmp_path


def test_the_check_reports_removals_since_the_merge_base(repo: Path) -> None:
    (repo / "tests" / "test_lit.py").write_text(AFTER)
    _git(repo, "commit", "-q", "-am", "Use requests-hardened")
    result = RemovedTestsCheck(repo).run()
    assert not result.passed
    assert len(result.issues) == 3
    assert all(i.file == Path("tests/test_lit.py") for i in result.issues)


def test_uncommitted_removals_are_reported(repo: Path) -> None:
    (repo / "tests" / "test_lit.py").write_text(AFTER)
    assert len(RemovedTestsCheck(repo).run().issues) == 3


def test_trailers_acknowledge_removals_exactly_or_by_pattern(repo: Path) -> None:
    (repo / "tests" / "test_lit.py").write_text(AFTER)
    message = (
        "Use requests-hardened\n\n"
        "Removed-test: tests/test_lit.py::test_non_public_urls_are_refused\n"
        "Removed-tests: tests/test_lit.py::test_public_*\n"
    )
    _git(repo, "commit", "-q", "-am", message)
    issues = RemovedTestsCheck(repo).run().issues
    assert [i.description.split(" was ")[0] for i in issues] == [
        "tests/test_lit.py::test_redirects_are_rechecked"
    ]


def test_no_base_passes_with_a_note(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PREEN_BASE_REF", "no-such-ref")
    (repo / "tests" / "test_lit.py").write_text(AFTER)
    result = RemovedTestsCheck(repo).run()
    assert result.passed
    assert "No base" in result.issues[0].description


def test_outside_git_passes(tmp_path: Path) -> None:
    assert RemovedTestsCheck(tmp_path).run().passed


# Findings from the 0.11.0 release review, one test each.


def test_an_unchanged_sibling_with_the_same_body_cannot_stand_in() -> None:
    body = "    assert value(request.node.name)\n"
    before = f"def test_value_1(request):\n{body}\ndef test_value_2(request):\n{body}"
    after = f"def test_value_2(request):\n{body}"
    assert _gone(before, after) == ["tests/test_lit.py::test_value_1"]


def test_an_unchanged_sibling_sharing_a_value_cannot_hide_a_deleted_case() -> None:
    before = (
        "@pytest.mark.parametrize('x', [1, 2])\ndef test_abs(x):\n    assert abs(x)\n"
        "@pytest.mark.parametrize('x', [1, 2])\ndef test_order(x):\n    assert x < 3\n"
    )
    after = before.replace("[1, 2])\ndef test_abs", "[1])\ndef test_abs")
    assert _gone(before, after) == ["tests/test_lit.py::test_abs[x=2]"]


def test_keyword_parametrize_is_read() -> None:
    src = (
        "@pytest.mark.parametrize(argnames='x', argvalues=[1, 2])\n"
        "def test_v(x):\n"
        "    assert x\n"
    )
    assert _gone(src, src.replace("[1, 2]", "[1]")) == [
        "tests/test_lit.py::test_v[x=2]"
    ]


def test_class_level_parametrize_applies_to_methods() -> None:
    src = (
        "@pytest.mark.parametrize('x', [1, 2])\nclass TestValues:\n"
        "    def test_v(self, x):\n        assert x\n"
    )
    assert _gone(src, src.replace("[1, 2]", "[1]")) == [
        "tests/test_lit.py::TestValues::test_v[x=2]"
    ]


def test_argnames_spacing_and_param_ids_do_not_count() -> None:
    before = (
        "@pytest.mark.parametrize('x,y', [(1, 2), pytest.param(3, 4, id='one')])\n"
        "def test_x(x, y):\n    assert x < y\n"
    )
    after = before.replace("'x,y'", "'x, y'").replace("id='one'", "id='renamed'")
    assert _gone(before, after) == []


def test_a_repeated_value_counts_each_time() -> None:
    src = "@pytest.mark.parametrize('x', [1, 1])\ndef test_v(x):\n    assert x\n"
    assert _gone(src, src.replace("[1, 1]", "[1]")) == [
        "tests/test_lit.py::test_v[x=1#2]"
    ]


def test_unittest_and_conditional_tests_are_inventoried() -> None:
    src = (
        "import sys, unittest\n"
        "class ParserCase(unittest.TestCase):\n"
        "    def test_result(self):\n        self.assertTrue(1)\n"
        "if sys.version_info.major == 3:\n"
        "    def test_feature():\n        assert 1\n"
    )
    assert [e.node_id for e in inventory("t/test_a.py", src)] == [
        "t/test_a.py::ParserCase::test_result",
        "t/test_a.py::test_feature",
    ]


def test_an_exact_trailer_does_not_glob_its_brackets() -> None:
    assert _matches("t.py::test_v[x=1]", "t.py::test_v[x=1]")
    assert not _matches("t.py::test_v1", "t.py::test_v[x=1]")
    assert _matches("t.py::test_old_a", "t.py::test_old_*")


def test_latin1_and_bom_sources_parse() -> None:
    latin1 = "# -*- coding: latin-1 -*-\ndef test_caf\u00e9():\n    assert 1\n".encode(
        "latin-1"
    )
    bom = "\ufeffdef test_a():\n    assert 1\n".encode("utf-8")
    assert len(inventory("t/test_a.py", latin1)) == 1
    assert len(inventory("t/test_b.py", bom)) == 1


def test_a_trailer_quoted_in_prose_acknowledges_nothing(repo: Path) -> None:
    (repo / "tests" / "test_lit.py").write_text(AFTER)
    message = (
        "Use requests-hardened\n\n"
        "A trailer such as\nRemoved-tests: *\nwould acknowledge everything.\n\n"
        "Signed-off-by: t <t@example.org>\n"
    )
    _git(repo, "commit", "-q", "-am", message)
    assert len(RemovedTestsCheck(repo).run().issues) == 3


def test_a_pull_request_merge_commit_is_compared_with_its_first_parent(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The PR adds a file; meanwhile main deletes the tests. On GitHub the
    # checkout is a merge of the two, and main's deletion is not the PR's.
    _git(repo, "checkout", "-q", "main")
    (repo / "tests" / "test_lit.py").write_text(AFTER)
    _git(repo, "commit", "-q", "-am", "main deletes tests")
    _git(repo, "checkout", "-q", "feature")
    (repo / "notes.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "PR change")
    _git(repo, "checkout", "-q", "--detach", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "feature")
    monkeypatch.delenv("PREEN_BASE_REF")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/1/merge")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    monkeypatch.setenv("GITHUB_SHA", head)
    _git(repo, "update-ref", "refs/remotes/origin/main", "main~1")
    assert RemovedTestsCheck(repo).run().passed


def test_a_head_checkout_that_merged_main_uses_the_merge_base(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A workflow checking out the PR head, not GitHub's merge ref: the
    # branch merged main into itself, so HEAD^1 is the branch, not main.
    (repo / "tests" / "test_new.py").write_text("def test_n():\n    assert 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "feature test")
    _git(repo, "checkout", "-q", "main")
    (repo / "notes.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "main moves")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge main", "main")
    monkeypatch.delenv("PREEN_BASE_REF")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    (repo / "tests" / "test_new.py").unlink()
    assert RemovedTestsCheck(repo).run().passed


def test_a_star_inside_a_case_id_is_literal() -> None:
    assert _matches("t.py::test_v[x='*']", "t.py::test_v[x='*']")
    assert not _matches("t.py::test_v[x='two']", "t.py::test_v[x='*']")
    assert _matches("t.py::test_v[x='two']", "t.py::test_v*")


def test_a_local_function_named_param_is_a_value() -> None:
    before = "@pytest.mark.parametrize('x', [param(1)])\ndef test_v(x):\n    assert x\n"
    after = before.replace("[param(1)]", "[1]")
    assert _gone(before, after) == ["tests/test_lit.py::test_v[x=param(1)]"]


def test_type_checking_blocks_are_not_tests() -> None:
    src = "if TYPE_CHECKING:\n    def test_t():\n        assert 1\n"
    assert inventory("t/test_a.py", src) == []


def test_a_subdirectory_project_reads_its_base(repo: Path) -> None:
    (repo / "tests" / "test_lit.py").write_text(AFTER)
    assert len(RemovedTestsCheck(repo / "tests").run().issues) == 3


def test_a_deleted_latin1_test_file_is_reported(repo: Path) -> None:
    src = "# -*- coding: latin-1 -*-\nS = 'caf\u00e9'\ndef test_a():\n    assert S\n"
    (repo / "tests" / "test_latin.py").write_bytes(src.encode("latin-1"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add")
    _git(repo, "update-ref", "refs/heads/main", "HEAD")
    (repo / "tests" / "test_latin.py").unlink()
    assert [
        i.description.split(" was ")[0] for i in RemovedTestsCheck(repo).run().issues
    ] == ["tests/test_latin.py::test_a"]
