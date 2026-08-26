"""Template adoption and drift check against the py-canon copier template."""

import re
import subprocess

import yaml

from .base import Check, CheckResult, Impact, Issue, Severity

CANON_URL = "https://github.com/gojiplus/py-canon"
ANSWERS_FILE = ".copier-answers.yml"

_VERSION_TAG = re.compile(r"refs/tags/(v\d+(?:\.\d+)*)$")

# Major-only tags like `v1` move with every release; recording one in
# .copier-answers.yml makes `copier update` compare the tag against itself
# and report "already up to date" forever.
_MOVING_TAG = re.compile(r"v\d+")
_CONCRETE_TAG = re.compile(r"v\d+\.\d+\.\d+")

# copier writes `git describe` output when the template checkout is not
# sitting exactly on a tag: v1.2.0-3-gabc1234.
_DESCRIBE_TAG = re.compile(r"v\d+(?:\.\d+)*-\d+-g[0-9a-f]+")


def _version_key(tag: str) -> tuple[int, ...] | None:
    """Parse a v-tag into a comparable tuple.

    Deliberately keeps every component. Truncating to three made
    ``v1.0.1.0.1`` -- a doubled substring replacement that sharepack's
    .copier-answers.yml actually carried -- compare equal to ``v1.0.1``, so the
    corruption passed the drift check and survived until someone read the file
    (issue #55).

    Args:
        tag: A tag like ``v1`` or ``v1.2.0``.

    Returns:
        The numeric components, or None if unparsable.
    """
    match = re.fullmatch(r"v(\d+(?:\.\d+)*)", tag.strip())
    if not match:
        return None
    return tuple(int(p) for p in match.group(1).split("."))


def _pad(key: tuple[int, ...], width: int) -> tuple[int, ...]:
    """Zero-extend a version key so two of different length compare.

    Args:
        key: The version components.
        width: Length to extend to.

    Returns:
        The key, padded with zeros.
    """
    return key + (0,) * (width - len(key))


def _same_version(left: str, right: str) -> bool:
    """Report whether two v-tags name the same release.

    Args:
        left: A tag.
        right: A tag.

    Returns:
        True when both parse and are equal once zero-padded (``v1`` == ``v1.0``).
    """
    left_key, right_key = _version_key(left), _version_key(right)
    if left_key is None or right_key is None:
        return False
    width = max(len(left_key), len(right_key))
    return _pad(left_key, width) == _pad(right_key, width)


