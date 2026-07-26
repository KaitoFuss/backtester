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

`Engine` (`src/backtester/core/engine.py`) drives this synchronously: it pulls one bar at a time from the `DataHandler`, pushes it onto an in-memory `EventQueue` (`core/queue.py`), then drains the queue via `_dispatch`, which pattern-matches on event type. Every event rides the queue: a `MarketEvent` enqueues the `Strategy`'s single `SignalEvent` for the bar; that `SignalEvent` runs `Portfolio.process_signal` to build the bar's order batch, hands it to the optional `RiskManager.reconcile`, and enqueues the result; `OrderEvent`s and `FillEvent`s then flow through `process_order`/`process_fill`. `Strategy.process_market` returns exactly one `SignalEvent` per bar (its `scores` may be empty), which guarantees the `RiskManager` gets a reconcile pass every bar; the `Engine` stashes the `MarketEvent` in `_current_bar` so the `SignalEvent` stage can pass it to `reconcile`. The `RiskManager` is an order interceptor, not a queue stage: `reconcile(event, orders)` drops any strategy order on a ticker it is force-exiting (stop-loss/take-profit/max-holding) and appends its own exit orders — risk beats strategy. It reads position cost basis from the `Portfolio` via `PortfolioView`, so it holds no state of its own. `MarketEvent`s and `FillEvent`s are also handed to an optional `Tracker.track_market`/`track_fill` (non-blocking, no return) — currently that slot is occupied by `PerformanceTracker`.

Every component (`DataHandler`, `Strategy`, `Portfolio`, `ExecutionHandler`, `RiskManager`, `Tracker`) is a structural `Protocol` defined in `engine.py` itself — concrete implementations live in their own top-level package (`strategy/`, `portfolio/`, `execution/`) and only need to satisfy the shape, not inherit from anything. `engine.py` also defines two wiring protocols the `Engine` itself never calls: `PriceSource` (shared pull-based price lookup) and `PortfolioView` (read-only `get_position` + `mark_to_market`, used by the risk manager and performance tracker).

### Events (`core/events.py`)

All events are frozen dataclasses forming the `Event = MarketEvent | SignalEvent | OrderEvent | FillEvent` union, each with a `Literal` `type` tag (e.g. `"MARKET"`) used for the `match` dispatch in `Engine._dispatch`. `Ticker` is a soft type alias for `str`. Mapping-typed fields (`MarketEvent.bars`, `SignalEvent.scores`) are frozen into `MappingProxyType` in `__post_init__` for immutability, since the dataclasses themselves are frozen but dict values aren't automatically protected.

### Data layer (`data/`)

`ParquetMarketData` (`data/parquet_market_data.py`) reads one Parquet file per trading day from a directory (filename `YYYY-MM-DD.parquet`, validated fail-fast at construction), tickers as the row index, `close` required and `open`/`high`/`low`/`volume` optional per-file columns. Missing tickers in a given file are silently skipped rather than erroring — the data layer does not validate cross-ticker column consistency. A single instance is wired in twice: as the `Engine`'s `DataHandler` and as the shared `PriceSource` for `Portfolio`/`ExecutionHandler` (its price cache only reflects bars already consumed by the loop). `data/fetch_yfinance.py` downloads daily bars into that layout.

### Implemented components

- `strategy/`: `ZScoreMovingAverageStrategy` (mean-reversion on z-scored log returns) and `BuyAndHoldStrategy` (equal-weight benchmark).
- `portfolio/`: `VolWeightedPortfolio` — opens long/short positions weighted `score * target_vol / trailing σ` (signed conviction scaled to a target risk contribution per unit vol), capped — never scaled up, only down — to fit the gross still available under `max_gross` (the leverage limit: gross exposure as a multiple of equity). A candidate without a full `vol_window` of returns yet is skipped for that bar, no fallback. Cash is tracked as an accounting balance, not a sizing constraint — the leverage cap is. Held positions are never resized (flat→open→flat band trading); a sign flip / sub-`exit_threshold` / zero score closes; an absent ticker is held. `ScoreProportionalPortfolio` is the vol-free default: same open/hold/close semantics, sized `score / total abs score` normalized into the `max_gross` budget — only equal-weighted when every open candidate's score has the same magnitude, otherwise proportional to score — opening on the same bar a score first qualifies (no vol warm-up) — used for `BuyAndHoldStrategy`, which only signals a ticker once and would otherwise never get bought under `VolWeightedPortfolio`'s no-fallback rule.
- `execution/`: `IdealExecutionHandler` — fills at the current cached price, no slippage or commission.
- `tracker/`: `PerformanceTracker` (satisfies the `Tracker` protocol; equity curve + metrics) and `plotting.py` (equity/drawdown charts).
- `risk/`: `PositionExitRiskManager` (satisfies the `RiskManager` protocol) — flattens a position on stop-loss, take-profit, or max-holding-days breach. Stateless: it reads entry price/date/quantity from the `Portfolio` via `PortfolioView` (the `VolWeightedPortfolio` records cost basis per position) rather than replaying the fill stream.

`scripts/run_zscore_backtest.py` shows the full wiring. See `NOTES.md` sections 4–8 for the remaining open design questions (slippage/commission model, risk checks, richer performance metrics).

### Logging conventions

Every module that makes a trading decision logs it, at a level chosen so `INFO` alone reads as a clean trade blotter and `DEBUG` adds the full numeric trail behind each entry. Each module gets its own `logger = logging.getLogger(__name__)`; never add a function parameter or return value just to thread a logger or a log message through — log with whatever the function already has in scope.

- **DEBUG** — high-volume, per-bar/per-ticker computation: raw scores, vol estimates, threshold checks, warm-up progress, individual order fills, the MARKET → SIGNAL → ORDER → FILL pipeline in `Engine._dispatch`.
- **INFO** — state-changing or otherwise notable decisions: a position opened or closed (with the reason — sign flip, threshold, zero score), a risk exit (stop-loss/take-profit/max-holding), a gross-budget scale-down, a new ticker entering a strategy's universe, run start/end summaries, end-of-run liquidation.
- **WARNING** — data went missing where it was expected (e.g. no price for a held position when marking equity).
- **ERROR** — an order genuinely can't be filled (e.g. no price available at all).

Message format: a per-ticker/per-decision line leads with the ticker (e.g. `"%s: closing ..."`, matching `portfolio/utils.py`, `risk/exits.py`, `strategy/zscore_ma.py`) — never with `event.timestamp`, since the log record's own `asctime` already carries wall-clock time. Only the genuinely per-bar pipeline logs (`Engine._dispatch`'s MARKET/SIGNAL/ORDER/FILL trace, `tracker/metrics.py`'s equity marks) embed the backtest's simulated bar timestamp, since there it's the one piece of context the record doesn't otherwise carry.

Run at `-v`/`INFO` for a readable trade log; drop to `DEBUG` to retrace *why* a specific bar's decision came out the way it did.

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (60-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk go test             # Go test failures only (90%)
rtk jest                # Jest failures only (99.5%)
rtk vitest              # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk pytest              # Python test failures only (90%)
rtk rake test           # Ruby test failures only (90%)
rtk rspec               # RSpec test failures only (60%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%). Format flags (-c, -l, -L, -o, -Z) run raw.
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->