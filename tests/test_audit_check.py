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
