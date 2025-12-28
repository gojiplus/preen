# Usage Guide

## Overview

Preen provides several commands to help maintain your Python projects:

- `preen check` - Run all enabled checks on your project
- `preen sync` - Synchronize project files and configuration
- `preen init` - Initialize preen configuration for a new project
- `preen bump` - Bump package version
- `preen fix` - Fix issues automatically where possible

## Basic Commands

### Check Your Project

Run all enabled checks to identify issues:

```bash
# Check everything
preen check

# Check specific types
preen check --only structure
preen check --only ruff
preen check --only deptree

# Run in strict mode (fail on any issues)
preen check --strict
```

### Sync Project Files

Synchronize and update project configuration files:

```bash
# Sync everything
preen sync

# Sync specific categories
preen sync --only docs
preen sync --only ci
preen sync --only workflows
```

### Initialize Configuration

Set up preen for a new project:

```bash
# Initialize with defaults
preen init

# Initialize with specific template
preen init --template basic
```

### Version Management

Bump your package version:

```bash
# Bump patch version (1.0.0 -> 1.0.1)
preen bump patch

# Bump minor version (1.0.0 -> 1.1.0)
preen bump minor

# Bump major version (1.0.0 -> 2.0.0)
preen bump major

# Set specific version
preen bump --version 2.1.3
```

### Fix Issues Automatically

Fix issues that can be automatically resolved:

```bash
# Fix all fixable issues
preen fix

# Fix specific check types
preen fix --only ruff
preen fix --only structure
```

## Common Workflows

### New Project Setup

```bash
# 1. Initialize preen configuration
preen init

# 2. Sync project files
preen sync

# 3. Check for any issues
preen check

# 4. Fix any auto-fixable issues
preen fix
```

### Regular Maintenance

```bash
# Check for issues
preen check

# Fix what can be fixed automatically
preen fix

# Sync any updated templates
preen sync
```

### Before Release

```bash
# Ensure everything is clean
preen check --strict

# Bump version
preen bump minor

# Final check
preen check
```

## Command Options

### Global Options

- `--verbose, -v` - Increase verbosity
- `--quiet, -q` - Suppress output
- `--config PATH` - Use specific config file
- `--help` - Show help message

### Check Options

- `--only TYPES` - Run only specific check types
- `--skip TYPES` - Skip specific check types
- `--strict` - Fail on any issues (exit code 1)
- `--fix` - Automatically fix issues where possible

### Sync Options

- `--only CATEGORIES` - Sync only specific categories
- `--dry-run` - Show what would be synced without making changes
- `--force` - Overwrite existing files

For detailed help on any command, use:

```bash
preen COMMAND --help
```