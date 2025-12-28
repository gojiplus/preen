"""Pyright static type checking check."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .base import Check, CheckResult, Issue, Severity, Impact


class PyrightCheck(Check):
    """Check for type errors and warnings using pyright static type checker."""

    @property
    def name(self) -> str:
        return "pyright"

    @property
    def description(self) -> str:
        return "Check static typing with pyright"

    def _parse_pyright_json(self, json_output: str) -> list[Issue]:
        """Parse pyright JSON output and convert to Issue objects."""
        issues = []
        
        try:
            data = json.loads(json_output)
        except json.JSONDecodeError:
            return [Issue(
                check=self.name,
                severity=Severity.ERROR,
                description="Failed to parse pyright JSON output",
                impact=Impact.IMPORTANT,
                explanation="Pyright returned invalid JSON, possibly due to a configuration error",
            )]
        
        # Parse general diagnostics
        for diagnostic in data.get('generalDiagnostics', []):
            issues.append(self._create_issue_from_diagnostic(diagnostic))
            
        return issues

    def _create_issue_from_diagnostic(self, diagnostic: dict[str, Any]) -> Issue:
        """Create an Issue from a pyright diagnostic."""
        # Extract file path and make it relative
        file_path = diagnostic.get('file', '')
        try:
            rel_path = Path(file_path).relative_to(self.project_dir) if file_path else None
        except ValueError:
            rel_path = Path(file_path) if file_path else None
        
        # Extract line and column info
        line = None
        if 'range' in diagnostic and 'start' in diagnostic['range']:
            line = diagnostic['range']['start'].get('line', 0) + 1  # Convert 0-based to 1-based
        
        # Determine severity based on pyright severity
        pyright_severity = diagnostic.get('severity', 'error').lower()
        match pyright_severity:
            case 'error':
                severity = Severity.ERROR
                impact = Impact.CRITICAL
            case 'warning':
                severity = Severity.WARNING
                impact = Impact.IMPORTANT
            case _:  # information, etc.
                severity = Severity.WARNING
                impact = Impact.INFORMATIONAL
        
        # Get the diagnostic message and rule
        message = diagnostic.get('message', 'Unknown type error')
        rule = diagnostic.get('rule', '')
        
        # Format description with rule if available
        description = f"{message}"
        if rule:
            description = f"{rule}: {message}"
        
        return Issue(
            check=self.name,
            severity=severity,
            description=description,
            file=rel_path,
            line=line,
            impact=impact,
            explanation=self._get_explanation_for_rule(rule, pyright_severity),
        )

    def _get_explanation_for_rule(self, rule: str, severity: str) -> str:
        """Provide explanation for common pyright rules."""
        rule_explanations = {
            'reportMissingTypeStubs': 'Missing type stubs for imported library. Consider installing types package or adding type: ignore.',
            'reportUnknownMemberType': 'Unknown member type. Add type annotations to improve type safety.',
            'reportUnknownVariableType': 'Unknown variable type. Add type annotations for better type checking.',
            'reportMissingParameterType': 'Missing parameter type annotation. Add type hints for function parameters.',
            'reportMissingReturnType': 'Missing return type annotation. Add return type hints for functions.',
            'reportUnusedImport': 'Unused import detected. Remove unused imports to clean up code.',
            'reportUnusedVariable': 'Unused variable detected. Remove unused variables or prefix with underscore.',
            'reportIncompatibleMethodOverride': 'Method override is incompatible with base class. Fix signature to match parent.',
            'reportGeneralTypeIssues': 'General type issue detected. Review type annotations and usage.',
        }
        
        base_explanation = rule_explanations.get(
            rule, 
            f"Type {severity} detected by pyright static analysis"
        )
        
        return f"{base_explanation}. Static type checking helps catch bugs early and improves code reliability."

    def run(self) -> CheckResult:
        """Run pyright type checking."""
        issues = []
        
        # Check if pyright is available
        try:
            subprocess.run(
                ["pyright", "--version"],
                capture_output=True,
                check=True,
                cwd=self.project_dir,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return CheckResult(
                check=self.name,
                passed=False,
                issues=[
                    Issue(
                        check=self.name,
                        severity=Severity.ERROR,
                        description="pyright is not installed. Install with: pip install pyright",
                        impact=Impact.CRITICAL,
                        explanation="pyright is required for static type checking",
                    )
                ],
            )

        # Run pyright with JSON output for easier parsing
        result = subprocess.run(
            ["pyright", "--outputjson", str(self.project_dir)],
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )
        
        # pyright returns:
        # 0: No errors
        # 1: Errors found
        # 2: Fatal error (config issues, etc.)
        
        match result.returncode:
            case 0 | 1 if result.stdout:
                # Normal completion with or without type errors
                issues = self._parse_pyright_json(result.stdout)
            case 2 | _ if result.stderr and not result.stdout:
                # Fatal error (return code 2 or stderr with no stdout)
                error_msg = result.stderr.strip() or "pyright encountered a fatal error"
                issues.append(Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    description=f"pyright fatal error: {error_msg}",
                    impact=Impact.IMPORTANT,
                    explanation="pyright could not complete type checking, possibly due to configuration issues",
                ))
            case _:
                # Default case - no output to process
                pass

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return False  # Type annotations require manual fixes