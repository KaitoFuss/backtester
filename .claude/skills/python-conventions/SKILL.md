---
name: python-conventions
description: Coding conventions for this repo (src layout, strict typing, docstring/comment policy, dependency management with uv). Read before adding new modules, functions, or public APIs in src/backtester.
---

# Python conventions for this repo

## Layout

- Package code lives under `src/backtester/`, tests under `tests/` (mirroring
  module paths, e.g. `src/backtester/engine.py` -> `tests/test_engine.py`).
- `src/backtester/py.typed` marks the package as typed — keep it; it's what
  lets downstream users and mypy treat this package's types as authoritative.
- No `__main__.py` / CLI entry point unless the user asks for one.

## Typing

- `mypy --strict` is enforced (see `[tool.mypy]` in `pyproject.toml`). Every
  function needs a full signature: typed parameters and an explicit return
  type, including `-> None`.
- Prefer precise types over `Any`. Use `Protocol` for structural interfaces
  (e.g. a `Strategy` or `DataFeed` interface) instead of ABCs when only
  duck-typed behavior is required.
- Use modern built-in generics (`list[float]`, `dict[str, int]`, `X | None`)
  — not `typing.List`/`typing.Optional`. `target-version = py312` in ruff
  enforces this via the `UP` (pyupgrade) rule set.

## Style

- Formatting and import order are handled entirely by `ruff format` /
  `ruff check --fix` (isort rules included). Never hand-format.
- Follow this repo's no-comments-by-default policy: code should read from
  names; add a comment only to explain a non-obvious *why* (a numerical
  stability trick, an off-by-one in bar-close handling, a broker-API quirk),
  never to restate *what* the code does.
- No docstrings on trivial functions. Add one only when the behavior isn't
  obvious from the signature and name (e.g. a non-standard return-on-cash
  convention, or how a lookahead-bias guard works).

## Dependencies

- Manage all dependencies with `uv add` / `uv add --dev` / `uv remove` —
  never edit `pyproject.toml` dependency arrays by hand and never `pip
  install` directly into `.venv`.
- Keep runtime dependencies (`[project.dependencies]`) minimal; anything only
  needed for linting/typing/testing belongs in the `dev` group under
  `[dependency-groups]`.

## Tests

- Use `pytest` with plain `assert` statements (no `unittest.TestCase`
  classes).
- Test files/functions need type annotations too (`-> None` on test
  functions) except where relaxed — see the `tool.mypy.overrides` block for
  `tests.*` in `pyproject.toml`.
- Don't write tests for trivial scaffolding (e.g. "does the package import");
  write tests when there is actual behavior to pin down — e.g. P&L
  calculations, order-matching logic, edge cases in date/bar alignment.

See also the [[python-check]] skill for the run-this-after-every-change
command sequence.
