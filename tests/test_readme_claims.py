"""preen's README describes preen, so the code is the source of truth for it.

The check list in the README fell one behind the registry when `pytest-config`
was wired in: 24 checks registered, 23 named. Nothing caught it, because
nothing compared the two. preen checks other repos' documentation for exactly
this class of drift, so it should hold itself to the same rule.
"""

import pathlib

from preen.checks import ALL_CHECKS
from preen.config import PreenConfig

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"
TEXT = " ".join(README.read_text().split())


def test_every_registered_check_is_named_in_the_readme():
    here = pathlib.Path()
    missing = sorted(c(here).name for c in ALL_CHECKS if c(here).name not in TEXT)
    assert not missing, (
        f"README does not mention {missing}. Add them to the `preen check runs:` "
        f"list, or the README undersells what the tool does."
    )


def test_every_tool_preen_config_field_is_documented():
    # A real field nobody knows about is a field nobody uses.
    for field_name in PreenConfig.__dataclass_fields__:
        assert field_name in TEXT, (
            f"[tool.preen] accepts {field_name!r} but the README's Configuration "
            f"section does not mention it."
        )
