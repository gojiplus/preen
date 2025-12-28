"""Codespell spell checking check."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
# from typing import List  # No longer needed with Python 3.12+

from .base import Check, CheckResult, Issue, Fix, Severity, Impact


class CodespellCheck(Check):
    """Check for spelling errors in documentation and comments using codespell."""

    @property
    def name(self) -> str:
        return "codespell"

    @property
    def description(self) -> str:
        return "Check spelling in documentation and comments with codespell"

    def _parse_codespell_output(self, output: str) -> list[Issue]:
        """Parse codespell output and convert to Issue objects."""
        issues = []
        
        # Pattern to match codespell output format:
        # path/to/file.py:line: word ==> suggestion
        pattern = r'^(.+?):(\d+): (.+) ==> (.+)$'
        
        for line in output.strip().split('\n'):
            if not line.strip():
                continue
                
            match = re.match(pattern, line)
            if match:
                file_path, line_num, misspelled, suggestion = match.groups()
                
                # Convert absolute path to relative
                try:
                    rel_path = Path(file_path).relative_to(self.project_dir)
                except ValueError:
                    # If path is not under project_dir, use as-is
                    rel_path = Path(file_path)
                
                # Determine impact based on file location
                impact = self._get_impact_for_file(rel_path)
                
                issues.append(Issue(
                    check=self.name,
                    severity=Severity.WARNING,  # Spelling errors are usually warnings
                    description=f"'{misspelled}' should be '{suggestion}'",
                    file=rel_path,
                    line=int(line_num),
                    impact=impact,
                    explanation=f"Spelling error detected. '{misspelled}' should be spelled '{suggestion}'. Good spelling improves documentation quality and professionalism.",
                ))
        
        return issues

    def _get_impact_for_file(self, file_path: Path) -> Impact:
        """Determine impact level based on file location."""
        file_str = str(file_path).lower()
        
        # Critical for user-facing documentation
        if any(critical in file_str for critical in ['readme', 'changelog', 'license', 'contributing']):
            return Impact.CRITICAL
            
        # Important for documentation and code
        if file_path.suffix in ['.md', '.rst', '.py', '.txt'] or 'docs/' in file_str:
            return Impact.IMPORTANT
            
        # Informational for other files
        return Impact.INFORMATIONAL

    def _get_codespell_command(self) -> list[str]:
        """Build codespell command with appropriate options."""
        cmd = ["codespell"]
        
        # Add skip patterns for common directories/files that don't need spell checking
        skip_patterns = [
            ".git",
            "__pycache__", 
            "*.pyc",
            "*.egg-info",
            ".pytest_cache",
            "node_modules",
            ".mypy_cache",
            "dist",
            "build",
            ".venv",
            "venv"
        ]
        
        cmd.extend(["--skip", ",".join(skip_patterns)])
        
        # Focus on text files and code
        # Don't spell check binary files, images, etc.
        cmd.extend([
            "--check-filenames",  # Also check file names
            "--quiet-level", "2",  # Suppress binary file warnings
        ])
        
        # Add project directory as target
        cmd.append(str(self.project_dir))
        
        return cmd

    def run(self) -> CheckResult:
        """Run codespell check."""
        issues = []
        
        # Check if codespell is available
        try:
            subprocess.run(
                ["codespell", "--version"],
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
                        description="codespell is not installed. Install with: pip install codespell",
                        impact=Impact.CRITICAL,
                        explanation="codespell is required for spell checking documentation and comments",
                    )
                ],
            )

        # Run codespell 
        cmd = self._get_codespell_command()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )
        
        # codespell returns:
        # 0: No misspellings found
        # >0: Misspellings found (exit code represents number of files with issues)
        
        match result.returncode:
            case 0:
                # No misspellings found - issues list stays empty
                pass
            case code if code > 0 and (result.stdout or result.stderr):
                # Misspellings found - check both stdout and stderr
                output = result.stdout if result.stdout else result.stderr
                if output:
                    issues = self._parse_codespell_output(output)
                    
                    # Add a single fix for all spelling issues if any exist
                    if issues:
                        fix = self._get_fix_for_issues(issues)
                        # Attach the fix to the first issue (consolidated approach)
                        issues[0].proposed_fix = fix
            case code if code > 0:
                # Non-zero exit code but no output - likely an error
                error_msg = result.stderr.strip() or f"codespell exited with code {result.returncode}"
                issues.append(Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    description=f"codespell error: {error_msg}",
                    impact=Impact.INFORMATIONAL,
                    explanation="codespell had trouble analyzing some files",
                ))

        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return True  # Codespell can auto-fix spelling errors

    def _get_fix_for_issues(self, issues: list[Issue]) -> Fix:
        """Create a Fix object for codespell auto-correction."""
        def apply_codespell_fix():
            """Apply codespell automatic fixes."""
            cmd = self._get_codespell_command()
            # Add write flag to actually apply fixes
            cmd.insert(-1, "--write-changes")  # Insert before directory argument
            
            subprocess.run(
                cmd,
                cwd=self.project_dir,
                check=False,  # Don't raise on exit code 1 (fixes applied)
            )

        # Get diff preview by running with --diff flag
        cmd = self._get_codespell_command() 
        cmd.insert(-1, "--diff")  # Insert before directory argument
        
        diff_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )
        
        diff_output = diff_result.stdout if diff_result.stdout else "No diff available"
        
        return Fix(
            description=f"Apply codespell automatic fixes for {len(issues)} spelling error(s)",
            diff=diff_output,
            apply=apply_codespell_fix,
        )