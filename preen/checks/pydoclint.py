"""Pydoclint documentation linting check."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
# from typing import List  # No longer needed with Python 3.12+

from .base import Check, CheckResult, Issue, Severity, Impact


class PydoclintCheck(Check):
    """Check for docstring quality and completeness using pydoclint."""

    @property
    def name(self) -> str:
        return "pydoclint"

    @property
    def description(self) -> str:
        return "Check docstring quality and completeness with pydoclint"

    def _parse_pydoclint_output(self, output: str) -> list[Issue]:
        """Parse pydoclint output and convert to Issue objects."""
        issues = []
        
        # Pattern to match pydoclint output format:
        # path/to/file.py:line: DOC001 Missing docstring in function
        pattern = r'^(.+?):(\d+): (DOC\d+) (.+)$'
        
        for line in output.strip().split('\n'):
            if not line.strip():
                continue
                
            match = re.match(pattern, line)
            if match:
                file_path, line_num, code, description = match.groups()
                
                # Convert absolute path to relative
                try:
                    rel_path = Path(file_path).relative_to(self.project_dir)
                except ValueError:
                    # If path is not under project_dir, use as-is
                    rel_path = Path(file_path)
                
                # Determine impact based on file location and violation type
                impact = self._get_impact_for_violation(rel_path, code, description)
                
                # Determine severity - most docstring issues are warnings
                severity = Severity.ERROR if 'missing' in description.lower() and any(
                    critical in rel_path.name for critical in ['__init__.py', 'cli.py']
                ) or any(critical in str(rel_path) for critical in ['api/', 'public']) else Severity.WARNING
                
                issues.append(Issue(
                    check=self.name,
                    severity=severity,
                    description=f"{code}: {description}",
                    file=rel_path,
                    line=int(line_num),
                    impact=impact,
                    explanation=self._get_explanation_for_code(code),
                ))
        
        return issues

    def _get_impact_for_violation(self, file_path: Path, code: str, description: str) -> Impact:
        """Determine impact level based on file location and violation type."""
        # Critical for public APIs and main module files
        if file_path.name in ['__init__.py', 'cli.py'] or any(
            critical in str(file_path) for critical in ['api/', 'public']
        ):
            return Impact.CRITICAL
            
        # Important for most Python files with docstring issues
        if file_path.suffix == '.py':
            # Missing docstrings are more important than formatting issues
            if 'missing' in description.lower() or code in ['DOC101', 'DOC102', 'DOC103']:
                return Impact.IMPORTANT
            else:
                return Impact.INFORMATIONAL
                
        # Everything else is informational
        return Impact.INFORMATIONAL

    def _get_explanation_for_code(self, code: str) -> str:
        """Provide explanation for common pydoclint error codes."""
        explanations = {
            'DOC101': 'Missing docstring in public method',
            'DOC102': 'Missing docstring in public function', 
            'DOC103': 'Missing docstring in public class',
            'DOC201': 'Function/method has no argument documented',
            'DOC202': 'Function/method has argument documented but not defined',
            'DOC203': 'Function/method has return documented but no return statement',
            'DOC501': 'Function/method has exception documented but not raised',
            'DOC502': 'Function/method has exception raised but not documented',
        }
        
        base_explanation = explanations.get(
            code, 
            'Docstring formatting or completeness issue'
        )
        
        return f"{base_explanation}. Good documentation improves code maintainability and helps other developers understand your code."

    def run(self) -> CheckResult:
        """Run pydoclint check."""
        issues = []
        
        # Check if pydoclint is available
        try:
            subprocess.run(
                ["pydoclint", "--version"],
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
                        description="pydoclint is not installed. Install with: pip install pydoclint",
                        impact=Impact.CRITICAL,
                        explanation="pydoclint is required for docstring quality checking",
                    )
                ],
            )

        # Run pydoclint on the project directory
        # Use --quiet to suppress file scanning output, only show violations
        result = subprocess.run(
            ["pydoclint", "--quiet", "--style=google", str(self.project_dir)],
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )
        
        # pydoclint returns 0 if no issues, >0 if issues found
        if result.returncode != 0 and result.stdout:
            issues = self._parse_pydoclint_output(result.stdout)
        
        # Handle stderr errors (but not if we have stdout with violations)
        if result.stderr and result.returncode != 0 and not result.stdout:
            issues.append(Issue(
                check=self.name,
                severity=Severity.WARNING,
                description=f"pydoclint encountered an error: {result.stderr.strip()}",
                impact=Impact.INFORMATIONAL,
                explanation="pydoclint had trouble analyzing some files",
            ))

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return False  # Docstring quality requires manual fixes