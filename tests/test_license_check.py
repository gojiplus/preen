"""Tests for the PEP 639 `license` check and its `preen fix license` fixer."""

import tomllib
from pathlib import Path

from preen.checks.base import Impact
from preen.checks.license import LicenseCheck, _tokenize_spdx

MODERN_PYPROJECT = """\
[project]
name = "mypkg"
license = "MIT"
license-files = ["LICENSE"]
classifiers = [
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
]
"""


def _write(tmp_path: Path, content: str) -> None:
    (tmp_path / "pyproject.toml").write_text(content)


def _load(tmp_path: Path) -> dict:
    with (tmp_path / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_modern_form_passes(tmp_path: Path) -> None:
    _write(tmp_path, MODERN_PYPROJECT)
    (tmp_path / "LICENSE").write_text("MIT License\n")
    result = LicenseCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_missing_license_is_important(tmp_path: Path) -> None:
    _write(tmp_path, '[project]\nname = "mypkg"\n')
    result = LicenseCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.impact == Impact.IMPORTANT
    assert "license" in issue.description.lower()


def test_table_form_text_is_important(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\nlicense = { text = "MIT" }\n',
    )
    result = LicenseCheck(tmp_path).run()
    assert not result.passed
    table_issues = [i for i in result.issues if "table form" in i.description.lower()]
    assert len(table_issues) == 1
    issue = table_issues[0]
    assert issue.impact == Impact.IMPORTANT
    assert "PEP 639" in issue.explanation
    assert "preen fix license" in issue.explanation
    assert issue.proposed_fix is not None


def test_table_form_file_is_unfixable(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\nlicense = { file = "LICENSE" }\n',
    )
    (tmp_path / "LICENSE").write_text("some text\n")
    result = LicenseCheck(tmp_path).run()
    table_issues = [i for i in result.issues if "table form" in i.description.lower()]
    assert len(table_issues) == 1
    issue = table_issues[0]
    assert issue.impact == Impact.IMPORTANT
    assert issue.proposed_fix is None
    assert "manually" in issue.explanation.lower()


def test_table_form_ambiguous_text_is_unfixable(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\nlicense = { text = "BSD" }\n',
    )
    result = LicenseCheck(tmp_path).run()
    table_issues = [i for i in result.issues if "table form" in i.description.lower()]
    assert len(table_issues) == 1
    assert table_issues[0].proposed_fix is None


def test_invalid_spdx_expression_is_important(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\nlicense = "MIT AND"\n',
    )
    result = LicenseCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].impact == Impact.IMPORTANT


def test_unknown_spdx_identifier_is_informational(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\nlicense = "MadeUpLicense-1.0"\n',
    )
    result = LicenseCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].impact == Impact.INFORMATIONAL


def test_compound_allowlisted_expression_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\nlicense = "MIT OR Apache-2.0"\n',
    )
    result = LicenseCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_deprecated_classifier_alongside_license_is_important(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        '[project]\nname = "mypkg"\nlicense = "MIT"\n'
        'classifiers = ["License :: OSI Approved :: MIT License"]\n',
    )
    result = LicenseCheck(tmp_path).run()
    assert not result.passed
    classifier_issues = [
        i for i in result.issues if "classifier" in i.description.lower()
    ]
    assert len(classifier_issues) == 1
    issue = classifier_issues[0]
    assert issue.impact == Impact.IMPORTANT
    assert issue.proposed_fix is not None


def test_missing_license_files_with_license_file_present_is_info(
    tmp_path: Path,
) -> None:
    _write(tmp_path, '[project]\nname = "mypkg"\nlicense = "MIT"\n')
    (tmp_path / "LICENSE").write_text("MIT License\n")
    result = LicenseCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.impact == Impact.INFORMATIONAL
    assert issue.proposed_fix is not None


