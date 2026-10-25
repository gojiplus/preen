"""Tests for the pip-audit `audit` check."""

import json
import subprocess
from pathlib import Path

from preen.checks.audit import AuditCheck
from preen.checks.base import Impact, Severity

CLEAN_REPORT = json.dumps(
    {
        "dependencies": [
            {"name": "requests", "version": "2.31.0", "vulns": []},
        ],
        "fixes": [],
    }
)

VULN_REPORT = json.dumps(
    {
        "dependencies": [
            {"name": "requests", "version": "2.31.0", "vulns": []},
            {
                "name": "urllib3",
                "version": "1.26.0",
                "vulns": [
                    {
                        "id": "PYSEC-2023-0001",
                        "fix_versions": ["1.26.17"],
                        "description": "some CVE",
                    }
                ],
            },
            {
                "name": "jinja2",
                "version": "3.0.0",
                "vulns": [
                    {
                        "id": "GHSA-abcd-1234",
                        "fix_versions": [],
                        "description": "another CVE",
                    },
                    {
                        "id": "PYSEC-2024-9999",
                        "fix_versions": ["3.1.3"],
                        "description": "yet another CVE",
                    },
                ],
            },
        ],
        "fixes": [],
    }
)


def _write_lock(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("# lock\n")


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_no_uv_lock_skips(tmp_path: Path) -> None:
    result = AuditCheck(tmp_path).run()
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.INFO
    assert issue.impact == Impact.INFORMATIONAL
    assert "uv.lock" in issue.description


def test_uv_export_failure_skips(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=1, stderr="boom")
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    assert "export" in result.issues[0].description.lower()


def test_uv_missing_skips(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            raise FileNotFoundError
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    assert "export" in result.issues[0].description.lower()


def test_pip_audit_missing_skips(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd[0] in ("pip-audit", "uvx"):
            raise FileNotFoundError
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.INFO
    assert "pip install pip-audit" in issue.description


def test_pip_audit_via_uvx_fallback(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd == ["pip-audit", "--version"]:
            raise FileNotFoundError
        if cmd == ["uvx", "--version"]:
            return _completed(cmd, returncode=0, stdout="uvx 0.9\n")
        if cmd[:2] == ["uvx", "pip-audit"]:
            return _completed(cmd, returncode=0, stdout=CLEAN_REPORT)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []
    assert any(c[:2] == ["uvx", "pip-audit"] for c in calls)


def test_clean_report_passes(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=0, stdout=CLEAN_REPORT)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_vulnerable_report_produces_issues(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(
                cmd, returncode=0, stdout="urllib3==1.26.0\njinja2==3.0.0\n"
            )
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=1, stdout=VULN_REPORT)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 2  # requests has no vulns, so no issue for it

    by_pkg = {issue.description.split()[0]: issue for issue in result.issues}
    assert "urllib3" in by_pkg
    assert "jinja2" in by_pkg

    urllib3_issue = by_pkg["urllib3"]
    assert urllib3_issue.impact == Impact.IMPORTANT
    assert "PYSEC-2023-0001" in urllib3_issue.description
    assert "1.26.17" in urllib3_issue.description

    jinja2_issue = by_pkg["jinja2"]
    assert "GHSA-abcd-1234" in jinja2_issue.description
    assert "PYSEC-2024-9999" in jinja2_issue.description
    assert "3.1.3" in jinja2_issue.description

    assert all(issue.proposed_fix is None for issue in result.issues)


def test_malformed_json_skips(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=1, stdout="not json{{{")
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    assert "could not complete" in result.issues[0].description.lower()


def test_pip_audit_crash_skips(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=120)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    assert "could not complete" in result.issues[0].description.lower()


def test_unexpected_pip_audit_exit_code_skips(tmp_path: Path, monkeypatch) -> None:
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=2, stderr="network error")
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    assert "could not complete" in result.issues[0].description.lower()


def test_exit_code_one_with_empty_stdout_skips(tmp_path: Path, monkeypatch) -> None:
    """A returncode of 1 alone doesn't mean "vulns found" -- pip-audit also

    exits 1 on a bad invocation (e.g. an unresolvable/unhashable
    requirement) without ever printing a JSON report. That must be treated
    as "could not complete", not silently read as a clean, empty report.
    """
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(
                cmd,
                returncode=1,
                stdout="",
                stderr="ERROR: requirement ... does not contain a hash",
            )
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    assert "could not complete" in result.issues[0].description.lower()


def test_unexpected_json_shape_skips(tmp_path: Path, monkeypatch) -> None:
    """Valid JSON that isn't the expected `{"dependencies": [...]}` shape

    (e.g. a bare list, from some other tool/version) must degrade
    gracefully rather than crash on `.get()`.
    """
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=0, stdout="[]")
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    assert "could not complete" in result.issues[0].description.lower()


REQUIREMENTS_WITH_GIT_DEP = """\
# This file was autogenerated by uv via the following command:
#    uv export --format requirements-txt --no-emit-project --all-groups
requests==2.31.0 \\
    --hash=sha256:aaaa \\
    --hash=sha256:bbbb
py-canon @ git+https://github.com/gojiplus/py-canon@abcdef1234567890
urllib3==1.26.0 \\
    --hash=sha256:cccc
"""

CLEAN_REPORT_FILTERED = json.dumps(
    {
        "dependencies": [
            {"name": "requests", "version": "2.31.0", "vulns": []},
            {"name": "urllib3", "version": "1.26.0", "vulns": []},
        ],
        "fixes": [],
    }
)

MIXED_NON_PYPI_REQUIREMENTS = """\
requests==2.31.0
localpkg @ file:///Users/x/localpkg
directurl @ https://example.com/directurl-1.0-py3-none-any.whl
gitpkg @ git+https://example.com/gitpkg.git
-e git+https://example.com/editablepkg.git#egg=editablepkg
"""


def test_non_pypi_requirement_dropped_reports_info_and_passes(
    tmp_path: Path, monkeypatch
) -> None:
    """A VCS/direct-reference requirement (e.g. a git dependency) can't be

    scanned by `pip-audit --disable-pip` (no hash to verify against). It
    should be dropped from what's sent to pip-audit and surfaced as a
    single info-level note, not fail the whole audit when the remaining,
    PyPI-resolvable dependencies are clean.
    """
    _write_lock(tmp_path)
    written_requirements: dict[str, str] = {}

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout=REQUIREMENTS_WITH_GIT_DEP)
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            requirements_path = Path(cmd[cmd.index("-r") + 1])
            written_requirements["text"] = requirements_path.read_text()
            return _completed(cmd, returncode=0, stdout=CLEAN_REPORT_FILTERED)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()

    # The git dependency never reaches pip-audit.
    text = written_requirements["text"]
    assert "py-canon" not in text
    assert "requests==2.31.0" in text
    assert "urllib3==1.26.0" in text

    # A genuine pass: no vulnerabilities among the auditable deps, with an
    # informational note about the one dependency that couldn't be scanned.
    assert result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.INFO
    assert issue.impact == Impact.INFORMATIONAL
    assert "py-canon" in issue.description
    assert "not auditable" in issue.description.lower()


def test_multiple_non_pypi_markers_all_dropped(tmp_path: Path, monkeypatch) -> None:
    """Direct file:, http(s):, git+ references, and `-e ` editable installs

    are all non-PyPI-auditable and should all be dropped and named.
    """
    _write_lock(tmp_path)
    written_requirements: dict[str, str] = {}
    clean_report = json.dumps(
        {
            "dependencies": [
                {"name": "requests", "version": "2.31.0", "vulns": []},
            ],
            "fixes": [],
        }
    )

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout=MIXED_NON_PYPI_REQUIREMENTS)
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            requirements_path = Path(cmd[cmd.index("-r") + 1])
            written_requirements["text"] = requirements_path.read_text()
            return _completed(cmd, returncode=0, stdout=clean_report)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()

    text = written_requirements["text"]
    assert "requests==2.31.0" in text
    for dropped_name in ("localpkg", "directurl", "gitpkg", "editablepkg"):
        assert dropped_name not in text

    assert result.passed
    assert len(result.issues) == 1
    description = result.issues[0].description
    for dropped_name in ("localpkg", "directurl", "gitpkg", "editablepkg"):
        assert dropped_name in description


