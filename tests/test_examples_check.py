"""The examples check, and the three false positives it had to survive.

Each of these was found by running the check across all 51 fleet repos before
enabling it, which is the only reason they are not now failing someone's CI.
"""

import pathlib
import textwrap

import pytest

from preen.checks.examples import ExamplesCheck, exported_symbols, referenced_symbols


def _repo(tmp_path, init: str, readme: str, pyproject: str = ""):
    pkg = tmp_path / "src" / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(textwrap.dedent(init))
    (tmp_path / "README.md").write_text(textwrap.dedent(readme))
    (tmp_path / "pyproject.toml").write_text(pyproject or '[project]\nname = "mypkg"\n')
    return tmp_path


def _errors(result):
    return [i for i in result.issues if i.severity.value == "error"]


def test_a_readme_naming_a_missing_symbol_fails(tmp_path):
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            import mypkg
            mypkg.gone()
            ```
        """,
    )
    issues = _errors(ExamplesCheck(repo).run())
    assert len(issues) == 1
    assert "mypkg.gone" in issues[0].description


def test_a_readme_naming_only_real_symbols_passes(tmp_path):
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            import mypkg
            mypkg.real()
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_an_alias_imported_once_is_understood_in_later_blocks(tmp_path):
    # A README imports the package at the top and uses the alias throughout.
    # Reading aliases per block found one symbol out of thirteen in batchlane.
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            import mypkg as mp
            ```

            Some prose between the blocks.

            ```python
            mp.gone()
            ```
        """,
    )
    assert "mypkg.gone" in _errors(ExamplesCheck(repo).run())[0].description


# --- the three false positives, each verified against a real fleet repo ---


def test_a_name_bound_locally_is_not_the_package(tmp_path):
    # layoutlens documents a pytest fixture called `layoutlens`, so
    # `layoutlens.assert_ui(...)` is a fixture method. Reading it as a package
    # attribute reported three bugs that did not exist.
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            def test_something(mypkg):
                mypkg.assert_thing("x")
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_a_dunder_is_not_package_api(tmp_path):
    # incline exports __version__ from a try/except and declares __all__.
    # __all__ governs star-imports, not attribute access.
    repo = _repo(
        tmp_path,
        init="""
            from importlib.metadata import version

            try:
                __version__ = version("mypkg")
            except Exception:
                __version__ = "0.0.0"

            __all__ = ["real"]

            def real(): ...
        """,
        readme="""
            ```python
            import mypkg
            print(mypkg.__version__)
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_a_module_dunder_is_never_flagged(tmp_path):
    # __doc__, __name__ and __file__ exist on every module and are declared in
    # no package. Without the dunder guard the first README to print one gets
    # reported as a missing symbol. The __version__ case does not test this:
    # that name is declared, so the try-descent fix already covers it.
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            import mypkg
            print(mypkg.__doc__)
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_a_name_defined_inside_a_try_still_counts(tmp_path):
    repo = _repo(
        tmp_path,
        init="""
            try:
                from .fast import go
            except ImportError:
                from .slow import go
        """,
        readme="""
            ```python
            import mypkg
            mypkg.go()
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


# --- the executing tier ---


def test_doctests_do_not_run_unless_a_repo_asks(tmp_path):
    # Measured across 51 repos, the only doctest failure was a README whose
    # examples are illustrative. Executing by default would fail exactly the
    # repos this tier exists to serve.
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            >>> 1 + 1
            9999
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_an_unparseable_fragment_is_ignored_rather_than_failing(tmp_path):
    # READMEs are full of illustrative fragments. They are not this check's
    # business, and treating them as programs is the false-positive flood.
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            def incomplete(
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_a_repo_with_no_single_package_is_skipped(tmp_path):
    (tmp_path / "README.md").write_text("# nothing here")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    assert ExamplesCheck(tmp_path).run().passed


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("__all__ = ['a', 'b']\n", {"a", "b"}),
        ("def f(): ...\nclass C: ...\n", {"f", "C"}),
        ("from .x import y\n", {"y"}),
        ("if True:\n    def g(): ...\n", {"g"}),
    ],
)
def test_exported_symbols_reads_what_a_package_defines(tmp_path, source, expected):
    init = tmp_path / "__init__.py"
    init.write_text(source)
    assert expected <= (exported_symbols(init) or set())


def test_referenced_symbols_finds_both_attribute_and_from_import():
    text = "```python\nfrom mypkg import a\nimport mypkg\nmypkg.b()\n```"
    assert referenced_symbols(text, "mypkg") == {"a", "b"}


