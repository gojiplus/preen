# Installation

## Requirements

- Python 3.12 or higher
- pip or uv for package installation

## Install from PyPI

```bash
pip install preen
```

## Install with uv

```bash
uv add preen
```

## Development Installation

For contributing to preen or using the latest development version:

```bash
# Clone the repository
git clone https://github.com/gojiplus/preen.git
cd preen

# Install in development mode
pip install -e .

# Or with uv
uv sync
```

## Verify Installation

Check that preen is correctly installed:

```bash
preen --version
preen --help
```

## Optional Dependencies

For development and testing:

```bash
# Install with development dependencies
pip install preen[dev]

# Or with uv
uv sync --all-extras
```

This includes:
- pytest and pytest-cov for testing
- All documentation dependencies for building docs