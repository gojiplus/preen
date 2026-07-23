"""Preen — conformance and adoption CLI for the py-canon fleet standard."""

from importlib.metadata import version as _get_version


def __getattr__(name: str) -> str:
    """Lazily expose the package version.

    Args:
        name: Attribute name being looked up.

    Returns:
        The installed package version for ``__version__``.

    Raises:
        AttributeError: If any other attribute is requested.
    """
    if name == "__version__":
        return _get_version(__name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
