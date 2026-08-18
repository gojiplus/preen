"""Static-version, tag-driven release command in the devtools::release() spirit.

Under the fleet standard ``project.version`` is authoritative and the matching
``vX.Y.Z`` tag triggers the repo's release workflow (build, attestations, trusted
publishing, GitHub Release). This command runs the checks, verifies that the tag
and project metadata agree, asks for informed consent, then tags and pushes.
"""

import datetime
import json
import re
import subprocess
import tomllib
from pathlib import Path

import typer
from packaging.version import InvalidVersion, Version
from rich.console import Console
from rich.prompt import Confirm

from ..checks import ALL_CHECKS, run_checks
from ..checks.changelog import (
    has_version_entry,
    rename_unreleased_heading,
    unreleased_section_text,
)
from ..config import PreenConfig
from ..interactive import InteractiveReleaseWorkflow


def _git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in the project directory.

    Args:
        project_dir: Repository directory.
        *args: Git arguments.

    Returns:
        The completed process.
    """
    return subprocess.run(
        ["git", *args],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )


def _latest_tag(project_dir: Path) -> str | None:
    """Return the latest v* tag reachable from HEAD, or None."""
    result = _git(project_dir, "describe", "--tags", "--abbrev=0", "--match", "v*")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _tag_exists(project_dir: Path, tag: str) -> bool:
    """Return True if `tag` already exists locally (per ``git tag -l``)."""
    result = _git(project_dir, "tag", "-l", tag)
    return bool(result.stdout.strip())


def _remote_tag_exists(project_dir: Path, tag: str) -> bool:
    """Return True if `tag` already exists on origin.

    A tag that was never fetched passes the local check and then fails at
    push, after the changelog has been rewritten and committed. An offline
    or otherwise failing query answers False rather than blocking a release.

    Args:
        project_dir: Repository directory.
        tag: Tag name, e.g. ``v1.2.3``.

    Returns:
        True only when origin is reachable and already has the tag.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def _plugin_manifest_bump(project_dir: Path, version: str) -> Path | None:
    """Return the Claude Code plugin manifest needing a version bump, if any.

    The manifest carries a hardcoded version while everything else in the
    fleet standard is tag-derived, so it silently drifts behind the tags.

    Args:
        project_dir: Repository directory.
        version: Version being released.

    Returns:
        Path to the manifest when it declares a different version, else None.
    """
    manifest = project_dir / ".claude-plugin" / "plugin.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "version" not in data:
        return None
    return manifest if str(data["version"]) != version else None


def _write_plugin_version(manifest: Path, version: str) -> None:
    """Set the plugin manifest's version, preserving key order and indentation.

    Args:
        manifest: Path to .claude-plugin/plugin.json.
        version: Version to write.
    """
    text = manifest.read_text(encoding="utf-8")
    updated = re.sub(
        r'("version"\s*:\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{version}"',
        text,
        count=1,
    )
    manifest.write_text(updated, encoding="utf-8")


def _project_version(project_dir: Path) -> Version:
    """Return the project's required explicit version.

    Args:
        project_dir: Repository directory containing ``pyproject.toml``.

    Returns:
        The normalized declared version.

    Raises:
        ValueError: If project metadata or its explicit version is absent or
            invalid.
    """
    pyproject = project_dir / "pyproject.toml"
    try:
        with pyproject.open("rb") as file:
            project = tomllib.load(file).get("project", {})
    except FileNotFoundError:
        raise ValueError("pyproject.toml is required for release") from None
    except OSError as error:
        raise ValueError(f"cannot read pyproject.toml: {error}") from None
    except tomllib.TOMLDecodeError:
        raise ValueError("pyproject.toml is not valid TOML") from None
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml [project] must be a table")
    version = project.get("version")
    if version is None:
        raise ValueError("project.version must be declared explicitly")
    if not isinstance(version, str):
        raise ValueError("project.version must be a string")
    try:
        return Version(version)
    except InvalidVersion:
        raise ValueError(f"project.version {version!r} is not PEP 440-valid") from None


