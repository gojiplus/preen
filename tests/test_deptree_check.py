"""Tests for the circular-import detection check."""

from pathlib import Path

from preen.checks.base import Impact, Severity
from preen.checks.deptree import DeptreeCheck


def test_no_python_files_passes(tmp_path: Path) -> None:
    result = DeptreeCheck(tmp_path).run()
    assert result.passed
    assert result.issues == []


def test_acyclic_imports_pass(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import os\n")
    (tmp_path / "b.py").write_text("import a\n")
    result = DeptreeCheck(tmp_path).run()
    assert result.passed


def test_direct_circular_import_detected(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text("import a\n")
    result = DeptreeCheck(tmp_path).run()
    assert not result.passed
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == Severity.ERROR
    assert issue.impact == Impact.CRITICAL
    assert "a" in issue.description
    assert "b" in issue.description
    assert "Circular import detected" in issue.description


def test_self_referential_module_not_flagged_as_cycle(tmp_path: Path) -> None:
    """A single module with no external imports shouldn't be reported."""
    (tmp_path / "solo.py").write_text("x = 1\n")
    result = DeptreeCheck(tmp_path).run()
    assert result.passed


def test_unparsable_file_skipped_not_crashed(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n")
    (tmp_path / "fine.py").write_text("import os\n")
    result = DeptreeCheck(tmp_path).run()
    assert result.passed


def test_excluded_dirs_ignored(tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "a.py").write_text("import b\n")
    (venv / "b.py").write_text("import a\n")
    result = DeptreeCheck(tmp_path).run()
    assert result.passed


def test_can_fix_false(tmp_path: Path) -> None:
    assert DeptreeCheck(tmp_path).can_fix() is False


# A cycle only fails at import time through imports that run while a module
# loads. An import deferred into a function, or guarded by TYPE_CHECKING, is
# the standard way to break one, so it must not be reported as a cycle.


def test_function_local_import_breaks_cycle(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text("def load():\n    import a\n    return a\n")
    result = DeptreeCheck(tmp_path).run()
    assert result.passed


def test_async_function_and_method_imports_break_cycle(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text(
        "async def load():\n    import a\n\n"
        "class C:\n    def m(self):\n        from a import x\n"
    )
    result = DeptreeCheck(tmp_path).run()
    assert result.passed


def test_type_checking_import_breaks_cycle(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text(
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import a\n"
    )
    result = DeptreeCheck(tmp_path).run()
    assert result.passed


def test_qualified_type_checking_import_breaks_cycle(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text(
        "import typing\n\nif typing.TYPE_CHECKING:\n    import a\n"
    )
    result = DeptreeCheck(tmp_path).run()
    assert result.passed


def test_type_checking_else_branch_still_counts(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text(
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    pass\nelse:\n    import a\n"
    )
    result = DeptreeCheck(tmp_path).run()
    assert not result.passed


def test_class_body_import_still_counts(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text("class C:\n    import a\n")
    result = DeptreeCheck(tmp_path).run()
    assert not result.passed


def test_module_level_try_import_still_counts(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text(
        "try:\n    import a\nexcept ImportError:\n    a = None\n"
    )
    result = DeptreeCheck(tmp_path).run()
    assert not result.passed


def test_type_checking_nested_in_else_breaks_cycle(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text(
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    pass\nelif TYPE_CHECKING:\n    import a\n"
    )
    result = DeptreeCheck(tmp_path).run()
    assert result.passed
