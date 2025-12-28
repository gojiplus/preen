# preen

[![PyPI version](https://badge.fury.io/py/preen.svg)](https://badge.fury.io/py/preen)
[![CI](https://github.com/gojiplus/preen/actions/workflows/ci.yml/badge.svg)](https://github.com/gojiplus/preen/actions)
[![Documentation](https://github.com/gojiplus/preen/actions/workflows/docs.yml/badge.svg)](https://gojiplus.github.io/preen)
[![Downloads](https://pepy.tech/badge/preen)](https://pepy.tech/project/preen)

**An opinionated, agentic CLI for Python package hygiene and release**

*"Get your feathers in order before you fly"*

`preen` is a comprehensive tool for Python package maintenance that treats `pyproject.toml` as the single source of truth. It automatically generates and synchronizes derived files, runs comprehensive pre-release checks, and provides an opinionated workflow for package development and release.

## Features

- 🔍 **12 comprehensive checks** - linting, tests, dependencies, CI matrix, project structure, version consistency, citation validation, link validation, documentation quality, static type checking, and spell checking
- 🔧 **Interactive fixes** - preview diffs and apply fixes automatically or selectively
- 📦 **Package initialization** - scaffold new packages with opinionated best practices
- 🔄 **File synchronization** - generate CI workflows, documentation config, and CITATION.cff from pyproject.toml
- 📈 **Version management** - semantic versioning with automatic derived file updates
- 🎯 **Modern tooling** - uv-native workflows, GitHub Actions, and trusted publishing

## Installation

```bash
pip install preen
```

Requires Python 3.9+

## Quick Start

### Create a new package
```bash
preen init mypackage
cd mypackage
pip install -e .[dev]
```

### Run checks and fixes
```bash
preen check          # Interactive check with fix prompts
preen check --fix    # Apply all fixes automatically
preen check --strict # Exit 1 if any issues (perfect for CI)
```

### Sync derived files
```bash
preen sync                    # Update all derived files
preen sync --only citation   # Update only CITATION.cff
preen sync --check          # Check if files need updating (CI mode)
```

### Manage versions
```bash
preen bump patch    # 1.0.0 → 1.0.1
preen bump minor    # 1.0.1 → 1.1.0
preen bump major    # 1.1.0 → 2.0.0
```

## Commands

### `preen init`
Initialize new Python packages with opinionated structure:
- Modern `pyproject.toml` with setuptools backend
- `src/` layout for better import isolation  
- Comprehensive `tests/` directory at project root
- GitHub Actions workflows for CI, docs, and release
- Pre-configured development dependencies (pytest, ruff)
- CITATION.cff for academic software

```bash
preen init mypackage                    # Interactive mode
preen init mypackage --dir ./custom     # Specify directory
```

### `preen check`
Run comprehensive pre-release checks:

| Check | Description |
|-------|-------------|
| **ruff** | Code linting and formatting |
| **tests** | Run pytest suite |
| **deps** | Find unused/missing dependencies (requires deptry) |
| **ci-matrix** | Verify CI tests all declared Python versions |
| **structure** | Enforce project structure best practices |
| **version** | Detect hardcoded version strings |
| **citation** | Ensure CITATION.cff matches pyproject.toml |
| **links** | Check for broken or dead links in project files |
| **pydoclint** | Check docstring quality and completeness |
| **pyright** | Static type checking for type safety |
| **codespell** | Check spelling in documentation and comments |

```bash
preen check                     # Interactive mode
preen check --fix              # Auto-apply all fixes
preen check --only ruff,tests  # Run specific checks
preen check --skip deps,links,pydoclint,pyright,codespell  # Skip optional checks
preen check --strict           # CI mode (exit 1 on issues)
```

### `preen sync`
Synchronize derived files from `pyproject.toml`:
- `.github/workflows/ci.yml` - CI matrix from Python classifiers
- `.github/workflows/docs.yml` - Documentation deployment
- `.github/workflows/release.yml` - PyPI publishing with trusted publisher
- `docs/conf.py` - Sphinx configuration
- `CITATION.cff` - Citation metadata for academic software

```bash
preen sync                      # Update all derived files
preen sync --only ci,citation  # Update specific targets
preen sync --check             # Verify files are up to date
```

### `preen bump`
Semantic version management:
- Updates version in `pyproject.toml`
- Regenerates all derived files with new version
- Commits changes to git with conventional commit message

```bash
preen bump patch        # Bug fixes: 1.0.0 → 1.0.1
preen bump minor        # New features: 1.0.1 → 1.1.0  
preen bump major        # Breaking changes: 1.1.0 → 2.0.0
preen bump patch --dry-run     # Preview changes
preen bump minor --no-commit   # Skip git commit
```

## Configuration

Customize behavior in `pyproject.toml`:

```toml
[tool.preen]
# CI configuration
ci_os = ["ubuntu-latest", "macos-latest"]
ci_runner = "uv"  # or "pip"

# Documentation
sphinx_theme = "furo"
use_myst = true

# Structure preferences  
src_layout = true
tests_at_root = true

# Skip specific checks
skip_checks = ["deps", "structure"]
```

## Development Workflow

Typical workflow for package maintenance:

```bash
# 1. Initialize new package
preen init myawesome-package
cd myawesome-package

# 2. Develop your package
# ... write code, tests ...

# 3. Pre-release checks
preen check --fix

# 4. Version bump and release prep
preen bump minor
git push origin main

# 5. Manual steps (for now)
# - Create GitHub release
# - CI will build and publish to PyPI via trusted publisher
```

## Philosophy

**pyproject.toml as Single Source of Truth**
- All metadata lives in one place
- Derived files are generated, never edited manually
- Eliminates version mismatches and configuration drift

**Opinionated Best Practices**
- `src/` layout for better import isolation
- `tests/` at project root, not inside package
- Modern Python packaging (setuptools, trusted publishing)
- Comprehensive CI matrix matching declared Python support

**DRY Across Configuration**
- CI matrix generated from Python classifiers
- Documentation config reflects project metadata
- CITATION.cff stays in sync with authors and version

## Generated Files

When you run `preen sync`, these files are generated/updated:

```
.github/workflows/
├── ci.yml           # Test matrix + linting
├── docs.yml         # Documentation deployment  
└── release.yml      # PyPI publishing

docs/
└── conf.py          # Sphinx configuration

CITATION.cff         # Citation metadata
```

All generated files include a header indicating they're managed by preen:
```yaml
# Generated by preen — do not edit manually
# Regenerate with: preen sync
```

## Integration

**GitHub Actions**
```yaml
# .github/workflows/quality.yml
- name: Package hygiene
  run: |
    pip install preen
    preen check --strict
    preen sync --check
```

**Pre-commit Hook**
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: preen-check
        name: preen check
        entry: preen check --strict
        language: system
        pass_filenames: false
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run `preen check` to ensure code quality
5. Submit a pull request

For development setup:
```bash
git clone https://github.com/gojiplus/preen.git
cd preen
pip install -e .[dev]
preen check
```