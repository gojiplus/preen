"""Check framework for preen.

This module provides the base infrastructure for running checks and the
registry of all built-in checks.
"""

from .base import Check, CheckResult, Fix, Impact, Issue, Severity
from .ci_matrix import CIMatrixCheck
from .citation import CitationCheck
from .codespell import CodespellCheck
from .deps import DepsCheck
from .deptree import DeptreeCheck
from .links import LinkCheck
from .pydoclint import PydoclintCheck
from .pyright import PyrightCheck
from .ruff import RuffCheck
from .runner import run_checks
from .structure import StructureCheck
from .template import TemplateCheck
from .tests import TestsCheck
from .version import VersionCheck

ALL_CHECKS: list[type[Check]] = [
    TemplateCheck,
    RuffCheck,
    TestsCheck,
    CitationCheck,
    DepsCheck,
    DeptreeCheck,
    CIMatrixCheck,
    StructureCheck,
    VersionCheck,
    LinkCheck,
    PydoclintCheck,
    PyrightCheck,
    CodespellCheck,
]

__all__ = [
    "ALL_CHECKS",
    "Check",
    "CheckResult",
    "Fix",
    "Impact",
    "Issue",
    "Severity",
    "run_checks",
]
