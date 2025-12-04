"""Template manager for rendering project files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader


class TemplateManager:
    """Manages templates for project initialization."""

    def __init__(self, templates_dir: Path | None = None):
        """Initialize template manager.

        Args:
            templates_dir: Directory containing templates. If None, uses built-in templates.
        """
        if templates_dir is None:
            templates_dir = Path(__file__).parent / "files"

        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            keep_trailing_newline=True,
        )

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a template with the given context.

        Args:
            template_name: Name of template file to render.
            context: Variables to use in template.

        Returns:
            Rendered template content.
        """
        template = self.env.get_template(template_name)
        return template.render(**context)

    def list_templates(self) -> list[str]:
        """List available templates."""
        if not self.templates_dir.exists():
            return []

        return [f.name for f in self.templates_dir.iterdir() if f.is_file()]

    def get_template_path(self, template_name: str) -> Path:
        """Get path to a template file."""
        return self.templates_dir / template_name
