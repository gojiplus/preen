"""Tests for the `changelog` check (Keep a Changelog conformance)."""

from pathlib import Path

from preen.checks.base import Impact
from preen.checks.changelog import ChangelogCheck

KEEP_A_CHANGELOG = """\
# Changelog

## [Unreleased]

### Added

- Something new.

## [1.2.3] - 2026-01-01

### Fixed

- A bug.
"""


def _write(tmp_path: Path, content: str) -> None:
    (tmp_path / "CHANGELOG.md").write_text(content)


def test_missing_changelog_is_important(tmp_path: Path) -> None:
    result = ChangelogCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.impact == Impact.IMPORTANT
    assert "CHANGELOG.md" in issue.description
    assert "Keep a Changelog" in issue.explanation
    assert "preen release" in issue.explanation


def test_full_keep_a_changelog_passes(tmp_path: Path) -> None:
    _write(tmp_path, KEEP_A_CHANGELOG)
    result = ChangelogCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_no_recognizable_structure_is_important(tmp_path: Path) -> None:
    _write(tmp_path, "# Changelog\n\nJust some free-form notes.\n")
    result = ChangelogCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].impact == Impact.IMPORTANT


def test_version_headings_without_unreleased_is_info(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "# Changelog\n\n## [1.2.3] - 2026-01-01\n\n### Added\n\n- Stuff.\n",
    )
    result = ChangelogCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.impact == Impact.INFORMATIONAL
    assert "Unreleased" in issue.description


def test_unreleased_only_no_versions_passes(tmp_path: Path) -> None:
    _write(tmp_path, "# Changelog\n\n## [Unreleased]\n\n- Nothing yet.\n")
    result = ChangelogCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_unreleased_without_brackets_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "# Changelog\n\n## Unreleased\n\n- WIP.\n\n## v1.0.0\n\n- Initial.\n",
    )
    result = ChangelogCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_unreleased_case_insensitive_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "# Changelog\n\n## [UNRELEASED]\n\n- WIP.\n\n## v1.0.0\n\n- Initial.\n",
    )
    result = ChangelogCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_version_heading_paren_date_form_recognized(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "# Changelog\n\n## 1.2.3 (2026-01-01)\n\n- Stuff.\n",
    )
    result = ChangelogCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].impact == Impact.INFORMATIONAL


def test_version_heading_v_prefix_form_recognized(tmp_path: Path) -> None:
    _write(tmp_path, "# Changelog\n\n## v1.2.3\n\n- Stuff.\n")
    result = ChangelogCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].impact == Impact.INFORMATIONAL


def test_can_fix_is_false(tmp_path: Path) -> None:
    assert ChangelogCheck(tmp_path).can_fix() is False


def test_check_name_is_changelog(tmp_path: Path) -> None:
    assert ChangelogCheck(tmp_path).name == "changelog"
