"""Validate packaged runtime data and model assets."""

import ast
import re
import tomllib
from pathlib import Path

from .base import Check, CheckResult, Impact, Issue, Severity

TABULAR_SUFFIXES = (
    ".csv",
    ".csv.gz",
    ".csv.bz2",
    ".csv.zip",
    ".tsv",
    ".tsv.gz",
)
MODEL_SUFFIXES = (
    ".ckpt",
    ".h5",
    ".joblib",
    ".keras",
    ".onnx",
    ".pickle",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
    ".sav",
)
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip")
FULL_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
HUB_DOWNLOAD_CALLS = frozenset({"hf_hub_download", "snapshot_download"})
REMOTE_CALLS = HUB_DOWNLOAD_CALLS | {"from_pretrained"}


class RuntimeAssetsCheck(Check):
    """Check that packaged assets are typed, inspectable, and reproducible."""

    @property
    def name(self) -> str:
        """Return the check name."""
        return "runtime-assets"

    @property
    def description(self) -> str:
        """Return a short description of the check."""
        return "Check packaged tables, model files, and Hugging Face revisions"

    def _package_roots(self) -> list[Path]:
        """Locate import-package directories.

        Returns:
            Package roots for src and flat layouts.
        """
        src = self.project_dir / "src"
        if src.is_dir():
            return sorted(
                path
                for path in src.iterdir()
                if path.is_dir()
                and ((path / "__init__.py").exists() or (path / "py.typed").exists())
            )

        pyproject = self.project_dir / "pyproject.toml"
        if not pyproject.exists():
            return []
        try:
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get(
                "project", {}
            )
        except (OSError, tomllib.TOMLDecodeError):
            return []
        package_name = str(project.get("name", "")).replace("-", "_")
        candidate = self.project_dir / package_name
        return [candidate] if candidate.is_dir() else []

    def _files(self) -> list[Path]:
        """Return files under the import packages.

        Returns:
            Paths relative to the project root.
        """
        files: list[Path] = []
        for root in self._package_roots():
            files.extend(
                path.relative_to(self.project_dir)
                for path in root.rglob("*")
                if path.is_file() and not self.is_excluded(path)
            )
        return sorted(files)

    def _format_issues(self, files: list[Path]) -> list[Issue]:
        """Find opaque tabular and local model artifacts.

        Args:
            files: Package-relative file paths.

        Returns:
            One issue per invalid artifact.
        """
        issues = []
        for path in files:
            lower_name = path.name.lower()
            if lower_name.endswith(TABULAR_SUFFIXES):
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=(
                            "Packaged runtime table uses CSV or TSV. Use typed "
                            "Parquet for tabular data, or Protobuf for structured "
                            "records."
                        ),
                        file=path,
                        impact=Impact.CRITICAL,
                    )
                )
            elif lower_name.endswith(MODEL_SUFFIXES):
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=(
                            "Serialized model is stored in the Python package. "
                            "Publish it on Hugging Face and download a pinned revision."
                        ),
                        file=path,
                        impact=Impact.CRITICAL,
                    )
                )
            elif lower_name.endswith(ARCHIVE_SUFFIXES):
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=(
                            "Opaque archive is stored inside the Python package. "
                            "Ship schema-bearing resources directly."
                        ),
                        file=path,
                        impact=Impact.CRITICAL,
                    )
                )
        return issues

    def _revision_issues(self, files: list[Path]) -> list[Issue]:
        """Validate explicit remote Hugging Face calls.

        Args:
            files: Package-relative file paths.

        Returns:
            Issues for missing or mutable Hugging Face revisions.
        """
        issues = []
        for path in (path for path in files if path.suffix == ".py"):
            absolute = self.project_dir / path
            try:
                source = absolute.read_text(encoding="utf-8")
            except OSError:
                continue
            if not any(marker in source for marker in REMOTE_CALLS):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                call_name = self._call_name(call)
                if call_name not in REMOTE_CALLS:
                    continue
                if call_name == "from_pretrained" and not self._literal_hub_target(
                    call
                ):
                    continue
                revision = next(
                    (
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg == "revision"
                    ),
                    None,
                )
                if revision is None:
                    issues.append(self._missing_revision_issue(path, call.lineno))
                elif isinstance(revision, ast.Constant) and (
                    not isinstance(revision.value, str)
                    or not FULL_COMMIT_SHA.fullmatch(revision.value)
                ):
                    issues.append(
                        self._mutable_revision_issue(path, call.lineno, revision.value)
                    )
        return issues

    @staticmethod
    def _call_name(call: ast.Call) -> str:
        """Return the final name of a called function.

        Args:
            call: Parsed call expression.

        Returns:
            Function or method name.
        """
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return ""

    @staticmethod
    def _literal_hub_target(call: ast.Call) -> bool:
        """Return whether a from_pretrained call names a remote repository.

        Variable targets may resolve to local directories or to controlled overrides,
        so this check leaves them to the package's contract tests.

        Args:
            call: Parsed from_pretrained call.

        Returns:
            True for a literal ``owner/repository`` target.
        """
        target = call.args[0] if call.args else None
        if target is None:
            target = next(
                (
                    keyword.value
                    for keyword in call.keywords
                    if keyword.arg in {"pretrained_model_name_or_path", "repo_id"}
                ),
                None,
            )
        return (
            isinstance(target, ast.Constant)
            and isinstance(target.value, str)
            and "/" in target.value
        )

    def _missing_revision_issue(self, path: Path, line: int) -> Issue:
        """Build an issue for an unpinned remote call.

        Args:
            path: Source file containing the call.
            line: Call line number.

        Returns:
            Blocking revision issue.
        """
        return Issue(
            check=self.name,
            severity=Severity.ERROR,
            description=(
                "Remote Hugging Face call has no revision. Use the full "
                "40-character commit SHA."
            ),
            file=path,
            line=line,
            impact=Impact.CRITICAL,
        )

    def _mutable_revision_issue(self, path: Path, line: int, revision: object) -> Issue:
        """Build an issue for a literal mutable revision.

        Args:
            path: Source file containing the call.
            line: Call line number.
            revision: Literal revision value.

        Returns:
            Blocking revision issue.
        """
        return Issue(
            check=self.name,
            severity=Severity.ERROR,
            description=(
                f"Hugging Face revision {revision!r} is mutable or abbreviated. "
                "Use the full 40-character commit SHA."
            ),
            file=path,
            line=line,
            impact=Impact.CRITICAL,
        )

    def run(self) -> CheckResult:
        """Run the runtime asset checks.

        Returns:
            Check result with one issue per invalid asset or revision.
        """
        files = self._files()
        issues = [*self._format_issues(files), *self._revision_issues(files)]
        return CheckResult(check=self.name, passed=not issues, issues=issues)
