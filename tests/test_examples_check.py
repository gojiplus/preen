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


def test_a_star_import_cycle_is_unknown_not_a_crash(tmp_path):
    # `from .api import *` in __init__ and `from . import *` in api.py is a
    # working package; following the stars forever was a RecursionError.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .api import *\n")
    (pkg / "api.py").write_text("from . import *\ndef public(): ...\n")
    assert exported_symbols(pkg / "__init__.py") is None


def test_a_module_getattr_makes_exports_unknown(tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text("def __getattr__(name):\n    return name\n")
    assert exported_symbols(init) is None


def test_an_alias_rebound_to_a_submodule_is_not_the_package(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            import mypkg as mp
            ```
            ```python
            from mypkg import client as mp
            mp.request()
            ```
            ```python
            import mypkg.client as mp2
            mp2.request()
            ```
        """,
    )
    (tmp_path / "src" / "mypkg" / "client.py").write_text("def request(): ...\n")
    assert ExamplesCheck(repo).run().passed


def test_importing_a_submodule_keeps_the_package_name_live(tmp_path):
    repo = _repo(
        tmp_path, init="", readme="```python\nimport mypkg.sub\nmypkg.gone\n```"
    )
    (tmp_path / "src" / "mypkg" / "sub.py").write_text("")
    assert not ExamplesCheck(repo).run().passed


def test_a_windows_style_venv_is_found(tmp_path):
    import sys

    repo = _repo(
        tmp_path,
        init="",
        readme="```python\n>>> 1 + 1\n3\n```\n",
        pyproject='[project]\nname = "mypkg"\n\n[tool.preen]\nrun_doctests = true\n',
    )
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").symlink_to(sys.executable)
    result = ExamplesCheck(repo).run()
    assert not result.passed
    assert "no longer reproduces" in result.issues[0].description


def test_a_local_class_or_function_named_like_the_package_is_not_it(tmp_path):
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            import mypkg

            class mypkg:
                fake = 1

            mypkg.fake
            ```
            ```python
            def mypkg(): ...
            mypkg.other
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_a_missing_venv_is_informational_not_a_failure(tmp_path):
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="```python\n>>> 1 + 1\n2\n```\n",
        pyproject='[project]\nname = "mypkg"\n\n[tool.preen]\nrun_doctests = true\n',
    )
    result = ExamplesCheck(repo).run()
    assert result.passed
    assert [i.severity.value for i in result.issues] == ["info"]


def test_an_alias_rebinding_carries_into_later_blocks(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            import mypkg as mp
            ```
            ```python
            from mypkg import client as mp
            ```
            ```python
            mp.request()
            ```
        """,
    )
    (tmp_path / "src" / "mypkg" / "client.py").write_text("def request(): ...\n")
    assert ExamplesCheck(repo).run().passed


def test_an_alias_reimported_later_is_the_package_again(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            from mypkg import client as mp
            ```
            ```python
            import mypkg as mp
            mp.gone()
            ```
        """,
    )
    (tmp_path / "src" / "mypkg" / "client.py").write_text("")
    assert not ExamplesCheck(repo).run().passed


def test_an_indented_block_is_still_read(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="1. Try it:\n\n   ```python\n   import mypkg\n   mypkg.gone()\n   ```\n",
    )
    assert not ExamplesCheck(repo).run().passed


def test_an_indented_fence_is_not_expected_output(tmp_path):
    repo = _doctest_repo(
        tmp_path, "1. Try it:\n\n   ```python\n   >>> 1 + 1\n   2\n   ```\n"
    )
    assert ExamplesCheck(repo).run().passed


def test_a_type_alias_is_an_export(tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text("type Item = str\n")
    assert {"Item"} <= (exported_symbols(init) or set())


def test_assigning_an_attribute_is_not_reaching_for_it():
    text = "```python\nimport mypkg\nmypkg.callback = lambda: 42\nmypkg.real()\n```"
    assert referenced_symbols(text, "mypkg") == {"real"}


@pytest.mark.parametrize(
    "block",
    [
        "async def f():\n    async with thing() as mypkg:\n        mypkg.x()\n",
        "try:\n    pass\nexcept Exception as mypkg:\n    mypkg.x()\n",
        "f = lambda mypkg: mypkg.x()\n",
        "match obj:\n    case [mypkg]:\n        mypkg.x()\n",
        "match obj:\n    case {'k': mypkg}:\n        mypkg.x()\n",
        "match obj:\n    case [*mypkg]:\n        mypkg.x()\n",
        "match obj:\n    case {**mypkg}:\n        mypkg.x()\n",
    ],
)
def test_every_binding_form_shadows_the_package(block):
    assert referenced_symbols(f"```python\n{block}```", "mypkg") == set()


def test_a_rebinding_in_the_importing_block_still_carries_forward(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            import mypkg as mp
            from mypkg import client as mp
            ```
            ```python
            mp.request()
            ```
        """,
    )
    (tmp_path / "src" / "mypkg" / "client.py").write_text("def request(): ...\n")
    assert ExamplesCheck(repo).run().passed


def test_a_star_import_keeps_an_underscore_name_that_all_exports(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .api import *\n")
    (pkg / "api.py").write_text(
        "__all__ = ['_public']\ndef _public(): ...\ndef _private(): ...\n"
    )
    names = exported_symbols(pkg / "__init__.py") or set()
    assert "_public" in names
    assert "_private" not in names


def test_exports_inside_a_module_level_with_count(tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text(
        "from contextlib import suppress\n"
        "with suppress(ImportError):\n"
        "    from math import sqrt\n"
    )
    assert {"sqrt"} <= (exported_symbols(init) or set())


def test_a_namespace_subpackage_is_an_importable_child(tmp_path):
    repo = _repo(tmp_path, init="", readme="```python\nfrom mypkg import plugins\n```")
    (tmp_path / "src" / "mypkg" / "plugins").mkdir()
    (tmp_path / "src" / "mypkg" / "plugins" / "a.py").write_text("")
    assert ExamplesCheck(repo).run().passed


@pytest.mark.parametrize(
    "block",
    ["f = lambda *mypkg: mypkg.count(1)\n", "f = lambda **mypkg: mypkg.get('o')\n"],
)
def test_variadic_lambda_parameters_shadow_the_package(block):
    assert referenced_symbols(f"```python\n{block}```", "mypkg") == set()


def test_a_type_alias_in_an_example_shadows_the_package():
    text = "```python\nimport mypkg\ntype mypkg = list[str]\nmypkg.x\n```"
    assert referenced_symbols(text, "mypkg") == set()


def test_an_attribute_the_example_creates_may_be_used_later(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            import mypkg
            mypkg.callback = lambda: 42
            ```
            ```python
            mypkg.callback()
            mypkg.gone()
            ```
        """,
    )
    issues = _errors(ExamplesCheck(repo).run())
    assert [i.description for i in issues] == [
        "README.md shows `mypkg.gone`, which the package does not define"
    ]


@pytest.mark.parametrize(
    "source",
    [
        "import sys\nmatch sys.platform:\n    case 'win32':\n        pass\n"
        "    case _:\n        from math import sqrt\n",
        "try:\n    from math import sqrt\nexcept* ImportError:\n    pass\n",
        "for _ in range(1):\n    from math import sqrt\n",
        "while False:\n    pass\nelse:\n    from math import sqrt\n",
    ],
)
def test_exports_inside_any_module_level_suite_count(tmp_path, source):
    init = tmp_path / "__init__.py"
    init.write_text(source)
    assert {"sqrt"} <= (exported_symbols(init) or set())


@pytest.mark.parametrize(
    "source",
    [
        "from contextlib import nullcontext\nwith nullcontext(1) as value:\n    pass\n",
        "for value in [1]:\n    pass\n",
        "match 1:\n    case value:\n        pass\n",
        "match [1]:\n    case [*value]:\n        pass\n",
        "if (value := 1):\n    pass\n",
    ],
)
def test_a_name_a_compound_statement_binds_is_an_export(tmp_path, source):
    init = tmp_path / "__init__.py"
    init.write_text(source)
    assert {"value"} <= (exported_symbols(init) or set())


def test_a_walrus_inside_a_function_is_not_an_export(tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text("def f():\n    return (value := 1)\n")
    assert "value" not in (exported_symbols(init) or set())


def test_a_parameter_in_one_block_does_not_retire_the_package_for_the_next(tmp_path):
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            def test_fixture(mypkg):
                mypkg.assert_ok()
            ```
            ```python
            mypkg.does_not_exist()
            ```
        """,
    )
    issues = _errors(ExamplesCheck(repo).run())
    assert [i.description for i in issues] == [
        "README.md shows `mypkg.does_not_exist`, which the package does not define"
    ]


def test_an_annotated_all_declares_star_exports(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .api import *\n")
    (pkg / "api.py").write_text(
        "__all__: list[str] = ['_public']\ndef _public(): ...\n"
    )
    assert "_public" in (exported_symbols(pkg / "__init__.py") or set())


def test_a_comprehension_variable_does_not_retire_the_package(tmp_path):
    # A comprehension is its own scope; its loop variable never escapes.
    repo = _repo(
        tmp_path,
        init="def real(): ...\n",
        readme="""
            ```python
            import mypkg
            [mypkg for mypkg in (1, 2)]
            ```
            ```python
            mypkg.gone()
            ```
        """,
    )
    assert [i.description for i in _errors(ExamplesCheck(repo).run())] == [
        "README.md shows `mypkg.gone`, which the package does not define"
    ]


def test_a_build_directory_above_the_repo_does_not_hide_docs(tmp_path):
    # Only docs/**/_build is generated output; the repo's own path is not.
    root = tmp_path / "_build" / "repo"
    root.mkdir(parents=True)
    repo = _repo(root, init="", readme="# nothing\n")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text(
        "```python\nimport mypkg\nmypkg.gone()\n```"
    )
    assert not ExamplesCheck(repo).run().passed


def test_a_vendored_readme_under_docs_is_not_the_repo_s_documentation(tmp_path):
    # docs/.venv or docs/node_modules hold other people's READMEs.
    repo = _repo(tmp_path, init="", readme="# nothing\n")
    vendored = tmp_path / "docs" / ".venv" / "lib" / "dep"
    vendored.mkdir(parents=True)
    (vendored / "README.md").write_text("```python\nimport mypkg\nmypkg.gone()\n```")
    assert ExamplesCheck(repo).run().passed


def test_importing_a_submodule_revives_the_package_name(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            mypkg = 1
            ```
            ```python
            import mypkg.cli
            mypkg.gone
            ```
        """,
    )
    (tmp_path / "src" / "mypkg" / "cli.py").write_text("")
    assert not ExamplesCheck(repo).run().passed


def test_a_from_import_of_a_missing_submodule_is_reported(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="```python\nfrom mypkg.does_not_exist import anything\n```",
    )
    assert [i.description for i in _errors(ExamplesCheck(repo).run())] == [
        "README.md shows `mypkg.does_not_exist`, which the package does not define"
    ]


def test_a_function_local_import_does_not_leak_into_later_blocks(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            from mypkg import client as mp
            ```
            ```python
            def helper():
                import mypkg as mp
                return mp
            ```
            ```python
            mp.request()
            ```
        """,
    )
    (tmp_path / "src" / "mypkg" / "client.py").write_text("def request(): ...\n")
    assert ExamplesCheck(repo).run().passed


@pytest.mark.parametrize(
    "block", ["import mypkg.removed\n", "import mypkg.removed as old\n"]
)
def test_a_dotted_import_of_a_missing_submodule_is_reported(tmp_path, block):
    repo = _repo(tmp_path, init="", readme=f"```python\n{block}```")
    assert [i.description for i in _errors(ExamplesCheck(repo).run())] == [
        "README.md shows `mypkg.removed`, which the package does not define"
    ]


def test_a_tilde_fenced_block_is_read(tmp_path):
    repo = _repo(
        tmp_path, init="", readme="~~~python\nimport mypkg\nmypkg.gone()\n~~~\n"
    )
    assert not ExamplesCheck(repo).run().passed


def test_a_tilde_fence_is_not_expected_output(tmp_path):
    repo = _doctest_repo(tmp_path, "~~~python\n>>> 1 + 1\n2\n~~~\n")
    assert ExamplesCheck(repo).run().passed


def test_a_function_local_import_does_not_alias_the_rest_of_its_block(tmp_path):
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            from mypkg import client as mp
            ```
            ```python
            def helper():
                import mypkg as mp
                return mp

            mp.request()
            ```
        """,
    )
    (tmp_path / "src" / "mypkg" / "client.py").write_text("def request(): ...\n")
    assert ExamplesCheck(repo).run().passed


def test_a_walrus_inside_a_comprehension_binds_the_block(tmp_path):
    # The loop variable is the comprehension's own; a walrus target is not.
    repo = _repo(
        tmp_path,
        init="",
        readme="""
            ```python
            import mypkg as mp
            ```
            ```python
            [(mp := value) for value in ["text"]]
            ```
            ```python
            mp.upper()
            ```
        """,
    )
    assert ExamplesCheck(repo).run().passed


def test_a_star_import_honors_the_target_s_all(tmp_path):
    # Python brings in only what __all__ lists; so does the check.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .sub import *\n")
    (pkg / "sub.py").write_text("__all__ = ['foo']\nfoo = 1\nbar = 2\n")
    names = exported_symbols(pkg / "__init__.py") or set()
    assert "foo" in names
    assert "bar" not in names


def test_only_the_block_s_own_fences_are_blanked_for_doctest(tmp_path):
    # An expected-output line that happens to look like a fence is output.
    repo = _doctest_repo(tmp_path, '~~~pycon\n>>> print("```")\n```\n~~~\n')
    assert ExamplesCheck(repo).run().passed


def test_an_extended_all_is_not_exhaustive(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .core import *\n")
    (pkg / "core.py").write_text(
        "__all__ = ['first']\n__all__ += ['second']\n"
        "def first(): ...\ndef second(): ...\n"
    )
    names = exported_symbols(pkg / "__init__.py") or set()
    assert {"first", "second"} <= names
