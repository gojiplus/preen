"""Top-level package for preen.

This module exposes a small public API for programmatic use.  At this stage the
implementation is minimal, providing only the `sync` function used by the
command‑line interface.  Future versions will add additional helpers for
checking and releasing packages.
"""

from importlib.metadata import version as _get_version  # type: ignore

from .syncer import sync_project

__all__ = ["__version__", "sync_project"]


def __getattr__(name: str):
    """Lazily expose the package version.

    The version is looked up using importlib.metadata when accessed.  This
    avoids importing pkg_resources at runtime and follows the recommended
    pattern for modern packaging.
    """
    if name == "__version__":
        return _get_version(__name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
