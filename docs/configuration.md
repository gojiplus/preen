# Configuration

Preen can be configured through your `pyproject.toml` file under the `[tool.preen]` section. This allows you to customize behavior, enable/disable checks, and set project-specific preferences.

## Basic Configuration

```toml
[tool.preen]
# Project metadata
project_name = "my-project"
author = "Your Name"
author_email = "you@example.com"

# Enable/disable checks globally
enabled_checks = ["structure", "ruff", "version", "deps"]
disabled_checks = ["links", "pyright"]

# Global settings
strict_mode = false
auto_fix = true
verbose = false
```

## Check-Specific Configuration

### Structure Check

```toml
[tool.preen.structure]
# Enforce tests/ directory at project root
tests_at_root = true

# Enforce examples/ directory at project root  
examples_at_root = true

# Prefer src/ layout over flat layout
src_layout = false

# Additional directories to check
check_directories = ["scripts", "notebooks"]
```

### Ruff Configuration

```toml
[tool.preen.ruff]
# Target Python version
target_version = "py312"

# Line length (default: 88)
line_length = 88

# Additional ruff arguments
extra_args = ["--fix", "--show-fixes"]

# Rules to enable/disable
select = ["E", "W", "F", "I"]
ignore = ["E203", "W503"]
```

### Version Check

```toml
[tool.preen.version]
# Enforce semantic versioning
enforce_semver = true

# Files to check for version consistency
version_files = [
    "pyproject.toml",
    "src/myproject/__init__.py",
    "docs/conf.py"
]

# Version format regex
version_pattern = "\\d+\\.\\d+\\.\\d+"
```

### Dependencies Check

```toml
[tool.preen.deps]
# Check for unused dependencies
check_unused = true

# Check for security vulnerabilities
check_security = true

# Maximum age for dependencies (days)
max_age_days = 365

# Dependencies to ignore in unused check
ignore_unused = ["black", "mypy"]
```

### CI Matrix Check

```toml
[tool.preen.ci_matrix]
# Required Python versions
required_versions = ["3.12", "3.13"]

# Required OS matrix
required_os = ["ubuntu-latest", "windows-latest", "macos-latest"]

# CI workflow files to check
workflow_files = [".github/workflows/ci.yml"]
```

### Documentation Checks

```toml
[tool.preen.links]
# Timeout for link checking (seconds)
timeout = 10

# Maximum retries for failed links
max_retries = 3

# URLs to skip checking
skip_urls = [
    "https://example.com/private",
    "localhost",
]

# File patterns to check for links
include_patterns = ["*.md", "*.rst", "*.py"]
```

### Code Quality Checks

```toml
[tool.preen.codespell]
# Additional dictionaries
dictionaries = ["clear", "rare"]

# Files to skip
skip_files = ["*.po", "*.pot"]

# Words to ignore
ignore_words = ["ist", "nd"]

[tool.preen.pydoclint]
# Docstring style
style = "google"  # or "numpy", "sphinx"

# Require docstrings for public functions
require_public = true

# Require return type documentation
require_return_section = true

[tool.preen.pyright]
# Type checking mode
type_checking_mode = "basic"  # or "strict", "off"

# Include/exclude patterns
include = ["src", "tests"]
exclude = ["**/node_modules", "**/__pycache__"]
```

## Template Configuration

Configure how preen generates and syncs project files:

```toml
[tool.preen.templates]
# Template source
template_dir = "custom_templates"

# Files to always overwrite
force_overwrite = [
    ".github/workflows/ci.yml",
    "pyproject.toml"
]

# Files to never touch
never_overwrite = [
    "README.md",
    "LICENSE"
]

# Template variables
[tool.preen.templates.variables]
project_description = "My awesome project"
license_type = "MIT"
github_username = "myusername"
```

## Sync Configuration

Control how preen syncs project files:

```toml
[tool.preen.sync]
# Categories to sync by default
default_categories = ["ci", "docs", "quality"]

# Dry run mode by default
dry_run = false

# Backup original files
backup_files = true

# Sync-specific settings
[tool.preen.sync.ci]
python_versions = ["3.12", "3.13"]
test_command = "pytest"
lint_command = "ruff check"

[tool.preen.sync.docs]
docs_dir = "docs"
build_command = "sphinx-build -b html docs docs/_build/html"
theme = "furo"
```

## Environment Variables

Preen also supports configuration via environment variables:

```bash
# Enable debug mode
export PREEN_DEBUG=1

# Set config file location
export PREEN_CONFIG=/path/to/preen.toml

# Override specific settings
export PREEN_STRICT_MODE=true
export PREEN_AUTO_FIX=false
```

## Configuration Validation

Preen validates your configuration on startup:

```bash
# Check configuration validity
preen config --validate

# Show effective configuration
preen config --show

# Show configuration schema
preen config --schema
```

## Example Complete Configuration

```toml
[tool.preen]
# Basic settings
enabled_checks = ["structure", "ruff", "version", "deps", "tests"]
disabled_checks = ["links", "pyright"]
strict_mode = false
auto_fix = true

# Structure preferences
[tool.preen.structure]
tests_at_root = true
src_layout = false

# Code quality
[tool.preen.ruff]
target_version = "py312"
line_length = 88
select = ["E", "W", "F", "I", "N"]

[tool.preen.codespell]
skip_files = ["*.po"]

# Version management
[tool.preen.version]
enforce_semver = true
version_files = ["pyproject.toml", "src/myproject/__init__.py"]

# Dependencies
[tool.preen.deps]
check_unused = true
check_security = true
ignore_unused = ["black", "mypy"]

# CI configuration
[tool.preen.ci_matrix]
required_versions = ["3.12", "3.13"]
required_os = ["ubuntu-latest"]

# Template customization
[tool.preen.templates]
force_overwrite = [".github/workflows/ci.yml"]
never_overwrite = ["README.md"]

[tool.preen.templates.variables]
license_type = "MIT"
github_username = "myusername"
```

This configuration provides a good balance of code quality checks while allowing customization for your specific project needs.