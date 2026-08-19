"""Tests for the template adoption/drift check."""

from pathlib import Path

from preen.checks import template as template_mod
from preen.checks.base import Impact, Severity
from preen.checks.template import TemplateCheck


def test_missing_answers_file_is_critical(tmp_path: Path) -> None:
    result = TemplateCheck(tmp_path).run()
    assert not result.passed
    assert any(
        issue.impact == Impact.CRITICAL and issue.severity == Severity.ERROR
        for issue in result.issues
    )


def test_matching_commit_passes(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".copier-answers.yml").write_text(
        "_commit: v1.2.0\n_src_path: gh:gojiplus/py-canon\nproject_name: x\n"
    )
    monkeypatch.setattr(template_mod, "latest_canon_tag", lambda: "v1.2.0")
    result = TemplateCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_moving_tag_commit_is_important(tmp_path: Path, monkeypatch) -> None:
    """A `_commit: v1` record breaks `copier update` — flagged even offline."""
    (tmp_path / ".copier-answers.yml").write_text(
        "_commit: v1\n_src_path: gh:gojiplus/py-canon\nproject_name: x\n"
    )
    monkeypatch.setattr(
        template_mod, "latest_canon_tag", lambda: (_ for _ in ()).throw(AssertionError)
    )
    result = TemplateCheck(tmp_path).run()
    assert not result.passed
    important = [i for i in result.issues if i.impact == Impact.IMPORTANT]
    assert len(important) == 1
    assert "moving tag" in important[0].description
    assert "preen adopt" in (important[0].explanation or "")


def test_stale_commit_is_important(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".copier-answers.yml").write_text(
        "_commit: v1.0.0\n_src_path: gh:gojiplus/py-canon\nproject_name: x\n"
    )
    monkeypatch.setattr(template_mod, "latest_canon_tag", lambda: "v1.2.0")
    result = TemplateCheck(tmp_path).run()
    assert not result.passed
    important = [i for i in result.issues if i.impact == Impact.IMPORTANT]
    assert len(important) == 1
    assert "v1.0.0" in important[0].description
    assert "v1.2.0" in important[0].description
    # An INFO issue lists the drift.
    infos = [i for i in result.issues if i.severity == Severity.INFO]
    assert len(infos) == 1


def test_offline_skips_gracefully(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".copier-answers.yml").write_text(
        "_commit: v1.0.0\n_src_path: gh:gojiplus/py-canon\n"
    )
    monkeypatch.setattr(template_mod, "latest_canon_tag", lambda: None)
    result = TemplateCheck(tmp_path).run()
    assert result.passed
    assert all(i.severity == Severity.INFO for i in result.issues)


def test_invalid_yaml_is_critical(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("_commit: [unclosed\n")
    result = TemplateCheck(tmp_path).run()
    assert not result.passed
    assert any(i.impact == Impact.CRITICAL for i in result.issues)


def test_latest_canon_tag_concrete_only(monkeypatch) -> None:
    """`concrete_only` skips moving major tags even when they sort highest."""

    class FakeResult:
        returncode = 0
        stdout = (
            "aaa\trefs/tags/v1\n"
            "bbb\trefs/tags/v1.0.0\n"
            "ccc\trefs/tags/v1.0.1\n"
            "ddd\trefs/tags/v2\n"
        )

    monkeypatch.setattr(template_mod.subprocess, "run", lambda *a, **k: FakeResult())
    assert template_mod.latest_canon_tag() == "v2"
    assert template_mod.latest_canon_tag(concrete_only=True) == "v1.0.1"
