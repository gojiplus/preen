"""Tests for the `changelog` check (Keep a Changelog conformance)."""

from pathlib import Path

import pytest

from preen.checks.base import Impact
from preen.checks.changelog import ChangelogCheck, has_version_entry, heading_version

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


def test_prerelease_heading_does_not_satisfy_final_version() -> None:
    """`## [0.2.0rc1]` must not gate-pass a 0.2.0 release (issue #14)."""
    text = "## [0.2.0rc1] - 2026-01-01\n\n- something\n"
    assert not has_version_entry(text, "0.2.0")
    assert has_version_entry(text, "0.2.0rc1")


def test_prerelease_version_matches_its_own_heading() -> None:
    text = "## [1.2.3rc1] - 2026-01-01\n\n- something\n"
    assert has_version_entry(text, "1.2.3rc1")


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("[1.2.3] - 2026-01-01", "1.2.3"),
        ("1.2.3 (2026-01-01)", "1.2.3"),
        ("v1.2.3", "1.2.3"),
        ("[0.2.0rc1]", "0.2.0rc1"),
        ("[1.2.3.post1]", "1.2.3.post1"),
        ("[1.2.3.dev0]", "1.2.3.dev0"),
        ("Unreleased", None),
        ("[Unreleased]", None),
        ("Changed", None),
        ("2026-01-01", None),
    ],
)
def test_heading_version_parsing(heading: str, expected: str | None) -> None:
    assert heading_version(heading) == expected


def test_version_entry_matches_normalized_forms() -> None:
    assert has_version_entry("## [1.2.3.0] - 2026-01-01\n", "1.2.3")


def test_invalid_requested_version_never_matches() -> None:
    assert not has_version_entry("## [1.2.3] - 2026-01-01\n", "not-a-version")
