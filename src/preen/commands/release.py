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
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class VersionedFile:
    """A file carrying a copy of the version that the tag does not set.

    Attributes:
        path: Absolute path to the file.
        rel: Repo-relative path, for prompts and the commit pathspec.
        current: The version it currently records.
    """

    path: Path
    rel: str
    current: str


def _plugin_manifest_bump(project_dir: Path, version: str) -> VersionedFile | None:
    """Return the Claude Code plugin manifest needing a version bump, if any.

    The manifest carries a hardcoded version while everything else in the
    fleet standard is tag-derived, so it silently drifts behind the tags.

    Args:
        project_dir: Repository directory.
        version: Version being released.

    Returns:
        The file when it declares a different version, else None.
    """
    rel = ".claude-plugin/plugin.json"
    manifest = project_dir / rel
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "version" not in data:
        return None
    current = str(data["version"])
    return VersionedFile(manifest, rel, current) if current != version else None


def _citation_bump(project_dir: Path, version: str) -> VersionedFile | None:
    """Return CITATION.cff when it cites a different version.

    Same problem as the plugin manifest, with a worse consequence: whoever
    cites the package copies the number in this file, so a stale one outlives
    the release in someone else's bibliography.

    Args:
        project_dir: Repository directory.
        version: Version being released.

    Returns:
        The file when it cites a different version, else None.
    """
    rel = "CITATION.cff"
    citation = project_dir / rel
    if not citation.exists():
        return None
    match = _CITATION_VERSION.search(citation.read_text(encoding="utf-8"))
    if match is None:
        return None
    current = match.group("value").strip().strip("\"'")
    return VersionedFile(citation, rel, current) if current != version else None


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


def _write_citation_version(citation: Path, version: str) -> None:
    """Set CITATION.cff's version, leaving the rest of the file alone.

    A targeted substitution rather than a YAML round-trip: re-emitting the
    document would reorder keys and drop the comments a human wrote.

    Args:
        citation: Path to CITATION.cff.
        version: Version to write.
    """
    text = citation.read_text(encoding="utf-8")
    updated = _CITATION_VERSION.sub(
        lambda m: f'{m.group("prefix")}"{version}"', text, count=1
    )
    citation.write_text(updated, encoding="utf-8")


#: Which writer updates which file. Keyed by the repo-relative path so the
#: prompt, the write and the commit pathspec cannot drift apart.
VERSION_WRITERS: dict[str, Callable[[Path, str], None]] = {
    ".claude-plugin/plugin.json": _write_plugin_version,
    "CITATION.cff": _write_citation_version,
}


def _version_bumps(project_dir: Path, version: str) -> list[VersionedFile]:
    """Return every tracked file whose recorded version is out of date.

    Args:
        project_dir: Repository directory.
        version: Version being released.

    Returns:
        The files needing a bump, in a stable order.
    """
    found = (
        _plugin_manifest_bump(project_dir, version),
        _citation_bump(project_dir, version),
    )
    return [entry for entry in found if entry is not None]


#: `version: 1.2.3` in a CFF file, however it is quoted.
_CITATION_VERSION = re.compile(
    r"^(?P<prefix>version:\s*)(?P<value>.+?)\s*$", re.MULTILINE
)


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


def _artifact_error(project_dir: Path) -> str | None:
    """Build the distributions and check them the way PyPI will.

    The release flow tags and pushes; the tag push is what triggers the build
    that actually publishes. Anything wrong with the artifact was therefore
    discovered after the tag existed, which is the expensive place to find it.
    Building here costs seconds and moves that discovery before the tag.

    ``twine check`` is what py-canon's reusable release workflow runs, so the
    two agree on what a publishable artifact is: it validates the metadata PyPI
    will parse. ``check-wheel-contents`` asks the structural question twine
    does not -- whether the wheel's RECORD actually describes the wheel. On a
    well-formed uv_build wheel that is a cheap confirmation rather than a
    likely catch; it earns its place on the day a backend upgrade produces a
    wheel that is subtly not one.

    Args:
        project_dir: Repository directory.

    Returns:
        An actionable error, or None when the artifacts are fine or the tools
        could not be fetched. A missing network is not the repo's fault and
        must not block a release; a failing check is.
    """
    with tempfile.TemporaryDirectory() as tmp:
        build = _run_tool(
            ["uv", "build", "--out-dir", tmp, str(project_dir)], project_dir
        )
        if build is None:
            return None
        if build.returncode != 0:
            return f"uv build failed:\n{(build.stderr or build.stdout).strip()}"

        # By suffix, not by "every file here": uv writes a .gitignore into the
        # output directory, and twine rejects the whole invocation over it.
        artifacts = sorted(
            str(path)
            for path in Path(tmp).iterdir()
            if path.is_file() and path.name.endswith((".whl", ".tar.gz"))
        )
        if not artifacts:
            return "uv build produced no artifacts"

        wheels = [path for path in artifacts if path.endswith(".whl")]
        # No --strict: it turns twine's warnings into failures, and a missing
        # long_description would then block a release over something the files
        # check already covers. py-canon's reusable release workflow runs plain
        # `twine check`, and the two must agree on what publishable means.
        commands = [(["uvx", "twine", "check", *artifacts], "twine check")]
        if wheels:
            commands.append(
                (["uvx", "check-wheel-contents", *wheels], "check-wheel-contents")
            )

        for argv, label in commands:
            result = _run_tool(argv, project_dir)
            if result is None:
                continue
            if result.returncode != 0:
                detail = (result.stdout or result.stderr).strip()
                return f"{label} rejected the built artifacts:\n{detail}"
    return None


def _run_tool(argv: list[str], project_dir: Path) -> subprocess.CompletedProcess | None:
    """Run a build-time tool, tolerating its absence.

    Args:
        argv: Command to run.
        project_dir: Directory to run it in.

    Returns:
        The completed process, or None when the tool could not be run at all --
        no uv, no network to fetch it, or it took too long. Treated the same
        way as the remote-tag query: an unanswerable question does not block.
    """
    try:
        return subprocess.run(
            argv,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
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

    # Before the tag gate, because everything past it is either irreversible or
    # a question put to the user: a slow gate placed later wastes their answers
    # and, worse, discovers a bad artifact only after the tag exists.
    console.print("Building and checking the distributions...")
    artifact_error = _artifact_error(project_dir)
    if artifact_error:
        console.print(f"[red]{artifact_error}[/red]")
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

    bumps = _version_bumps(project_dir, version)

    if dry_run:
        console.print("\n[yellow]DRY RUN — would perform:[/yellow]")
        step = 1
        if rename_unreleased:
            console.print(
                f"  {step}. Rename [Unreleased] to [{version}] - {today} in "
                "CHANGELOG.md"
            )
            step += 1
        for bump in bumps:
            console.print(
                f"  {step}. Set version to {version} in {bump.rel} "
                f"(currently {bump.current})"
            )
            step += 1
        if rename_unreleased or bumps:
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

    bumps = [
        bump
        for bump in bumps
        if Confirm.ask(
            f"{bump.rel} records {bump.current}. Set it to {version}?",
            default=True,
        )
    ]

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
    for bump in bumps:
        VERSION_WRITERS[bump.rel](bump.path, version)
        release_paths.append(bump.rel)
        console.print(f"Set {bump.rel} version to {version}")

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
