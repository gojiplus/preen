"""Tests for the `preen` CLI: table rendering, exit codes, and command wiring.

Command wiring tests patch the underlying command functions (imported into
`preen.cli`'s namespace) rather than exercising the real implementations --
those are covered by their own test modules.
"""

from pathlib import Path

from typer.testing import CliRunner

import preen.cli as cli_mod
from preen.checks.base import CheckResult, Impact, Issue, Severity
from preen.cli import app

runner = CliRunner()


def _result(
    name: str, *, passed: bool, issues: list[Issue] | None = None
) -> CheckResult:
    return CheckResult(check=name, passed=passed, issues=issues or [])


def test_check_all_passed_exits_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        cli_mod, "run_checks", lambda *a, **k: {"ruff": _result("ruff", passed=True)}
    )
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "passed" in result.stdout
    assert "All checks passed" in result.stdout


def test_check_with_issues_shows_table_and_next_steps(monkeypatch) -> None:
    issue = Issue(
        check="ruff",
        severity=Severity.WARNING,
        description="Linting issues found (2 problems)",
        impact=Impact.IMPORTANT,
    )
    monkeypatch.setattr(
        cli_mod,
        "run_checks",
        lambda *a, **k: {"ruff": _result("ruff", passed=False, issues=[issue])},
    )
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0  # not --strict: informational/important don't gate
    assert "warning" in result.stdout
    assert "Found 1 issue(s)" in result.stdout
    assert "1 important" in result.stdout
    # The bracketed severity prefix must survive Rich markup rendering
    # rather than being silently swallowed as a bogus style tag.
    assert "[warning] ruff:" in result.stdout
    assert "preen fix" in result.stdout
    assert "--explain" in result.stdout


def test_check_error_severity_shows_failed_status(monkeypatch) -> None:
    issue = Issue(
        check="ruff",
        severity=Severity.ERROR,
        description="boom",
        impact=Impact.CRITICAL,
    )
    monkeypatch.setattr(
        cli_mod,
        "run_checks",
        lambda *a, **k: {"ruff": _result("ruff", passed=False, issues=[issue])},
    )
    result = runner.invoke(app, ["check"])
    assert "failed" in result.stdout
    assert "1 critical" in result.stdout


def test_check_strict_exits_nonzero_on_important_issue(monkeypatch) -> None:
    issue = Issue(
        check="ruff",
        severity=Severity.WARNING,
        description="x",
        impact=Impact.IMPORTANT,
    )
    monkeypatch.setattr(
        cli_mod,
        "run_checks",
        lambda *a, **k: {"ruff": _result("ruff", passed=False, issues=[issue])},
    )
    result = runner.invoke(app, ["check", "--strict"])
    assert result.exit_code == 1


def test_check_strict_passes_with_only_informational_issues(monkeypatch) -> None:
    issue = Issue(
        check="structure",
        severity=Severity.INFO,
        description="consider src layout",
        impact=Impact.INFORMATIONAL,
    )
    monkeypatch.setattr(
        cli_mod,
        "run_checks",
        lambda *a, **k: {
            "structure": _result("structure", passed=False, issues=[issue])
        },
    )
    result = runner.invoke(app, ["check", "--strict"])
    assert result.exit_code == 0


def test_check_explain_uses_educational_prompt(monkeypatch) -> None:
    issue = Issue(
        check="ruff",
        severity=Severity.WARNING,
        description="boom",
        explanation="Why it matters.",
        impact=Impact.IMPORTANT,
    )
    monkeypatch.setattr(
        cli_mod,
        "run_checks",
        lambda *a, **k: {"ruff": _result("ruff", passed=False, issues=[issue])},
    )
    result = runner.invoke(app, ["check", "--explain"])
    assert "About ruff check" in result.stdout
    assert "Why it matters." in result.stdout
    assert "Use --explain" not in result.stdout


def test_check_forwards_skip_and_only(monkeypatch) -> None:
    captured = {}

    def fake_run_checks(project_dir, checks, skip=None, only=None):
        captured["skip"] = skip
        captured["only"] = only
        return {}

    monkeypatch.setattr(cli_mod, "run_checks", fake_run_checks)
    runner.invoke(app, ["check", "--skip", "ruff", "--only", "structure"])
    assert captured["skip"] == ["ruff"]
    assert captured["only"] == ["structure"]


def test_new_command_calls_new_package(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        cli_mod,
        "new_package",
        lambda name, org=None, description=None, cli=None: captured.update(
            name=name, org=org, description=description, cli=cli
        ),
    )
    result = runner.invoke(
        app, ["new", "mypkg", "--org", "acme", "--description", "desc", "--cli"]
    )
    assert result.exit_code == 0
    assert captured == {
        "name": "mypkg",
        "org": "acme",
        "description": "desc",
        "cli": True,
    }


def test_adopt_command_defaults_to_cwd(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(
        cli_mod,
        "run_adopt",
        lambda repo, release_migration=False: captured.update(
            repo=repo, release_migration=release_migration
        ),
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["adopt"])
    assert result.exit_code == 0
    assert captured["repo"] == Path.cwd()
    assert captured["release_migration"] is False


def test_adopt_command_with_path_and_flag(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(
        cli_mod,
        "run_adopt",
        lambda repo, release_migration=False: captured.update(
            repo=repo, release_migration=release_migration
        ),
    )
    result = runner.invoke(app, ["adopt", str(tmp_path), "--release-migration"])
    assert result.exit_code == 0
    assert captured["repo"] == Path(str(tmp_path))
    assert captured["release_migration"] is True


def test_update_command_calls_run_update(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(cli_mod, "run_update", lambda repo: captured.update(repo=repo))
    result = runner.invoke(app, ["update", str(tmp_path)])
    assert result.exit_code == 0
    assert captured["repo"] == Path(str(tmp_path))


def test_fix_command_forwards_args(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(
        cli_mod,
        "apply_fixes",
        lambda **kwargs: captured.update(kwargs),
    )
    result = runner.invoke(app, ["fix", "ruff", "--path", str(tmp_path), "--auto"])
    assert result.exit_code == 0
    assert captured["check_name"] == "ruff"
    assert captured["project_dir"] == Path(str(tmp_path))
    assert captured["auto"] is True
    assert captured["interactive"] is False  # --auto overrides default interactive


def test_fix_command_batch_mode(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(
        cli_mod, "apply_fixes", lambda **kwargs: captured.update(kwargs)
    )
    runner.invoke(app, ["fix", "--path", str(tmp_path), "--batch"])
    assert captured["interactive"] is False
    assert captured["auto"] is False


def test_release_command_forwards_args(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(
        cli_mod, "release_package", lambda **kwargs: captured.update(kwargs)
    )
    result = runner.invoke(
        app,
        [
            "release",
            "1.2.3",
            "--path",
            str(tmp_path),
            "--skip-checks",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert captured == {
        "project_dir": Path(str(tmp_path)),
        "version": "1.2.3",
        "skip_checks": True,
        "dry_run": True,
    }
