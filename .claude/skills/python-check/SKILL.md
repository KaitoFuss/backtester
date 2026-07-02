---
name: python-check
description: Run this repo's format/lint/typecheck/test suite (ruff format, ruff check, mypy, pytest via uv) after writing or editing Python code, and before telling the user a Python change is complete. Use whenever files under src/ or tests/ change.
---

# Python quality check

This project uses `uv` for environment/dependency management, `ruff` for
formatting and linting, `mypy --strict` for type checking, and `pytest` for
tests. All config lives in `pyproject.toml` — do not create separate config
files (`setup.cfg`, `.flake8`, `mypy.ini`, etc.).

## Workflow

Run these in order after any Python source change, before reporting the work
as done:

```bash
uv run ruff format .        # auto-format
uv run ruff check . --fix   # lint, autofix what's safe
uv run mypy .                # strict type check
uv run pytest                # tests (only if tests/ has content)
```

If `uv sync` hasn't been run yet in this session (e.g. after editing
`pyproject.toml` dependencies), run it first so the lockfile and venv stay in
sync:

```bash
uv sync
```

## Fixing failures

- **ruff format**: just let it rewrite the file; never hand-format to match
  ruff's style.
- **ruff check**: fix the underlying issue. Don't add `# noqa` suppressions
  unless the rule is a genuine false positive — explain why in a comment if
  you do.
- **mypy**: this repo runs `strict = true`. Don't silence errors with `# type:
  ignore` or `Any` as a first resort — fix the type. Reach for `# type:
  ignore[code]` (always with an explicit error code) only when a third-party
  library genuinely lacks types.
- **pytest**: a failing test means either the code or the test is wrong —
  figure out which before changing either.

## Adding dependencies

Use `uv add <package>` for runtime deps and `uv add --dev <package>` for
dev-only tooling (test/lint/type-check libraries) — don't hand-edit the
`dependencies` or `[dependency-groups]` arrays in `pyproject.toml`. This keeps
`uv.lock` in sync automatically.