def test_missing_license_files_without_license_file_is_silent(
    tmp_path: Path,
) -> None:
    _write(tmp_path, '[project]\nname = "mypkg"\nlicense = "MIT"\n')
    result = LicenseCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_fix_migrates_text_table_form_end_to_end(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "# top comment\n"
        '[project]\nname = "mypkg"\nlicense = { text = "Apache License 2.0" }\n',
    )
    result = LicenseCheck(tmp_path).run()
    table_issues = [i for i in result.issues if "table form" in i.description.lower()]
    assert len(table_issues) == 1
    table_issues[0].proposed_fix.apply()

    data = _load(tmp_path)
    assert data["project"]["license"] == "Apache-2.0"
    assert "# top comment" in (tmp_path / "pyproject.toml").read_text()

    # Idempotent: re-running the check now finds nothing to migrate.
    rerun = LicenseCheck(tmp_path).run()
    assert rerun.passed
    assert rerun.issues == []


def test_fix_skips_ambiguous_text_without_mutating_file(tmp_path: Path) -> None:
    original = '[project]\nname = "mypkg"\nlicense = { text = "BSD" }\n'
    _write(tmp_path, original)
    result = LicenseCheck(tmp_path).run()
    table_issues = [i for i in result.issues if "table form" in i.description.lower()]
    assert table_issues[0].proposed_fix is None
    assert (tmp_path / "pyproject.toml").read_text() == original


def test_fix_removes_deprecated_classifiers_end_to_end(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "# top comment\n"
        '[project]\nname = "mypkg"\nlicense = "MIT"\n'
        "classifiers = [\n"
        '    "Intended Audience :: Developers",\n'
        '    "License :: OSI Approved :: MIT License",\n'
        "]\n",
    )
    result = LicenseCheck(tmp_path).run()
    classifier_issues = [
        i for i in result.issues if "classifier" in i.description.lower()
    ]
    classifier_issues[0].proposed_fix.apply()

    data = _load(tmp_path)
    assert data["project"]["classifiers"] == ["Intended Audience :: Developers"]
    assert "# top comment" in (tmp_path / "pyproject.toml").read_text()

    rerun = LicenseCheck(tmp_path).run()
    assert rerun.passed
    assert rerun.issues == []


def test_fix_adds_license_files_end_to_end(tmp_path: Path) -> None:
    _write(tmp_path, '# top comment\n[project]\nname = "mypkg"\nlicense = "MIT"\n')
    (tmp_path / "LICENSE").write_text("MIT License\n")

    result = LicenseCheck(tmp_path).run()
    assert len(result.issues) == 1
    result.issues[0].proposed_fix.apply()

    data = _load(tmp_path)
    assert data["project"]["license-files"] == ["LICENSE"]
    assert "# top comment" in (tmp_path / "pyproject.toml").read_text()

    rerun = LicenseCheck(tmp_path).run()
    assert rerun.passed
    assert rerun.issues == []


def test_can_fix_is_true(tmp_path: Path) -> None:
    assert LicenseCheck(tmp_path).can_fix() is True


def test_empty_license_table_message(tmp_path: Path) -> None:
    """`license = {}` must not be reported as `{ file = "None" }` (issue #16)."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nlicense = {}\nlicense-files = ["LICENSE"]\n'
    )
    result = LicenseCheck(tmp_path).run()
    descriptions = [i.description for i in result.issues]
    assert any("empty or unrecognized" in d for d in descriptions)
    assert not any("None" in d for d in descriptions)


def test_spdx_tokenizer_respects_word_boundaries() -> None:
    """An identifier starting with AND/OR/WITH must not split (issue #16)."""
    assert _tokenize_spdx("ANDover-1.0") == ["ANDover-1.0"]
    assert _tokenize_spdx("ORbit-2.0") == ["ORbit-2.0"]
    assert _tokenize_spdx("MIT AND Apache-2.0") == ["MIT", "AND", "Apache-2.0"]
    assert _tokenize_spdx("GPL-2.0-only WITH Classpath-exception-2.0") == [
        "GPL-2.0-only",
        "WITH",
        "Classpath-exception-2.0",
    ]
