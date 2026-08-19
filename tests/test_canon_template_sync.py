"""Drift alarm: preen's canon [tool.*] config must match py-canon's template.

The canonical tool configuration lives in three places that nothing else keeps
in sync: py-canon's ``template/pyproject.toml.jinja`` (source of truth for new
repos), ``preen.adopt.CANON_TOOL_TOML`` (source of truth for retrofits), and
py-canon's own ``pyproject.toml``. This test compares the first two so a
change to either side fails preen's CI until both agree.
"""

import tomllib
import urllib.error
import urllib.request

import pytest

from preen.adopt import CANON_TOOL_TOML

TEMPLATE_URL = (
    "https://raw.githubusercontent.com/gojiplus/py-canon/main/"
    "template/pyproject.toml.jinja"
)

SYNCED_TABLES = ("ruff", "pyright", "pydoclint")

# `adopt` derives ruff's target-version from each repo's own requires-python
# floor (see `_target_version`), so canon's value is a template default rather
# than a constant the two copies must agree on. Comparing it would fail every
# time the fleet floor moves, for no drift.
DERIVED_KEYS = {"ruff": ("target-version",)}


def _fetch_template() -> str:
    try:
        with urllib.request.urlopen(TEMPLATE_URL, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as exc:
        pytest.skip(f"py-canon template unreachable: {exc}")


def test_canon_tool_toml_matches_template() -> None:
    text = _fetch_template()
    start = text.find("[tool.ruff]")
    assert start != -1, "template pyproject has no [tool.ruff] table"
    # Everything from [tool.ruff] on is static TOML (jinja stops earlier).
    template_tools = tomllib.loads(text[start:])["tool"]
    preen_tools = tomllib.loads(CANON_TOOL_TOML)["tool"]

    for table in SYNCED_TABLES:
        ours = dict(preen_tools[table])
        theirs = dict(template_tools[table])
        for key in DERIVED_KEYS.get(table, ()):
            ours.pop(key, None)
            theirs.pop(key, None)
        assert ours == theirs, (
            f"[tool.{table}] differs between preen.adopt.CANON_TOOL_TOML and "
            "py-canon's template/pyproject.toml.jinja — update both together"
        )