# The findings below came from two independent reviews of the 0.6.0 release
# diff. Each test failed before its fix.


def test_a_submodule_import_is_not_a_missing_symbol(tmp_path):
    # `from mypkg import config` loads mypkg/config.py without __init__ naming
    # it. Reading only __init__ reported every such import as missing.
    repo = _repo(tmp_path, init="", readme="```python\nfrom mypkg import config\n```")
    (tmp_path / "src" / "mypkg" / "config.py").write_text("X = 1\n")
    sub = tmp_path / "src" / "mypkg" / "sub"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    (tmp_path / "README.md").write_text(
        "```python\nfrom mypkg import config, sub\nimport mypkg\nmypkg.config.X\n```"
    )
    assert ExamplesCheck(repo).run().passed


def test_a_relative_star_import_is_resolved(tmp_path):
    repo = _repo(
        tmp_path,
        init="from .api import *\n",
        readme="```python\nimport mypkg\nmypkg.public()\n```",
    )
    (tmp_path / "src" / "mypkg" / "api.py").write_text("def public(): ...\n")
    assert ExamplesCheck(repo).run().passed


def test_an_unresolvable_star_import_means_exports_are_unknown(tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text("from somewhere_else import *\n")
    assert exported_symbols(init) is None


def test_a_name_bound_by_unpacking_is_not_the_package(tmp_path):
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            import mypkg
            first, mypkg = 1, object()
            mypkg.not_ours()
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_a_name_bound_by_a_local_import_is_not_the_package(tmp_path):
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            import somelib as mypkg
            mypkg.not_ours()
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_exported_symbols_sees_unpacked_assignments(tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text('VERSION, AUTHOR = ("1.0", "who")\n')
    assert {"VERSION", "AUTHOR"} <= (exported_symbols(init) or set())


def test_a_prompt_inside_a_comment_does_not_hide_the_block():
    text = "```python\n# the prompt is >>>\nimport mypkg\nmypkg.gone()\n```"
    assert referenced_symbols(text, "mypkg") == {"gone"}


def _doctest_repo(tmp_path, readme: str, init: str = "def real(): ...\n"):
    """A repo that opted into doctests, with a .venv pointing at this python."""
    import sys

    repo = _repo(
        tmp_path,
        init=init,
        readme=readme,
        pyproject='[project]\nname = "mypkg"\n\n[tool.preen]\nrun_doctests = true\n',
    )
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(sys.executable)
    return repo


def test_a_closing_fence_is_not_expected_output(tmp_path):
    # doctest reads expected output until a blank line or the next prompt, so
    # a fence right after the output became part of what it expected.
    repo = _doctest_repo(tmp_path, "```python\n>>> 1 + 1\n2\n```\n")
    assert ExamplesCheck(repo).run().passed


def test_a_failing_doctest_still_fails(tmp_path):
    repo = _doctest_repo(tmp_path, "```python\n>>> 1 + 1\n3\n```\n")
    assert not ExamplesCheck(repo).run().passed


def test_doctests_run_from_a_relative_project_path(tmp_path, monkeypatch):
    _doctest_repo(tmp_path, "```python\n>>> 1 + 1\n3\n```\n")
    monkeypatch.chdir(tmp_path.parent)
    result = ExamplesCheck(pathlib.Path(tmp_path.name)).run()
    assert not result.passed
    assert "no longer reproduces" in result.issues[0].description


def test_doctests_run_even_without_a_single_package(tmp_path):
    # The static tier needs one package to compare against; execution does not.
    _doctest_repo(tmp_path, "```python\n>>> 1 + 1\n3\n```\n")
    (tmp_path / "src" / "other").mkdir()
    (tmp_path / "src" / "other" / "__init__.py").write_text("")
    assert not ExamplesCheck(tmp_path).run().passed


def test_a_hanging_doctest_is_a_finding_not_a_crash(tmp_path, monkeypatch):
    import subprocess

    from preen.checks import examples

    monkeypatch.setattr(examples, "DOCTEST_TIMEOUT", 0.01)
    repo = _doctest_repo(tmp_path, "```python\n>>> import time; time.sleep(5)\n\n```\n")
    result = ExamplesCheck(repo).run()
    assert not result.passed
    assert "did not finish" in result.issues[0].description
    assert subprocess.TimeoutExpired  # the type the check must catch
