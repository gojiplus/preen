"""The examples check, and the three false positives it had to survive.

Each of these was found by running the check across all 51 fleet repos before
enabling it, which is the only reason they are not now failing someone's CI.
"""

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
