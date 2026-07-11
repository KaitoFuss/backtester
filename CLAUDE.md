# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

For any file search or grep in the current git-indexed directory, use fff tools.

```bash
uv sync                      # install/sync deps into .venv (run after pyproject.toml dependency changes)
uv run ruff format .         # auto-format
uv run ruff check . --fix    # lint, autofix what's safe
uv run mypy .                # strict type check
uv run pytest                # full test suite (with coverage; config in pyproject.toml)
uv run pytest tests/core/test_engine.py::test_name   # single test
```

Run format → lint → mypy → pytest, in that order, after any source change (see `.claude/skills/python-check`). Dependencies are added via `uv add` / `uv add --dev`, never by hand-editing `pyproject.toml`.

Full coding conventions (typing strictness, Protocol-over-ABC preference, no-comments-by-default, test style) are in `.claude/skills/python-conventions/SKILL.md` — read it before adding new modules or public APIs.

## Architecture

This is an event-driven backtesting engine for factor-model equity strategies (see `NOTES.md` for the full design rationale and open questions — check it before making architectural decisions).

### Event loop

```
DataHandler → [MarketEvent] → Strategy → [SignalEvent] → Portfolio → [OrderEvent] → ExecutionHandler → [FillEvent] → Portfolio
```

`Engine` (`src/backtester/core/engine.py`) drives this synchronously: it pulls one bar at a time from the `DataHandler`, pushes it onto an in-memory `EventQueue` (`core/queue.py`), then drains the queue via `_dispatch`, which pattern-matches on event type and routes to the corresponding component method (`process_market`, `process_signal`, `process_order`, `process_fill`). A `FillEvent` is also handed to an optional `RiskManager.evaluate_fill` (non-blocking, observer-only) before the portfolio processes it.

Every component (`DataHandler`, `Strategy`, `Portfolio`, `ExecutionHandler`, `RiskManager`) is a structural `Protocol` defined in `engine.py` itself — concrete implementations live in their own top-level package (`strategy/`, `portfolio/`, `execution/`, `risk/`) and only need to satisfy the shape, not inherit from anything.

**Known gap:** `engine.py`'s `DataHandler` protocol expects `get_next_bar() -> MarketEvent | None`, but `data/base.py`'s `DataHandlerProtocol` (implemented by `ParquetHandler`) is iterator-based (`__iter__`/`__next__`). These were never reconciled — `Engine` cannot yet drive `ParquetHandler` directly.

### Events (`core/events.py`)

All events are frozen dataclasses forming the `Event = MarketEvent | SignalEvent | OrderEvent | FillEvent` union, each with a `Literal` `type` tag (e.g. `"MARKET"`) used for the `match` dispatch in `Engine._dispatch`. `Ticker` is a soft type alias for `str`. Mapping-typed fields (`MarketEvent.bars`, `SignalEvent.scores`) are frozen into `MappingProxyType` in `__post_init__` for immutability, since the dataclasses themselves are frozen but dict values aren't automatically protected.

### Data layer (`data/`)

`ParquetHandler` reads one Parquet file per trading day from a directory (filename `YYYY-MM-DD.parquet`), tickers as the row index, `close` required and `open`/`high`/`low`/`volume` optional per-file columns. Missing tickers in a given file are silently skipped rather than erroring — the data layer does not validate cross-ticker column consistency.

### Still unimplemented

`strategy/`, `portfolio/`, `execution/`, `risk/`, and `performance/` packages don't exist yet — only their `Protocol` shapes are defined in `core/engine.py`. See `NOTES.md` sections 4–8 for the open design questions on each (position sizing, slippage/commission model, risk checks, performance metrics).
