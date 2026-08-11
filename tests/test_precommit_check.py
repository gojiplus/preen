"""Tests for the pre-commit config check."""

from pathlib import Path

from preen.checks.base import Severity
from preen.checks.precommit import PreCommitCheck

VALID = """repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.1
    hooks:
      - id: ruff
"""


def test_valid_config_passes(tmp_path: Path) -> None:
    (tmp_path / ".pre-commit-config.yaml").write_text(VALID)
    result = PreCommitCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_yml_extension_also_accepted(tmp_path: Path) -> None:
    (tmp_path / ".pre-commit-config.yml").write_text(VALID)
    assert PreCommitCheck(tmp_path).run().passed


def test_missing_config_flagged(tmp_path: Path) -> None:
    result = PreCommitCheck(tmp_path).run()
    assert not result.passed
    assert result.issues[0].severity == Severity.WARNING
    assert "No pre-commit config" in result.issues[0].description


def test_unparseable_config_is_an_error(tmp_path: Path) -> None:
    """Broken YAML is the case worth catching hardest.

    pre-commit errors out rather than running, so the hooks silently stop
    happening and nothing else in CI reports it.
    """
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: [\n")
    result = PreCommitCheck(tmp_path).run()
    assert not result.passed
    assert result.issues[0].severity == Severity.ERROR
    assert "does not parse" in result.issues[0].description


def test_config_with_no_repos_flagged(tmp_path: Path) -> None:
    """A config with no hooks parses fine and runs nothing.

    This is the shape the check exists for: valid, silent, and useless.
    """
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
    result = PreCommitCheck(tmp_path).run()
    assert not result.passed
    assert "runs nothing" in result.issues[0].description


def test_offers_no_fix(tmp_path: Path) -> None:
    """Writing someone hooks they did not choose is not a fix."""
    assert PreCommitCheck(tmp_path).can_fix() is False
