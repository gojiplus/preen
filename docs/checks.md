# Available Checks

Preen includes a comprehensive set of checks to help maintain your Python project. Each check can be run individually or as part of a complete project audit.

## Project Structure Checks

### Structure Check (`structure`)

Validates project layout and structure follows best practices:

- **Tests Location**: Ensures `tests/` directory is at project root, not inside packages
- **Examples Location**: Ensures `examples/` directory is at project root
- **Src Layout**: Checks for proper src/ layout vs flat layout
- **Anti-patterns**: Detects common issues like committed `__pycache__` directories

**Auto-fixable**: Yes (can move directories and update `.gitignore`)

### Dependencies Check (`deps`)

Analyzes project dependencies and requirements:

- Validates dependency versions and constraints
- Checks for unused dependencies
- Identifies security vulnerabilities
- Ensures requirements files are up to date

### Dependency Tree Check (`deptree`)

Analyzes import dependencies within your project:

- Maps internal module dependencies
- Detects circular dependencies  
- Identifies unused internal modules
- Validates import structure

## Code Quality Checks

### Ruff Check (`ruff`)

Runs Ruff linter for comprehensive code quality:

- Style violations (PEP 8)
- Code complexity issues
- Import sorting
- Unused variables and imports
- Security issues

**Auto-fixable**: Yes (most Ruff rules can be auto-fixed)

### Codespell Check (`codespell`)

Checks for common spelling mistakes in code and documentation:

- Detects typos in comments and docstrings
- Checks variable and function names
- Validates documentation spelling

**Auto-fixable**: Yes (can fix common typos automatically)

### Pydoclint Check (`pydoclint`)

Validates docstring quality and completeness:

- Checks docstring presence for public functions/classes
- Validates docstring format (Google/NumPy/Sphinx style)
- Ensures parameter documentation matches function signatures

### Pyright Check (`pyright`)

Static type checking with Pyright:

- Type annotation validation
- Type inference checking
- Import resolution verification
- Generic type usage validation

## Version and Metadata Checks

### Version Check (`version`)

Ensures version consistency across project files:

- Validates `pyproject.toml` version format
- Checks for version mismatches between files
- Ensures semantic versioning compliance

### Citation Check (`citation`)

Validates academic citation metadata:

- Checks `CITATION.cff` format and completeness
- Validates author information
- Ensures proper citation metadata

## Configuration and CI Checks

### CI Matrix Check (`ci_matrix`)

Validates GitHub Actions CI configuration:

- Checks Python version matrix completeness
- Validates workflow syntax
- Ensures proper test matrix coverage

### Tests Check (`tests`)

Validates test suite configuration and coverage:

- Checks for test file presence
- Validates test configuration
- Ensures proper test structure

### Links Check (`links`)

Validates URLs in documentation and code:

- Checks external links for availability
- Validates internal references
- Detects broken documentation links

## Running Specific Checks

### Run Individual Checks

```bash
# Run only structure checks
preen check --only structure

# Run only code quality checks  
preen check --only ruff,codespell,pydoclint

# Skip specific checks
preen check --skip links,pyright
```

### Check Categories

Checks can be grouped by category:

- **structure**: `structure`, `deps`, `deptree`
- **quality**: `ruff`, `codespell`, `pydoclint`, `pyright`  
- **metadata**: `version`, `citation`
- **ci**: `ci_matrix`, `tests`
- **docs**: `links`

### Auto-fixing

Many checks support automatic fixing:

```bash
# Fix all auto-fixable issues
preen fix

# Fix specific check types
preen fix --only ruff,structure
```

## Check Configuration

Individual checks can be configured in your `pyproject.toml`:

```toml
[tool.preen]
# Enable/disable specific checks
enabled_checks = ["structure", "ruff", "version"]
disabled_checks = ["links", "pyright"]

# Check-specific configuration
[tool.preen.structure]
tests_at_root = true
examples_at_root = true
src_layout = false

[tool.preen.ruff]
target_version = "py312"
line_length = 88

[tool.preen.version]
enforce_semver = true
```

## Exit Codes

- **0**: All checks passed
- **1**: Some checks failed
- **2**: Configuration or runtime error

Use `--strict` mode to ensure any issues result in exit code 1.