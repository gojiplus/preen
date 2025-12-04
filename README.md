# preen

*An opinionated, agentic CLI for Python package hygiene and release.*

`preen` helps Python package maintainers keep their metadata, configuration files and workflows in sync.  It reads information from your `pyproject.toml` and regenerates derived files such as GitHub Actions workflows, documentation configuration and a `CITATION.cff` file.  The tool is intended as the last step before a release to ensure that everything is consistent and ready for publication.

This repository contains the early implementation of `preen`.  The current scope focuses on the sync functionality, which reads a project's metadata and writes a set of standardised files.  Future versions will add an interactive check runner, initialisation helpers and release workflows as described in the vision.