def test_dependencies_null_skips(tmp_path: Path, monkeypatch) -> None:
    """`{"dependencies": null}` is valid JSON but not a usable report --

    must not raise on iterating `None`, and should degrade to the same
    "could not complete" skip as any other unusable report.
    """
    _write_lock(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="requests==2.31.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(
                cmd, returncode=0, stdout=json.dumps({"dependencies": None})
            )
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    assert "could not complete" in result.issues[0].description.lower()


def test_non_dict_dependency_entries_are_skipped(tmp_path: Path, monkeypatch) -> None:
    """Non-dict entries in the dependencies list (a stray string, None, an

    int) must be skipped rather than crash `.get()`; well-formed entries
    alongside them are still processed normally.
    """
    _write_lock(tmp_path)
    report = json.dumps(
        {
            "dependencies": [
                "oops-not-a-dict",
                {
                    "name": "urllib3",
                    "version": "1.26.0",
                    "vulns": [{"id": "PYSEC-2023-0001", "fix_versions": ["1.26.17"]}],
                },
                None,
                42,
            ],
            "fixes": [],
        }
    )

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="urllib3==1.26.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=1, stdout=report)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    assert "urllib3" in result.issues[0].description


def test_can_fix_is_false(tmp_path: Path) -> None:
    assert AuditCheck(tmp_path).can_fix() is False


