# Preen

Conformance and adoption CLI for the
[py-canon](https://github.com/gojiplus/py-canon) fleet standard.

py-canon defines the standard (copier template, reusable workflows, shared
Sphinx config); preen is how repos enter the fleet and stay in it.

## Quick start

```bash
uv tool install preen

preen new my-package     # scaffold a new package
preen adopt              # retrofit an existing repo
preen check              # conformance checks
preen release            # tag-driven release
```

```{toctree}
:maxdepth: 2
:caption: User Guide

installation
usage
checks
```