def _lockfile_error(project_dir: Path) -> str | None:
    """Return why a tracked lockfile cannot be released, if applicable.

    Args:
        project_dir: Repository directory containing the project metadata.

    Returns:
        An actionable error when ``uv.lock`` is dirty or stale, otherwise None.
    """
    lockfile = project_dir / "uv.lock"
    status = _git(project_dir, "status", "--porcelain", "--", "uv.lock").stdout.strip()
    if status:
        return "uv.lock has uncommitted changes; commit the refreshed lockfile"
    if not lockfile.exists():
        return None
    try:
        result = subprocess.run(
            ["uv", "lock", "--check"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"cannot verify uv.lock: {error}"
    if result.returncode != 0:
        return (
            "uv.lock is not up to date with pyproject.toml; run `uv lock` and commit it"
        )
    return None


def release_package(
    project_dir: Path,
    version: str | None = None,
    skip_checks: bool = False,
    dry_run: bool = False,
    console: Console | None = None,
) -> None:
    """Interactive tag-driven release workflow.

    Args:
        project_dir: Path to project directory.
        version: Version to release (without the ``v``); uses
            ``project.version`` if omitted.
        skip_checks: Skip running checks (if you just ran them).
        dry_run: Show what would happen without doing it.
        console: Rich console for output.

    Raises:
        typer.Exit: If checks block the release, the user cancels, or git
            commands fail.
    """
    console = console or Console()
    workflow = InteractiveReleaseWorkflow(console)

    console.print(
        "\n[bold cyan]preen release[/bold cyan] — tag-driven release workflow\n"
    )

    if not skip_checks:
        console.print("Running pre-release checks...\n")
        config = PreenConfig.from_pyproject(project_dir)
        results = run_checks(project_dir, ALL_CHECKS, skip=config.skip_checks or None)
    else:
        console.print("[yellow]Skipping checks as requested[/yellow]\n")
        results = {}

    # Dry runs are fully non-interactive: no confirmation gates, no prompts.
    if not dry_run:
        if not workflow.run_release_checks(results, "GitHub (tag push)"):
            console.print("\n[red]Release cancelled[/red]")
            raise typer.Exit(1)

        dirty = _git(project_dir, "status", "--porcelain").stdout.strip()
        if dirty:
            console.print("[yellow]Working tree is not clean:[/yellow]")
            for line in dirty.splitlines()[:10]:
                console.print(f"  {line}")
            if not Confirm.ask("Tag anyway?", default=False):
                raise typer.Exit(1)

    latest = _latest_tag(project_dir)
    if latest:
        console.print(f"Latest release tag: [bold]{latest}[/bold]")
    pyproject_status = _git(
        project_dir, "status", "--porcelain", "--", "pyproject.toml"
    ).stdout.strip()
    if pyproject_status:
        console.print(
            "[red]pyproject.toml has uncommitted changes[/red]; commit the "
            "release version before tagging."
        )
        raise typer.Exit(1)
    try:
        project_version = _project_version(project_dir)
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from None
    lockfile_error = _lockfile_error(project_dir)
    if lockfile_error:
        console.print(f"[red]{lockfile_error}[/red]")
        raise typer.Exit(1)
    if version is None:
        version = str(project_version)
        console.print(f"Using project.version [bold]{version}[/bold]")
    try:
        requested_version = Version(version)
    except InvalidVersion:
        console.print(f"[red]'{version}' is not a valid PEP 440 version[/red]")
        raise typer.Exit(1) from None
    if requested_version != project_version:
        console.print(
            f"[red]Requested version {requested_version} does not match "
            "project.version "
            f"{project_version}[/red]; run `uv version {version}` first."
        )
        raise typer.Exit(1)
    version = str(project_version)
    tag = f"v{version}"

    if _tag_exists(project_dir, tag):
        console.print(f"[red]Tag {tag} already exists[/red]")
        raise typer.Exit(1)
    if _remote_tag_exists(project_dir, tag):
        console.print(
            f"[red]Tag {tag} already exists on origin[/red] (not fetched locally); "
            "run `git fetch --tags` and pick another version."
        )
        raise typer.Exit(1)

    changelog_path = project_dir / "CHANGELOG.md"
    changelog_text = (
        changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""
    )
    # Local date, explicitly zoned: a changelog heading should carry the date
    # the releaser sees, not UTC's.
    today = datetime.datetime.now().astimezone().date().isoformat()
    rename_unreleased = False
    if not has_version_entry(changelog_text, version):
        unreleased = unreleased_section_text(changelog_text)
        if unreleased is not None and unreleased.strip():
            rename_unreleased = True
        else:
            console.print(f"[red]no changelog entry for {version}[/red]")
            raise typer.Exit(1)

    plugin_manifest = _plugin_manifest_bump(project_dir, version)

    if dry_run:
        console.print("\n[yellow]DRY RUN — would perform:[/yellow]")
        step = 1
        if rename_unreleased:
            console.print(
                f"  {step}. Rename [Unreleased] to [{version}] - {today} in "
                "CHANGELOG.md"
            )
            step += 1
        if plugin_manifest is not None:
            console.print(
                f"  {step}. Set version to {version} in .claude-plugin/plugin.json"
            )
            step += 1
        if rename_unreleased or plugin_manifest is not None:
            console.print(f'  {step}. git commit -m "Release {version}"')
            step += 1
        console.print(f"  {step}. git tag {tag}")
        step += 1
        console.print(f"  {step}. git push origin {tag}")
        step += 1
        console.print(f"  {step}. The tag push triggers the repo's release workflow")
        return

    # Ask about the rename now, but defer writing CHANGELOG.md until the
    # final tag confirmation is also accepted -- a decline at either prompt
    # must leave the working tree untouched, and the tagged commit must
    # actually contain the renamed entry (not just an uncommitted edit).
    if rename_unreleased and not Confirm.ask(
        f"CHANGELOG.md has no entry for {version}. Rename [Unreleased] to "
        f"[{version}] - {today}?",
        default=True,
    ):
        console.print("[red]Release cancelled[/red]")
        raise typer.Exit(1)

    if plugin_manifest is not None and not Confirm.ask(
        f".claude-plugin/plugin.json declares a different version. Set it to "
        f"{version}?",
        default=True,
    ):
        plugin_manifest = None

    if not Confirm.ask(f"\nTag and push [bold]{tag}[/bold]?", default=False):
        console.print("[red]Release cancelled[/red]")
        raise typer.Exit(1)

    release_paths: list[str] = []
    if rename_unreleased:
        changelog_path.write_text(
            rename_unreleased_heading(changelog_text, version, today),
            encoding="utf-8",
        )
        release_paths.append("CHANGELOG.md")
        console.print(f"Renamed [Unreleased] to [{version}] - {today} in CHANGELOG.md")
    if plugin_manifest is not None:
        _write_plugin_version(plugin_manifest, version)
        release_paths.append(".claude-plugin/plugin.json")
        console.print(f"Set .claude-plugin/plugin.json version to {version}")

    if release_paths:
        # Pathspec-limited commit: anything the user had staged stays staged
        # instead of being swept into the release commit.
        result = _git(
            project_dir, "commit", "-m", f"Release {version}", "--", *release_paths
        )
        if result.returncode != 0:
            console.print(f"[red]git commit failed:[/red] {result.stderr.strip()}")
            raise typer.Exit(1)
        console.print(f"Committed: {', '.join(release_paths)}")

    result = _git(project_dir, "tag", tag)
    if result.returncode != 0:
        console.print(f"[red]git tag failed:[/red] {result.stderr.strip()}")
        raise typer.Exit(1)
    console.print(f"Created tag {tag}")

    result = _git(project_dir, "push", "origin", tag)
    if result.returncode != 0:
        console.print(f"[red]git push failed:[/red] {result.stderr.strip()}")
        console.print(f"The local tag {tag} still exists; push it manually.")
        raise typer.Exit(1)

    console.print(
        f"\n[bold green]Pushed {tag} — the release workflow takes it from "
        "here.[/bold green]"
    )
    if release_paths:
        console.print(
            f"The 'Release {version}' commit is local-only; run [bold]git push"
            "[/bold] so it is reachable from your branch."
        )
