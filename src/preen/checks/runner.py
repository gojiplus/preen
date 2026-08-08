"""Check runner implementation."""

import time
from pathlib import Path

from .base import Check, CheckResult


def run_checks(
    project_dir: Path,
    check_classes: list[type[Check]],
    skip: list[str] | None = None,
    only: list[str] | None = None,
) -> dict[str, CheckResult]:
    """Run multiple checks and return their results.

    Args:
        project_dir: Path to the project directory.
        check_classes: List of Check classes to instantiate and run.
        skip: List of check names to skip.
        only: List of check names to run exclusively.

    Returns:
        Dictionary mapping check names to their results.

    Raises:
        ValueError: If ``skip`` or ``only`` names a check that does not exist.
    """
    results = {}
    skip = skip or []

    checks = [check_class(project_dir) for check_class in check_classes]
    available = {check.name for check in checks}

    # A name matching nothing used to filter silently, so `--only ruff,tests` --
    # the obvious way to write it, and the way the help text reads -- selected
    # zero checks and printed "All checks passed" over an empty table. A
    # conformance tool reporting a pass it never established is worse than one
    # that refuses.
    unknown = sorted({*skip, *(only or [])} - available)
    if unknown:
        raise ValueError(
            f"Unknown check(s): {', '.join(unknown)}. "
            f"Available checks: {', '.join(sorted(available))}"
        )

    for check in checks:
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
