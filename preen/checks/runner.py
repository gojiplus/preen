"""Check runner implementation."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional, Type

from .base import Check, CheckResult


def run_checks(
    project_dir: Path,
    check_classes: List[Type[Check]],
    skip: Optional[List[str]] = None,
    only: Optional[List[str]] = None,
) -> Dict[str, CheckResult]:
    """Run multiple checks and return their results.

    Args:
        project_dir: Path to the project directory.
        check_classes: List of Check classes to instantiate and run.
        skip: List of check names to skip.
        only: List of check names to run exclusively.

    Returns:
        Dictionary mapping check names to their results.
    """
    results = {}
    skip = skip or []

    for check_class in check_classes:
        check = check_class(project_dir)

        # Skip if in skip list
        if check.name in skip:
            continue

        # Skip if only list is provided and check not in it
        if only and check.name not in only:
            continue

        # Run the check
        start_time = time.time()
        result = check.run()
        result.duration = time.time() - start_time

        results[check.name] = result

    return results
