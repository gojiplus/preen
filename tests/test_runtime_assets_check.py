"""Tests for packaged runtime asset validation."""

from pathlib import Path

from preen.checks.runtime_assets import RuntimeAssetsCheck


def _package(project: Path, name: str = "demo") -> Path:
    """Create a minimal src-layout package.

    Args:
        project: Temporary project root.
        name: Import package name.

    Returns:
        Created package directory.
    """
    package = project / "src" / name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    return package


def test_parquet_and_protobuf_runtime_data_pass(tmp_path: Path) -> None:
    """Schema-bearing runtime formats are accepted."""
    package = _package(tmp_path)
    (package / "lookup.parquet").write_bytes(b"PAR1")
    (package / "records.pb").write_bytes(b"schema-bound")

    assert RuntimeAssetsCheck(tmp_path).run().passed


def test_packaged_csv_and_model_files_are_blocking(tmp_path: Path) -> None:
    """Opaque runtime tables and local model weights are rejected."""
    package = _package(tmp_path)
    (package / "lookup.csv.gz").write_bytes(b"opaque")
    (package / "classifier.joblib").write_bytes(b"opaque")
    (package / "lookup.csv.tar.gz").write_bytes(b"opaque")

    result = RuntimeAssetsCheck(tmp_path).run()

    assert not result.passed
    assert len(result.issues) == 3
    assert all(issue.is_blocking() for issue in result.issues)


def test_csv_fixtures_outside_package_are_not_runtime_assets(tmp_path: Path) -> None:
    """Tests and user-facing interchange fixtures remain valid CSV."""
    _package(tmp_path)
    fixtures = tmp_path / "tests"
    fixtures.mkdir()
    (fixtures / "input.csv").write_text("name\nAda\n", encoding="utf-8")

    assert RuntimeAssetsCheck(tmp_path).run().passed


def test_full_hugging_face_commit_pin_passes(tmp_path: Path) -> None:
    """A full immutable revision satisfies the download contract."""
    package = _package(tmp_path)
    (package / "_resources.py").write_text(
        "from huggingface_hub import hf_hub_download\n"
        f'REVISION = "{"a" * 40}"\n'
        'hf_hub_download("org/model", "model.pt", revision=REVISION)\n',
        encoding="utf-8",
    )

    assert RuntimeAssetsCheck(tmp_path).run().passed


def test_mutable_or_missing_hugging_face_revision_fails(tmp_path: Path) -> None:
    """Hub downloads must not follow branches, tags, or defaults."""
    package = _package(tmp_path)
    (package / "mutable.py").write_text(
        "from huggingface_hub import snapshot_download\n"
        'snapshot_download(repo_id="org/model", revision="main")\n',
        encoding="utf-8",
    )
    (package / "missing.py").write_text(
        'from transformers import AutoModel\nAutoModel.from_pretrained("org/model")\n',
        encoding="utf-8",
    )

    result = RuntimeAssetsCheck(tmp_path).run()

    assert not result.passed
    assert len(result.issues) == 2
    descriptions = [issue.description for issue in result.issues]
    assert any("mutable" in description for description in descriptions)
    assert any("has no revision" in description for description in descriptions)


def test_variable_local_from_pretrained_target_is_not_guessed(tmp_path: Path) -> None:
    """A variable target may be a local directory and is not a remote literal."""
    package = _package(tmp_path)
    (package / "local.py").write_text(
        "from transformers import AutoModel\nAutoModel.from_pretrained(model_dir)\n",
        encoding="utf-8",
    )

    assert RuntimeAssetsCheck(tmp_path).run().passed


def test_flat_layout_package_is_checked(tmp_path: Path) -> None:
    """Legacy flat-layout packages receive the same asset validation."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-package"\n', encoding="utf-8"
    )
    package = tmp_path / "demo_package"
    package.mkdir()
    (package / "lookup.tsv").write_text("key\tvalue\n", encoding="utf-8")

    result = RuntimeAssetsCheck(tmp_path).run()

    assert not result.passed
    assert result.issues[0].file == Path("demo_package/lookup.tsv")