def test_audit_ignore_reports_but_does_not_fail(tmp_path: Path, monkeypatch) -> None:
    """An ignored advisory drops out of the failure and shows up as info."""
    _write_lock(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.preen]\naudit_ignore = ["GHSA-abcd-1234", "PYSEC-2024-9999"]\n'
    )

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="urllib3==1.26.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=1, stdout=VULN_REPORT)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()

    # jinja2's two advisories are both ignored, so only urllib3 still fails.
    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    assert not result.passed
    assert [i.description.split()[0] for i in errors] == ["urllib3"]

    infos = [i for i in result.issues if i.severity == Severity.INFO]
    assert len(infos) == 1
    assert "audit_ignore" in infos[0].description
    assert "jinja2 3.0.0: GHSA-abcd-1234" in infos[0].description
    assert "jinja2 3.0.0: PYSEC-2024-9999" in infos[0].description


def test_audit_ignore_of_every_advisory_passes(tmp_path: Path, monkeypatch) -> None:
    """When everything pip-audit found is ignored, the check passes."""
    _write_lock(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.preen]\n"
        'audit_ignore = ["PYSEC-2023-0001", "GHSA-abcd-1234", "PYSEC-2024-9999"]\n'
    )

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="urllib3==1.26.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=1, stdout=VULN_REPORT)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert result.passed
    assert all(i.severity == Severity.INFO for i in result.issues)


def test_audit_ignore_matches_an_alias(tmp_path: Path, monkeypatch) -> None:
    """pip-audit reports PYSEC as the id and the GHSA/CVE as aliases.

    A repo writes down whichever id it read (GitHub's advisory page shows the
    GHSA), so any of the names for one advisory must match.
    """
    _write_lock(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.preen]\naudit_ignore = ["GHSA-8mgp-746c-j5xp"]\n'
    )
    report = json.dumps(
        {
            "dependencies": [
                {
                    "name": "nltk",
                    "version": "3.10.3",
                    "vulns": [
                        {
                            "id": "PYSEC-2026-3740",
                            "aliases": ["CVE-2026-81726", "GHSA-8mgp-746c-j5xp"],
                            "fix_versions": [],
                            "description": "pathsec bypass",
                        }
                    ],
                }
            ],
            "fixes": [],
        }
    )

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="nltk==3.10.3\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=1, stdout=report)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    result = AuditCheck(tmp_path).run()
    assert result.passed
    assert len(result.issues) == 1
    assert result.issues[0].severity == Severity.INFO
    # Reported under the name the configuration used, so the reader can find
    # the entry to remove later.
    assert "nltk 3.10.3: GHSA-8mgp-746c-j5xp" in result.issues[0].description


def _run_with_config(tmp_path: Path, monkeypatch, config: str, report: str):
    _write_lock(tmp_path)
    (tmp_path / "pyproject.toml").write_text(config)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, returncode=0, stdout="pkg==1.0\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, returncode=0, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=1, stdout=report)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    return AuditCheck(tmp_path).run()


def test_audit_ignore_is_case_insensitive(tmp_path: Path, monkeypatch) -> None:
    """A repo that typed the id in lower case still gets its exception."""
    result = _run_with_config(
        tmp_path,
        monkeypatch,
        '[tool.preen]\naudit_ignore = ["pysec-2023-0001"]\n',
        VULN_REPORT,
    )
    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    assert [i.description.split()[0] for i in errors] == ["jinja2"]
    infos = [i for i in result.issues if i.severity == Severity.INFO]
    assert any("urllib3 1.26.0: PYSEC-2023-0001" in i.description for i in infos)


