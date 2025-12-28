"""Configuration management for preen.

This module handles loading and merging configuration from pyproject.toml's
[tool.preen] section with default values.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore


@dataclass
class PreenConfig:
    """Configuration for preen behavior."""

    # Structure preferences
    src_layout: bool = True
    tests_at_root: bool = True
    examples_at_root: bool = True

    # Documentation
    sphinx_theme: str = "furo"
    use_myst: bool = True
    readme_includes: bool = True
    autodoc: bool = True

    # CI Generation
    ci_os: List[str] = field(default_factory=lambda: ["ubuntu-latest"])
    ci_runner: str = "uv"
    ci_extras: List[str] = field(default_factory=lambda: ["test"])

    # Release
    release_branch: str = "main"
    tag_prefix: str = "v"
    trusted_publisher: bool = True

    # LLM (future)
    llm_enabled: bool = False
    llm_provider: str = "anthropic"
    llm_model: str = "claude-3-sonnet-20240320"

    # Checks
    skip_checks: List[str] = field(default_factory=list)
    custom_checks: List[str] = field(default_factory=list)

    @classmethod
    def from_pyproject(cls, project_dir: Path) -> "PreenConfig":
        """Load configuration from pyproject.toml.

        Args:
            project_dir: Path to the project directory

        Returns:
            PreenConfig instance with values from [tool.preen] or defaults
        """
        config = cls()
        pyproject_path = project_dir / "pyproject.toml"

        if not pyproject_path.exists():
            return config

        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)

        tool_config = data.get("tool", {}).get("preen", {})

        # Update config with values from pyproject.toml
        for key, value in tool_config.items():
            if hasattr(config, key):
                setattr(config, key, value)

        return config

    def get_ci_python_versions(self, pyproject_data: Dict[str, Any]) -> List[str]:
        """Get Python versions from explicit preen config or sensible defaults.

        Args:
            pyproject_data: Parsed pyproject.toml data

        Returns:
            List of Python version strings for CI matrix
        """
        preen_config = pyproject_data.get("tool", {}).get("preen", {})
        return preen_config.get("ci_python_versions", ["3.12", "3.13", "3.14"])
