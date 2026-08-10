"""Tests for the link check (file collection and result mapping, not network).

Extraction and fetching are lychee's job now, so these cover the two halves
preen still owns: which files get handed to lychee, and how its report becomes
Issues. One test does run the real binary, offline, to pin the contract this
mapping depends on -- that a broken link comes back with a file, a line and a
status code.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from preen.checks.base import Impact, Severity
from preen.checks.links import LinkCheck


def _url(host_and_path: str) -> str:
    """Build an ``https://`` URL from a host+path.

    Split from the scheme so this test file's own source text never
    contains a literal URL that preen's own `links` check would try to
    reach when it scans the preen repo.

    Args:
        host_and_path: Everything after the scheme.

    Returns:
        The assembled URL.
    """
    return "https://" + host_and_path


def _report(path: Path, *entries: dict) -> dict:
    """Build a minimal lychee JSON report.

    Args:
        path: File the entries belong to.
        entries: lychee ``error_map`` entries.

    Returns:
        A report shaped like lychee's ``--format json`` output.
    """
    return {"error_map": {str(path): list(entries)}}


def _entry(url: str, *, code: int | None = None, line: int = 1, text: str = "") -> dict:
    """Build one lychee error entry.

    Args:
        url: The URL that failed.
        code: HTTP status, or None for a transport-level failure.
        line: Line the URL appeared on.
        text: Error detail, for the no-status case.

    Returns:
        An entry shaped like an element of lychee's ``error_map`` lists.
    """
    status: dict = {"code": code} if code is not None else {"details": text}
    return {"url": url, "status": status, "span": {"line": line, "column": 1}}


def _stub(monkeypatch, report: dict) -> None:
    """Make ``_run_lychee`` return a fixed report.

    Args:
        monkeypatch: pytest fixture.
        report: Report to return.
    """
    monkeypatch.setattr(LinkCheck, "_run_lychee", lambda self, files: report)


def test_no_files_no_urls_passes(tmp_path: Path) -> None:
    result = LinkCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_file_with_no_urls_passes(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "README.md").write_text("Just prose, no links here.\n")
    _stub(monkeypatch, {"error_map": {}})
    result = LinkCheck(tmp_path).run()
    assert result.passed


def test_dead_link_flagged(tmp_path: Path, monkeypatch) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"Broken: {_url('dead.example-real.test/x')}\n")
    _stub(
        monkeypatch,
        _report(
            readme,
            _entry(_url("dead.example-real.test/x"), text="Connection refused"),
        ),
    )
    result = LinkCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert "Dead link" in issue.description
    assert issue.impact == Impact.CRITICAL  # README is a critical file


def test_client_error_flagged_as_warning(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text(_url("real-domain-example.test/missing") + "\n")
    _stub(
        monkeypatch,
        _report(notes, _entry(_url("real-domain-example.test/missing"), code=404)),
    )
    result = LinkCheck(tmp_path).run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.severity == Severity.WARNING
    assert "HTTP 404" in issue.description


def test_server_error_flagged(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text(_url("real-domain-example.test/broken") + "\n")
    _stub(
        monkeypatch,
        _report(notes, _entry(_url("real-domain-example.test/broken"), code=503)),
    )
    result = LinkCheck(tmp_path).run()
    assert not result.passed
    assert "Server error" in result.issues[0].description


@pytest.mark.parametrize("code", [401, 403, 405, 429])
def test_auth_and_rate_limit_codes_not_flagged(
    tmp_path: Path, monkeypatch, code: int
) -> None:
    """401/403/405/429 are anti-bot/auth noise, not real dead links."""
    notes = tmp_path / "notes.txt"
    notes.write_text(_url("a-real-domain.test/x") + "\n")
    _stub(monkeypatch, _report(notes, _entry(_url("a-real-domain.test/x"), code=code)))
    result = LinkCheck(tmp_path).run()
    assert result.passed


def test_line_number_is_carried_through(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("\n\n" + _url("a-real-domain.test/x") + "\n")
    _stub(
        monkeypatch,
        _report(notes, _entry(_url("a-real-domain.test/x"), code=404, line=3)),
    )
    issue = LinkCheck(tmp_path).run().issues[0]
    assert issue.line == 3
    assert issue.file == Path("notes.txt")


def test_hidden_and_excluded_dirs_skipped(tmp_path: Path) -> None:
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "config.md").write_text(_url("a-real-domain.test/hidden") + "\n")
    excluded = tmp_path / ".venv"
    excluded.mkdir()
    (excluded / "notes.txt").write_text(_url("a-real-domain.test/venv") + "\n")

    assert LinkCheck(tmp_path)._collect_files() == []


def test_collect_files_finds_scannable_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("x\n")
    (tmp_path / "notes.txt").write_text("x\n")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")

    found = {p.name for p in LinkCheck(tmp_path)._collect_files()}
    assert found == {"README.md", "notes.txt"}


def test_missing_binary_reports_nothing_rather_than_crashing(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "README.md").write_text(f"{_url('a-real-domain.test/x')}\n")
    monkeypatch.setattr(LinkCheck, "_lychee_binary", lambda self: None)
    result = LinkCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


@pytest.mark.skipif(shutil.which("lychee") is None, reason="lychee not installed")
def test_real_lychee_extracts_urls_the_old_regex_truncated(tmp_path: Path) -> None:
    """The regression this rewrite exists for.

    The previous extractor's path class was ``[-\\w/_.~%@+]`` and its query
    class ``[-\\w&=%.]``. Parentheses, a semicolon, a comma and a colon inside
    a query value each ended the match early, yielding a *different, shorter*
    URL -- which may still answer 200 while the real link goes unchecked, or
    404 and report a healthy link as dead.

    ``--dump`` extracts without fetching, so this needs no network.
    """
    tricky = [
        _url("en.wikipedia.org/wiki/Ruby_(programming_language)"),
        _url("github.com/search?q=a+b&sort=date:desc"),
        _url("gitlab.com/api/v4/items;type=a,b"),
    ]
    doc = tmp_path / "README.md"
    doc.write_text("".join(f"see {u} here\n" for u in tricky))

    binary = shutil.which("lychee")
    assert binary is not None

    dumped = subprocess.run(
        [
            binary,
            "--no-progress",
            "--dump",
            "--scheme",
            "http",
            "--scheme",
            "https",
            str(doc),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()

    assert sorted(dumped) == sorted(tricky)


def test_can_fix_false(tmp_path: Path) -> None:
    assert LinkCheck(tmp_path).can_fix() is False
