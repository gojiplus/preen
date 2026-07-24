# Contributing

## Dev setup

```bash
git clone https://github.com/gojiplus/preen
cd preen
uv sync --all-groups
```

## Tests and lint

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pydoclint src/
```

## Pull requests

- Keep commits focused; write imperative commit messages.
- Add tests for new behavior — this repo follows TDD.
- `uv run preen check` must pass on this repo before merging: preen
  dogfoods the same conformance standard it enforces on other repos.

## License

By contributing, you agree your contributions are licensed under the MIT
license.
