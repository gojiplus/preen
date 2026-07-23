"""Configuration for preen, read from pyproject.toml's ``[tool.preen]`` section."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PreenConfig:
    """Configuration for preen behavior."""

    # Structure preferences
    src_layout: bool = True
    tests_at_root: bool = True
    examples_at_root: bool = True

    # Checks
    skip_checks: list[str] = field(default_factory=list)

    @classmethod
    def from_pyproject(cls, project_dir: Path) -> "PreenConfig":
        """Load configuration from pyproject.toml.

        Args:
            project_dir: Path to the project directory.

        Returns:
            PreenConfig instance with values from ``[tool.preen]`` or defaults.
        """
        config = cls()
        pyproject_path = project_dir / "pyproject.toml"

        if not pyproject_path.exists():
            return config

        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)

        tool_config = data.get("tool", {}).get("preen", {})

        for key, value in tool_config.items():
            if hasattr(config, key):
                setattr(config, key, value)

        return config
