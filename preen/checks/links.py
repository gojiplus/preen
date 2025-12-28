"""Link validation check."""

from __future__ import annotations

import re
from pathlib import Path
# from typing import Dict, List, Set, Optional, Tuple  # No longer needed with Python 3.12+
from urllib.parse import urlparse

from .base import Check, CheckResult, Issue, Severity, Impact


class LinkCheck(Check):
    """Check for broken or dead links in project files."""

    # URL regex pattern to match HTTP/HTTPS URLs
    URL_PATTERN = re.compile(
        r'https?://(?:[-\w.])+(?:[:\d]+)?(?:/(?:[\w/_.])*(?:\?(?:[\w&=%.])*)?(?:#(?:[\w.])*)?)?',
        re.IGNORECASE
    )
    
    # File patterns to scan
    SCAN_PATTERNS = {
        "*.md", "*.rst", "*.txt", "*.py", "*.toml", "*.yaml", "*.yml", 
        "*.json", "*.cfg", "*.ini", "*.sh"
    }
    
    # URLs to skip by default
    DEFAULT_SKIP_PATTERNS = {
        "localhost", "127.0.0.1", "0.0.0.0", "example.com", "example.org",
        "test.com", "placeholder.com", "your-domain.com"
    }

    @property
    def name(self) -> str:
        return "links"

    @property
    def description(self) -> str:
        return "Check for broken or dead links in project files"

    def _should_skip_url(self, url: str) -> bool:
        """Check if URL should be skipped."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Skip URLs with skip patterns
        for pattern in self.DEFAULT_SKIP_PATTERNS:
            if pattern in domain:
                return True
                
        # Skip non-HTTP(S) URLs
        if parsed.scheme not in ('http', 'https'):
            return True
            
        return False

    def _extract_urls_from_file(self, file_path: Path) -> list[tuple[str, int]]:
        """Extract URLs from a file, returning (url, line_number) tuples."""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return []
            
        urls = []
        for line_num, line in enumerate(content.splitlines(), 1):
            for match in self.URL_PATTERN.finditer(line):
                url = match.group()
                if not self._should_skip_url(url):
                    urls.append((url, line_num))
                    
        return urls

    def _find_all_urls(self) -> dict[str, list[tuple[str, int]]]:
        """Find all URLs in project files."""
        url_map = {}
        
        for pattern in self.SCAN_PATTERNS:
            for file_path in self.project_dir.glob(f"**/{pattern}"):
                # Skip hidden files and directories
                if any(part.startswith('.') for part in file_path.parts):
                    continue
                    
                # Skip common build/cache directories
                skip_dirs = {'__pycache__', 'node_modules', '.git', 'build', 'dist', '.pytest_cache'}
                if any(skip_dir in file_path.parts for skip_dir in skip_dirs):
                    continue
                
                urls = self._extract_urls_from_file(file_path)
                if urls:
                    rel_path = str(file_path.relative_to(self.project_dir))
                    url_map[rel_path] = urls
                    
        return url_map

    def _check_url_sync(self, url: str) -> tuple[str, int, str]:
        """Check a single URL synchronously. Returns (url, status_code, error_msg)."""
        try:
            import httpx
            
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.head(url)
                return (url, response.status_code, "")
                    
        except Exception as e:
            return (url, 0, str(e))

    def _get_impact_for_file(self, file_path: Path) -> Impact:
        """Determine impact level based on file location."""
        file_str = str(file_path).lower()
        
        # Critical files
        if any(critical in file_str for critical in ['readme', 'docs/', 'documentation']):
            return Impact.CRITICAL
            
        # Important files
        if file_path.suffix in ['.md', '.rst', '.yml', '.yaml'] or file_path.name == 'pyproject.toml':
            return Impact.IMPORTANT
            
        # Everything else
        return Impact.INFORMATIONAL

    def run(self) -> CheckResult:
        """Run the link check."""
        issues = []
        
        # Find all URLs
        url_map = self._find_all_urls()
        
        if not url_map:
            return CheckResult(
                check=self.name,
                passed=True,
                issues=[],
            )
        
        # Collect unique URLs to check
        unique_urls = set()
        for file_urls in url_map.values():
            for url, _ in file_urls:
                unique_urls.add(url)
        
        if not unique_urls:
            return CheckResult(
                check=self.name,
                passed=True,
                issues=[],
            )
        
        # Check URLs
        url_results = {}
        for url in unique_urls:
            url_results[url] = self._check_url_sync(url)
        
        # Process results and create issues
        for file_path, file_urls in url_map.items():
            for url, line_num in file_urls:
                checked_url, status_code, error_msg = url_results[url]
                
                impact = self._get_impact_for_file(Path(file_path))
                
                # Determine if this is an issue
                match status_code:
                    case 0:  # Connection error
                        issues.append(Issue(
                            check=self.name,
                            severity=Severity.ERROR,
                            description=f"Dead link: {url} - {error_msg}",
                            file=Path(file_path),
                            line=line_num,
                            impact=impact,
                            explanation=f"Link appears to be dead or unreachable: {error_msg}",
                        ))
                    case code if 400 <= code < 500:  # Client error
                        issues.append(Issue(
                            check=self.name,
                            severity=Severity.WARNING,
                            description=f"Broken link: {url} (HTTP {status_code})",
                            file=Path(file_path),
                            line=line_num,
                            impact=impact,
                            explanation=f"Link returns HTTP {status_code}, indicating a client error (page not found, forbidden, etc.)",
                        ))
                    case code if 500 <= code < 600:  # Server error
                        issues.append(Issue(
                            check=self.name,
                            severity=Severity.WARNING,
                            description=f"Server error for link: {url} (HTTP {status_code})",
                            file=Path(file_path),
                            line=line_num,
                            impact=impact,
                            explanation=f"Link returns HTTP {status_code}, indicating a server error",
                        ))
        
        return CheckResult(
            check=self.name,
            passed=len(issues) == 0,
            issues=issues,
        )

    def can_fix(self) -> bool:
        return False  # Link checking doesn't offer automatic fixes