def test_audit_ignore_reports_entries_that_match_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    """The signal that upstream shipped a fix and the entry can go."""
    result = _run_with_config(
        tmp_path,
        monkeypatch,
        '[tool.preen]\naudit_ignore = ["GHSA-abcd-1234", "GHSA-gone-0000"]\n',
        VULN_REPORT,
    )
    stale = [i for i in result.issues if "match no advisory" in i.description]
    assert len(stale) == 1
    assert "GHSA-gone-0000" in stale[0].description
    assert "GHSA-abcd-1234" not in stale[0].description
    assert stale[0].severity == Severity.INFO
    # Still failing on urllib3 and on jinja2's other, unignored advisory.
    assert not result.passed


def test_vulnerability_without_an_id_still_reports(tmp_path: Path, monkeypatch) -> None:
    """An entry with no id is neither dropped nor printed with a dangling colon."""
    report = json.dumps(
        {
            "dependencies": [
                {"name": "pkg", "version": "1.0", "vulns": [{"fix_versions": ["1.1"]}]}
            ],
            "fixes": [],
        }
    )
    result = _run_with_config(tmp_path, monkeypatch, "[tool.preen]\n", report)
    assert not result.passed
    assert (
        result.issues[0].description
        == "pkg 1.0 has known vulnerabilities (fix available: 1.1)"
    )


def test_listing_two_names_for_one_advisory_marks_neither_stale(
    tmp_path: Path, monkeypatch
) -> None:
    """A repo may list both the PYSEC and the GHSA it saw; both matched."""
    report = json.dumps(
        {
            "dependencies": [
                {
                    "name": "nltk",
                    "version": "3.10.3",
                    "vulns": [
                        {
                            "id": "PYSEC-2026-3740",
                            "aliases": ["GHSA-8mgp-746c-j5xp"],
                            "fix_versions": [],
                        }
                    ],
                }
            ],
            "fixes": [],
        }
    )
    result = _run_with_config(
        tmp_path,
        monkeypatch,
        '[tool.preen]\naudit_ignore = ["PYSEC-2026-3740", "GHSA-8mgp-746c-j5xp"]\n',
        report,
    )
    assert result.passed
    assert not [i for i in result.issues if "match no advisory" in i.description]


def test_null_or_string_aliases_do_not_crash(tmp_path: Path, monkeypatch) -> None:
    """A report with aliases: null, or a bare string, still yields the finding."""
    report = json.dumps(
        {
            "dependencies": [
                {
                    "name": "a",
                    "version": "1",
                    "vulns": [{"id": "PYSEC-1", "aliases": None, "fix_versions": []}],
                },
                {
                    "name": "b",
                    "version": "1",
                    "vulns": [
                        {"id": "PYSEC-2", "aliases": "GHSA-x", "fix_versions": []}
                    ],
                },
            ],
            "fixes": [],
        }
    )
    result = _run_with_config(
        tmp_path, monkeypatch, '[tool.preen]\naudit_ignore = ["GHSA-x"]\n', report
    )
    assert not result.passed
    errors = sorted(
        i.description.split()[0] for i in result.issues if i.severity == Severity.ERROR
    )
    # Neither crashes; the bare-string alias is not treated as a match either.
    assert errors == ["a", "b"]


EXTRAS_PYPROJECT = """\
[project]
name = "fixture"
version = "0.1.0"
dependencies = ["requests"]

[project.optional-dependencies]
web = ["pillow"]
"""

CONFLICTING_EXTRAS_PYPROJECT = """\
[project]
name = "fixture"
version = "0.1.0"
dependencies = ["requests"]

[project.optional-dependencies]
cpu = ["pillow"]
gpu = ["accelerate"]

[tool.uv]
conflicts = [[{extra = "cpu"}, {extra = "gpu"}]]
"""

#: Pins each extra contributes to an export, standing in for a uv.lock.
EXTRA_PINS = {"web": ["pillow==12.3.0"], "cpu": ["pillow==12.3.0"], "gpu": []}

#: What the fake pip-audit knows about: one advisory per vulnerable pin.
ADVISORIES = {
    ("pillow", "12.3.0"): {"id": "GHSA-pill-0000", "fix_versions": ["13.0.0"]},
    ("requests", "2.31.0"): {"id": "GHSA-reqs-0000", "fix_versions": ["2.32.0"]},
}


