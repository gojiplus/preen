"""Tests for the PEP 735 `depgroups` check."""

from pathlib import Path

import pytest

from preen.checks.base import Impact
from preen.checks.depgroups import DepgroupsCheck

MODERN_PYPROJECT = """\
[project]
name = "mypkg"

[project.optional-dependencies]
s3 = ["boto3"]

[dependency-groups]
dev = [
    "pre-commit>=4",
    { include-group = "test" },
    "ruff>=0.14",
]
test = ["pytest>=8"]
docs = ["sphinx>=8"]
"""


def _write(tmp_path: Path, content: str) -> None:
    (tmp_path / "pyproject.toml").write_text(content)


def test_modern_layout_passes(tmp_path: Path) -> None:
    _write(tmp_path, MODERN_PYPROJECT)
    result = DepgroupsCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_no_pyproject_passes(tmp_path: Path) -> None:
    result = DepgroupsCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_missing_dependency_groups_is_important(tmp_path: Path) -> None:
    _write(tmp_path, '[project]\nname = "mypkg"\n')
    result = DepgroupsCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.impact == Impact.IMPORTANT
    assert "dependency-groups" in issue.description.lower()
    assert "PEP 735" in issue.explanation


def test_missing_dev_group_is_important(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\n\n[dependency-groups]\ntest = ["pytest>=8"]\n',
    )
    result = DepgroupsCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.impact == Impact.IMPORTANT
    assert "dev" in issue.description.lower()
    assert "uv sync --all-groups" in issue.explanation


def test_dev_group_with_only_include_group_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\n\n'
        "[dependency-groups]\n"
        'dev = [{ include-group = "test" }]\n'
        'test = ["pytest>=8"]\n',
    )
    result = DepgroupsCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_dev_type_extra_in_optional_dependencies_is_important(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\n\n'
        "[project.optional-dependencies]\n"
        'test = ["pytest>=8"]\n'
        'docs = ["sphinx>=8"]\n\n'
        "[dependency-groups]\n"
        'dev = ["pre-commit>=4"]\n',
    )
    result = DepgroupsCheck(tmp_path).run()
    assert not result.passed
    dev_type_issues = [i for i in result.issues if "extra" in i.description.lower()]
    assert len(dev_type_issues) == 2
    for issue in dev_type_issues:
        assert issue.impact == Impact.IMPORTANT


def test_dev_type_extra_matched_case_insensitively(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\n\n'
        "[project.optional-dependencies]\n"
        'Test = ["pytest>=8"]\n\n'
        "[dependency-groups]\n"
        'dev = ["pre-commit>=4"]\n',
    )
    result = DepgroupsCheck(tmp_path).run()
    assert not result.passed
    assert any("extra" in i.description.lower() for i in result.issues)


def test_feature_extra_does_not_fire_dev_type_finding(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\n\n'
        "[project.optional-dependencies]\n"
        's3 = ["boto3"]\n\n'
        "[dependency-groups]\n"
        'dev = ["pre-commit>=4"]\n',
    )
    result = DepgroupsCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_group_listed_in_both_places_is_info(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\n\n'
        "[project.optional-dependencies]\n"
        's3 = ["boto3"]\n\n'
        "[dependency-groups]\n"
        'dev = ["pre-commit>=4"]\n'
        's3 = ["boto3"]\n',
    )
    result = DepgroupsCheck(tmp_path).run()
    duplicate_issues = [i for i in result.issues if "both" in i.description.lower()]
    assert len(duplicate_issues) == 1
    issue = duplicate_issues[0]
    assert issue.impact == Impact.INFORMATIONAL
    assert not result.passed


def test_malformed_toml_passes(tmp_path: Path) -> None:
    _write(tmp_path, "[project\nname = mypkg\n")
    result = DepgroupsCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_can_fix_is_false(tmp_path: Path) -> None:
    assert DepgroupsCheck(tmp_path).can_fix() is False


@pytest.mark.parametrize("extra", ["type-check", "type_check", "Type-Checking"])
def test_dev_type_extra_name_variants_flagged(tmp_path: Path, extra: str) -> None:
    """Hyphen/underscore/case variants must all be recognized (issue #18)."""
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "x"\n\n[project.optional-dependencies]\n'
        f'"{extra}" = ["pyright"]\n\n[dependency-groups]\ndev = ["pytest"]\n'
    )
    result = DepgroupsCheck(tmp_path).run()
    assert any("dev-type dependency" in i.description for i in result.issues)
