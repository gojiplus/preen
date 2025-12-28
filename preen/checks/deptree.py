"""Circular dependency check using a simple Python implementation."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Set, List

from .base import Check, CheckResult, Issue, Severity, Impact


class DeptreeCheck(Check):
    """Check for circular dependencies in Python code."""

    @property
    def name(self) -> str:
        return "deptree"

    @property
    def description(self) -> str:
        return "Check for circular dependencies in Python code"

    def _get_python_files(self) -> List[Path]:
        """Get all Python files in the project."""
        python_files = []
        for path in self.project_dir.rglob("*.py"):
            # Skip __pycache__, .git, and test directories
            if any(skip in path.parts for skip in ["__pycache__", ".git", ".tox"]):
                continue
            python_files.append(path)
        return python_files

    def _extract_imports(self, file_path: Path) -> Set[str]:
        """Extract import statements from a Python file."""
        imports = set()
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content, filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module)

        except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
            pass  # Skip files that can't be parsed

        return imports

    def _module_name_from_path(self, file_path: Path) -> str:
        """Convert file path to module name."""
        try:
            relative_path = file_path.relative_to(self.project_dir)
        except ValueError:
            return str(file_path)

        # Remove .py extension
        if relative_path.suffix == ".py":
            relative_path = relative_path.with_suffix("")

        # Convert path parts to module name
        module_name = ".".join(relative_path.parts)

        # Handle __init__.py files
        if module_name.endswith(".__init__"):
            module_name = module_name[:-9]

        return module_name

    def _detect_cycles(self, graph: Dict[str, Set[str]]) -> List[List[str]]:
        """Detect cycles using DFS."""
        visited = set()
        rec_stack = set()
        cycles = []

        def dfs(node: str, path: List[str]) -> None:
            if node in rec_stack:
                # Found cycle
                try:
                    cycle_start = path.index(node)
                    cycle = path[cycle_start:] + [node]
                    cycles.append(cycle)
                except ValueError:
                    cycles.append([node])
                return

            if node in visited:
                return

            visited.add(node)
            rec_stack.add(node)

            for neighbor in graph.get(node, set()):
                if neighbor in graph:  # Only follow internal modules
                    dfs(neighbor, path + [node])

            rec_stack.remove(node)

        for module in graph:
            if module not in visited:
                dfs(module, [])

        return cycles

    def run(self) -> CheckResult:
        """Run circular dependency detection."""
        issues = []

        python_files = self._get_python_files()

        if not python_files:
            return CheckResult(check=self.name, passed=True, issues=[])

        # Build import graph
        graph = {}
        all_modules = set()

        # First pass: get all module names
        for file_path in python_files:
            module_name = self._module_name_from_path(file_path)
            all_modules.add(module_name)

        # Second pass: build import graph with only internal imports
        for file_path in python_files:
            module_name = self._module_name_from_path(file_path)
            imports = self._extract_imports(file_path)

            # Filter to only internal imports
            internal_imports = set()
            for imp in imports:
                # Check for relative imports or imports that match our modules
                if imp.startswith("."):
                    # Handle relative imports
                    if module_name:
                        parts = module_name.split(".")
                        if imp.startswith(".."):
                            # Go up one level
                            if len(parts) > 1:
                                base = ".".join(parts[:-1])
                                target = imp[2:]  # Remove '..'
                                if target:
                                    full_import = f"{base}.{target}"
                                else:
                                    full_import = base
                            else:
                                full_import = imp[2:]  # Just remove '..'
                        else:
                            # Single dot - same package
                            base = ".".join(parts[:-1]) if "." in module_name else ""
                            target = imp[1:]  # Remove '.'
                            if base and target:
                                full_import = f"{base}.{target}"
                            else:
                                full_import = target or base

                        if full_import in all_modules:
                            internal_imports.add(full_import)
                else:
                    # Check if it's an internal module
                    if imp in all_modules:
                        internal_imports.add(imp)
                    else:
                        # Check if it's a submodule of any internal module
                        for mod in all_modules:
                            if imp.startswith(mod + ".") or mod.startswith(imp + "."):
                                internal_imports.add(imp)
                                break

            graph[module_name] = internal_imports

        # Detect cycles
        cycles = self._detect_cycles(graph)

        for cycle in cycles:
            if len(cycle) > 1:  # Only report actual cycles
                cycle_str = " -> ".join(cycle)
                issues.append(
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description=f"Circular import detected: {cycle_str}",
                        impact=Impact.CRITICAL,
                        explanation="Circular imports can cause runtime failures when modules are loaded. They make code harder to understand and test.",
                        override_question="This is a serious issue that can break your package. Are you sure you want to release anyway?",
                    )
                )

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return False  # Circular dependencies require manual refactoring
