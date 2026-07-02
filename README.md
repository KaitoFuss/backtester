# backtester

A Python backtesting project.

## Requirements

- [uv](https://docs.astral.sh/uv/) for dependency, environment, and build
  management. `uv` will also install and pin the correct Python version
  (3.12, see `.python-version`) automatically.

## Setup

```bash
uv sync
```

This creates a `.venv/` and installs runtime and dev dependencies from the
lockfile.

## Development workflow

```bash
uv run ruff format .        # format
uv run ruff check . --fix   # lint
uv run mypy .                # strict type check
uv run pytest                # tests
```

Optionally, install the pre-commit hooks so formatting/linting run
automatically on `git commit`:

```bash
uv run --with pre-commit pre-commit install
```

## Project structure

```
src/backtester/   # library source (src layout)
tests/            # tests, mirroring src/backtester/ module paths
pyproject.toml    # project metadata, dependencies, and tool config
                   # (ruff, mypy, pytest, coverage all configured here)
```

## Conventions

Type checking runs in `mypy --strict` mode and linting is handled by `ruff`
(rule set and config in `pyproject.toml`). See
`.claude/skills/python-conventions/SKILL.md` for the full coding conventions
used in this repo, and `.claude/skills/python-check/SKILL.md` for the
required check sequence after any code change.