def latest_canon_tag(
    url: str = CANON_URL, timeout: float = 10.0, concrete_only: bool = False
) -> str | None:
    """Return the latest ``v*`` tag of the template repo, or None if offline.

    Args:
        url: Git URL of the template repository.
        timeout: Seconds to wait for ``git ls-remote``.
        concrete_only: Only consider full ``vX.Y.Z`` release tags, skipping
            moving major tags like ``v1``.

    Returns:
        The highest version tag (e.g. ``v1.2.0``), or None when the remote
        cannot be reached.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    tags: list[tuple[tuple[int, ...], str]] = []
    for line in result.stdout.splitlines():
        match = _VERSION_TAG.search(line.strip())
        if match:
            tag = match.group(1)
            if concrete_only and not _CONCRETE_TAG.fullmatch(tag):
                continue
            key = _version_key(tag)
            if key is not None:
                tags.append((key, tag))
    if not tags:
        return None
    width = max(len(key) for key, _ in tags)
    return max(tags, key=lambda item: _pad(item[0], width))[1]


class TemplateCheck(Check):
    """Check that the repo is adopted from py-canon and tracks its latest tag."""

    @property
    def name(self) -> str:
        """Return the name of this check."""
        return "template"

    @property
    def description(self) -> str:
        """Return a description of what this check does."""
        return "Check adoption of the py-canon template and template drift"

    def _malformed_commit_issue(self, commit: object) -> Issue | None:
        """Report a ``_commit`` that is not a release tag at all.

        The value must be a ``vX.Y.Z`` release tag, or the moving ``vN`` the
        next branch already reports. Anything else -- extra components from a
        botched string replacement, a git-describe string like
        ``v1.2.0-1-gabc123`` meaning the template checkout was not on a tag, a
        bare commit SHA -- is a record ``copier update`` cannot act on. The
        version parser used to truncate such a value to its first three
        components and compare that, which read ``v1.0.1.0.1`` as ``v1.0.1``
        and let sharepack's corruption pass (issue #55).

        Args:
            commit: The raw ``_commit`` value from .copier-answers.yml.

        Returns:
            The Issue, or None when the value is a tag preen understands.
        """
        if commit is None:
            return None
        text = str(commit).strip()
        if _MOVING_TAG.fullmatch(text) or _CONCRETE_TAG.fullmatch(text):
            return None

        if _DESCRIBE_TAG.fullmatch(text):
            detail = (
                "that is 'git describe' output, so the template was adopted "
                "from a commit that is not a release tag"
            )
        else:
            detail = "expected a vX.Y.Z release tag"

        return Issue(
            check=self.name,
            severity=Severity.ERROR,
            description=(
                f"{ANSWERS_FILE} records a malformed _commit={text!r}: {detail}"
            ),
            impact=Impact.IMPORTANT,
            explanation=(
                "'copier update' resolves this value against py-canon's tags; "
                "one it cannot resolve makes the record useless. Re-run 'preen "
                "adopt' to pin the current release."
            ),
        )

    def run(self) -> CheckResult:
        """Run the template adoption/drift check.

        Returns:
            CheckResult containing any issues found.
        """
        issues: list[Issue] = []
        answers_path = self.project_dir / ANSWERS_FILE

        if not answers_path.exists():
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=(
                        f"No {ANSWERS_FILE} — repo is not adopted from the "
                        "py-canon template"
                    ),
                    impact=Impact.CRITICAL,
                    explanation=(
                        "The fleet standard propagates through the copier "
                        "template; run 'preen adopt' to retrofit this repo."
                    ),
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        try:
            answers = yaml.safe_load(answers_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"{ANSWERS_FILE} is not valid YAML: {exc}",
                    impact=Impact.CRITICAL,
                )
            )
            return CheckResult(check=self.name, passed=False, issues=issues)

        commit = answers.get("_commit")
        malformed = self._malformed_commit_issue(commit)
        if malformed is not None:
            issues.append(malformed)
            return CheckResult(check=self.name, passed=False, issues=issues)

        if isinstance(commit, str) and _MOVING_TAG.fullmatch(commit.strip()):
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=(
                        f"{ANSWERS_FILE} records the moving tag "
                        f"_commit={commit!r} instead of a concrete release tag"
                    ),
                    impact=Impact.IMPORTANT,
                    explanation=(
                        "A moving major tag makes 'copier update' compare the "
                        "tag against itself and no-op forever; re-run 'preen "
                        "adopt' to pin the latest vX.Y.Z release."
                    ),
                )
            )
            blocking = [i for i in issues if i.severity != Severity.INFO]
            return CheckResult(check=self.name, passed=not blocking, issues=issues)

        latest = latest_canon_tag()
        if latest is None:
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=(
                        "Could not reach the py-canon remote; skipping "
                        "template-drift comparison"
                    ),
                    impact=Impact.INFORMATIONAL,
                )
            )
        elif commit != latest and not _same_version(str(commit), latest):
            # Advisory, not blocking. The repo did nothing wrong: the template
            # moved. Gating on this means every py-canon release turns the
            # whole fleet red at once -- v1.1.1 did exactly that -- and the
            # only cure is a PR to every repo before anyone's CI can pass
            # again. Recording a stale-but-concrete tag still lets `copier
            # update` do its job, which is what the record is for.
            issues.append(
                Issue(
                    check=self.name,
                    severity=Severity.INFO,
                    description=(
                        f"Template drift: {ANSWERS_FILE} records "
                        f"_commit={commit!r} but the latest py-canon tag is "
                        f"{latest!r}"
                    ),
                    impact=Impact.INFORMATIONAL,
                    explanation="Run 'preen update' to pull template changes.",
                )
            )

        blocking = [i for i in issues if i.severity != Severity.INFO]
        return CheckResult(check=self.name, passed=not blocking, issues=issues)
