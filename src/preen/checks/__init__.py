"""Check framework for preen.

This module provides the base infrastructure for running checks and the
registry of all built-in checks.
"""

from .audit import AuditCheck
from .base import Check, CheckResult, Fix, Impact, Issue, Severity
from .changelog import ChangelogCheck
from .ci_matrix import CIMatrixCheck
from .citation import CitationCheck
from .codespell import CodespellCheck
from .depgroups import DepgroupsCheck
from .deps import DepsCheck
from .deptree import DeptreeCheck
from .files import RequiredFilesCheck
from .license import LicenseCheck
from .links import LinkCheck
from .metadata import MetadataCheck
from .precommit import PreCommitCheck
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
    ChangelogCheck,
    DepsCheck,
    DeptreeCheck,
    DepgroupsCheck,
    AuditCheck,
    CIMatrixCheck,
    StructureCheck,
    RequiredFilesCheck,
    PreCommitCheck,
    VersionCheck,
    LicenseCheck,
    LinkCheck,
    MetadataCheck,
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
