"""Tests for the link-scanning check (URL extraction/skip rules, not network)."""

from pathlib import Path

from preen.checks.base import Impact, Severity
from preen.checks.links import LinkCheck


def test_no_files_no_urls_passes(tmp_path: Path) -> None:
    result = LinkCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_file_with_no_urls_passes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Just prose, no links here.\n")
    result = LinkCheck(tmp_path).run()
    assert result.passed


def test_localhost_and_example_urls_skipped(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "README.md").write_text(
        "See http://localhost:8000/x and https://example.com/y\n"
    )

    def fail_check(self, url):
        raise AssertionError(f"should not check skip-listed url: {url}")

    monkeypatch.setattr(LinkCheck, "_check_url_sync", fail_check)
    result = LinkCheck(tmp_path).run()
    assert result.passed


def test_dead_link_flagged(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "README.md").write_text("Broken: https://dead.example-real.test/x\n")
    monkeypatch.setattr(
        LinkCheck,
        "_check_url_sync",
        lambda self, url: (url, 0, "Connection refused"),
    )
    result = LinkCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert "Dead link" in issue.description
    assert issue.impact == Impact.CRITICAL  # README is a critical file


def test_client_error_flagged_as_warning(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "notes.txt").write_text("https://real-domain-example.test/missing\n")
    monkeypatch.setattr(LinkCheck, "_check_url_sync", lambda self, url: (url, 404, ""))
    result = LinkCheck(tmp_path).run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.severity == Severity.WARNING
    assert "HTTP 404" in issue.description


def test_server_error_flagged(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "notes.txt").write_text("https://real-domain-example.test/broken\n")
    monkeypatch.setattr(LinkCheck, "_check_url_sync", lambda self, url: (url, 503, ""))
    result = LinkCheck(tmp_path).run()
    assert not result.passed
    assert "Server error" in result.issues[0].description


def test_auth_and_rate_limit_codes_not_flagged(tmp_path: Path, monkeypatch) -> None:
    """401/403/405/429 are anti-bot/auth noise, not real dead links."""
    urls = [
        "https://a-real-domain-1.test/x",
        "https://a-real-domain-2.test/y",
        "https://a-real-domain-3.test/z",
        "https://a-real-domain-4.test/w",
    ]
    (tmp_path / "notes.txt").write_text("\n".join(urls) + "\n")
    codes = {401: urls[0], 403: urls[1], 405: urls[2], 429: urls[3]}
    responses = {url: (url, code, "") for code, url in codes.items()}
    monkeypatch.setattr(LinkCheck, "_check_url_sync", lambda self, url: responses[url])
    result = LinkCheck(tmp_path).run()
    assert result.passed


def test_success_code_not_flagged(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "notes.txt").write_text("https://a-real-domain.test/ok\n")
    monkeypatch.setattr(LinkCheck, "_check_url_sync", lambda self, url: (url, 200, ""))
    result = LinkCheck(tmp_path).run()
    assert result.passed


def test_hidden_and_excluded_dirs_skipped(tmp_path: Path, monkeypatch) -> None:
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "config.md").write_text("https://a-real-domain.test/hidden\n")
    excluded = tmp_path / ".venv"
    excluded.mkdir()
    (excluded / "notes.txt").write_text("https://a-real-domain.test/venv\n")

    def fail_check(self, url):
        raise AssertionError(f"should not check hidden/excluded url: {url}")

    monkeypatch.setattr(LinkCheck, "_check_url_sync", fail_check)
    result = LinkCheck(tmp_path).run()
    assert result.passed


def test_can_fix_false(tmp_path: Path) -> None:
    assert LinkCheck(tmp_path).can_fix() is False