def _fake_uv_and_pip_audit(exports: list[list[str]], fail_extra: str | None = None):
    """Fake `uv export` honoring extras flags, and a pip-audit that reads it.

    The export carries an extra's pins only when the command selects that
    extra, which is what makes a missing `--all-extras` observable.
    """

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            exports.append(cmd)
            if "--all-extras" in cmd:
                selected = list(EXTRA_PINS)
            else:
                selected = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--extra"]
            if fail_extra in selected:
                return _completed(
                    cmd, returncode=2, stderr="error: Extra `gpu` is broken"
                )
            pins = ["requests==2.31.0"]
            for extra in selected:
                pins.extend(p for p in EXTRA_PINS[extra] if p not in pins)
            return _completed(cmd, stdout="\n".join(pins) + "\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            text = Path(cmd[cmd.index("-r") + 1]).read_text()
            dependencies = []
            for line in text.split():
                name, version = line.split("==")
                vulns = (
                    [ADVISORIES[(name, version)]]
                    if (name, version) in ADVISORIES
                    else []
                )
                dependencies.append({"name": name, "version": version, "vulns": vulns})
            report = {"dependencies": dependencies, "fixes": []}
            returncode = 1 if any(d["vulns"] for d in dependencies) else 0
            return _completed(cmd, returncode=returncode, stdout=json.dumps(report))
        raise AssertionError(f"unexpected call: {cmd}")

    return fake_run


def test_package_reachable_only_through_an_extra_is_audited(
    tmp_path: Path, monkeypatch
) -> None:
    _write_lock(tmp_path)
    # The core pin's advisory is ignored so the only failure is the extra's.
    (tmp_path / "pyproject.toml").write_text(
        EXTRAS_PYPROJECT + '\n[tool.preen]\naudit_ignore = ["GHSA-reqs-0000"]\n'
    )
    exports: list[list[str]] = []
    monkeypatch.setattr(
        "preen.checks.audit.subprocess.run", _fake_uv_and_pip_audit(exports)
    )

    result = AuditCheck(tmp_path).run()

    assert not result.passed
    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    assert len(errors) == 1
    assert "pillow 12.3.0" in errors[0].description
    assert "GHSA-pill-0000" in errors[0].description
    assert len(exports) == 1
    assert "--all-extras" in exports[0]


def test_conflicting_extras_are_exported_one_at_a_time(
    tmp_path: Path, monkeypatch
) -> None:
    _write_lock(tmp_path)
    (tmp_path / "pyproject.toml").write_text(CONFLICTING_EXTRAS_PYPROJECT)
    exports: list[list[str]] = []
    monkeypatch.setattr(
        "preen.checks.audit.subprocess.run", _fake_uv_and_pip_audit(exports)
    )

    result = AuditCheck(tmp_path).run()

    # The groups once, then each extra without the groups.
    assert [c[5:] for c in exports] == [
        ["--all-groups"],
        ["--no-default-groups", "--extra", "cpu"],
        ["--no-default-groups", "--extra", "gpu"],
    ]
    assert not any("--all-extras" in c for c in exports)
    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    # requests is in both exports but is reported once.
    assert sorted(e.description.split(" has ")[0] for e in errors) == [
        "pillow 12.3.0",
        "requests 2.31.0",
    ]


def test_an_extra_that_will_not_export_fails_the_check(
    tmp_path: Path, monkeypatch
) -> None:
    _write_lock(tmp_path)
    (tmp_path / "pyproject.toml").write_text(CONFLICTING_EXTRAS_PYPROJECT)
    exports: list[list[str]] = []
    monkeypatch.setattr(
        "preen.checks.audit.subprocess.run",
        _fake_uv_and_pip_audit(exports, fail_extra="gpu"),
    )

    result = AuditCheck(tmp_path).run()

    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    # ERROR/IMPORTANT, not the info-level skip, so `--strict` gates on it.
    assert issue.severity == Severity.ERROR
    assert issue.impact == Impact.IMPORTANT
    assert "--extra gpu" in issue.description
    assert "Extra `gpu` is broken" in issue.description


EXTRA_GROUP_CONFLICT_PYPROJECT = """\
[project]
name = "demo"
version = "0.1.0"
dependencies = ["requests"]

[project.optional-dependencies]
legacy = ["six==1.16.0"]

[dependency-groups]
dev = ["six==1.17.0"]

[tool.uv]
conflicts = [[{extra = "legacy"}, {group = "dev"}]]
"""


def _fake_uv_with_groups(exports: list[list[str]]):
    """Fake `uv export` that, like uv, rejects a conflicting extra and group.

    Groups follow uv's selection rules: the default group (dev) unless
    `--no-default-groups`, every group with `--all-groups`, plus `--group`.
    pip-audit flags six 1.16.0 and 1.17.0 so both sides must be scanned.
    """
    advisories = {
        ("six", "1.16.0"): {"id": "GHSA-six-0016", "fix_versions": ["9"]},
        ("six", "1.17.0"): {"id": "GHSA-six-0017", "fix_versions": ["9"]},
        ("requests", "2.31.0"): None,
    }

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            exports.append(cmd)
            extras = ["legacy"] if "--all-extras" in cmd else []
            extras += [cmd[i + 1] for i, a in enumerate(cmd) if a == "--extra"]
            groups = [] if "--no-default-groups" in cmd else ["dev"]
            if "--all-groups" in cmd:
                groups = ["dev"]
            groups += [cmd[i + 1] for i, a in enumerate(cmd) if a == "--group"]
            if "legacy" in extras and "dev" in groups:
                return _completed(
                    cmd,
                    returncode=2,
                    stderr="error: Extra `legacy` and group `dev` are incompatible",
                )
            pins = ["requests==2.31.0"]
            if "legacy" in extras:
                pins.append("six==1.16.0")
            if "dev" in groups:
                pins.append("six==1.17.0")
            return _completed(cmd, stdout="\n".join(pins) + "\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            text = Path(cmd[cmd.index("-r") + 1]).read_text()
            dependencies = []
            for line in text.split():
                name, version = line.split("==")
                vuln = advisories.get((name, version))
                dependencies.append(
                    {"name": name, "version": version, "vulns": [vuln] if vuln else []}
                )
            report = {"dependencies": dependencies, "fixes": []}
            returncode = 1 if any(d["vulns"] for d in dependencies) else 0
            return _completed(cmd, returncode=returncode, stdout=json.dumps(report))
        raise AssertionError(f"unexpected call: {cmd}")

    return fake_run


def test_an_extra_conflicting_with_a_group_is_audited_apart_from_it(
    tmp_path: Path, monkeypatch
) -> None:
    _write_lock(tmp_path)
    (tmp_path / "pyproject.toml").write_text(EXTRA_GROUP_CONFLICT_PYPROJECT)
    exports: list[list[str]] = []
    monkeypatch.setattr(
        "preen.checks.audit.subprocess.run", _fake_uv_with_groups(exports)
    )

    result = AuditCheck(tmp_path).run()

    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    # Both sides were exported and scanned, so both advisories surface.
    assert sorted(e.description.split(" has ")[0] for e in errors) == [
        "six 1.16.0",
        "six 1.17.0",
    ]


def test_an_advisory_listed_twice_is_named_once(tmp_path: Path, monkeypatch) -> None:
    # pip-audit can return one advisory as two records (one per source).
    _write_lock(tmp_path)
    vuln = {"id": "PYSEC-2026-215", "fix_versions": ["3.15"], "aliases": []}
    report = json.dumps(
        {
            "dependencies": [
                {"name": "idna", "version": "3.11", "vulns": [vuln, dict(vuln)]}
            ],
            "fixes": [],
        }
    )

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["uv", "export"]:
            return _completed(cmd, stdout="idna==3.11\n")
        if cmd == ["pip-audit", "--version"]:
            return _completed(cmd, stdout="pip-audit 2.7\n")
        if cmd[0] == "pip-audit":
            return _completed(cmd, returncode=1, stdout=report)
        raise AssertionError(f"unexpected call: {cmd}")

    monkeypatch.setattr("preen.checks.audit.subprocess.run", fake_run)
    (issue,) = AuditCheck(tmp_path).run().issues

    assert issue.description.count("PYSEC-2026-215") == 1


def test_a_legacy_dev_dependencies_group_is_still_audited(
    tmp_path: Path, monkeypatch
) -> None:
    # uv still reads tool.uv.dev-dependencies as the `dev` group.
    _write_lock(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        EXTRA_GROUP_CONFLICT_PYPROJECT.replace(
            '[dependency-groups]\ndev = ["six==1.17.0"]\n', ""
        ).replace("[tool.uv]\n", '[tool.uv]\ndev-dependencies = ["six==1.17.0"]\n')
    )
    exports: list[list[str]] = []
    monkeypatch.setattr(
        "preen.checks.audit.subprocess.run", _fake_uv_with_groups(exports)
    )

    result = AuditCheck(tmp_path).run()

    errors = [i for i in result.issues if i.severity == Severity.ERROR]
    assert sorted(e.description.split(" has ")[0] for e in errors) == [
        "six 1.16.0",
        "six 1.17.0",
    ]
