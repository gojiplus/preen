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

## Requirements and evidence

Use py-canon's STANDARD.md as the authority for fleet policy. A new check must
identify the requirement and its scope, show a conforming and a violating
example, and test observable behavior. Changes to shared adoption defaults
must agree with py-canon's template and synchronization tests. Do not add a
second independent policy in the skill.

Keep detection separate from fixes. Test fixes against the original defect
and preserve project-owned configuration and data. Include the checker and
canon revisions, executed commands, omitted checks, and migration consequences
in review evidence. A passing subset is not a claim that every fleet
requirement has been checked.

## Pull requests

- Keep commits focused; write imperative commit messages.
- Add tests for new behavior — this repo follows TDD.
- `uv run preen check` must pass on this repo before merging: preen
  dogfoods the same conformance standard it enforces on other repos.

## License

By contributing, you agree your contributions are licensed under the MIT
license.
