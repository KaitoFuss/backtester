# Architecture

This is an event-driven backtesting engine for equity strategies:
single-threaded, deterministic, and built around structural typing
(`Protocol`) rather than a plugin/inheritance framework.

## Event loop

```
DataHandler → [MarketEvent] → Strategy → [SignalEvent] → Portfolio → [OrderEvent] → ExecutionHandler → [FillEvent] → Portfolio
```

`Engine` (`src/backtester/core/engine.py`) drives this synchronously: it
pulls one bar at a time from the `DataHandler`, pushes it onto an in-memory
`EventQueue` (`core/queue.py`), then drains the queue via `_dispatch`, which
pattern-matches on event type.

Every event rides the queue. A `MarketEvent` enqueues the `Strategy`'s single
`SignalEvent` for the bar; that `SignalEvent` runs `Portfolio.process_signal`
to build the bar's order batch, hands it to the optional
`RiskManager.reconcile`, and enqueues the result; the resulting orders and
fills then flow through `process_order`/`process_fill`.
`Strategy.process_market` returns exactly one `SignalEvent` per bar (its
`scores` may be empty), which guarantees the `RiskManager` gets a reconcile
pass every bar.

The `RiskManager` is an order interceptor, not a queue stage:
`reconcile(event, orders)` drops any strategy order on a ticker it is
force-exiting (stop-loss / take-profit / max-holding) and appends its own
exit orders — risk beats strategy. It reads position cost basis from the
`Portfolio` via a read-only `PortfolioView`, so it holds no state of its own.

Every `MarketEvent` and `FillEvent` is also handed to an optional
`Tracker.track_market` / `track_fill` (non-blocking, no return) — currently
that slot is occupied by `PerformanceTracker`.

## Protocols and wiring

Every component (`DataHandler`, `Strategy`, `Portfolio`, `ExecutionHandler`,
`RiskManager`, `Tracker`) is a structural `Protocol` defined in `engine.py`
itself — concrete implementations live in their own top-level package
(`strategy/`, `portfolio/`, `execution/`) and only need to satisfy the shape,
not inherit from anything.

`engine.py` also defines two wiring protocols the `Engine` itself never
calls directly: `PriceSource` (a shared pull-based price lookup used by
`Portfolio` and `ExecutionHandler`) and `PortfolioView` (read-only
`get_position` + `mark_to_market`, used by the risk manager and performance
tracker).

## Events (`core/events.py`)

All events are frozen dataclasses forming the
`Event = MarketEvent | SignalEvent | OrderEvent | FillEvent` union, each with
a `Literal` `type` tag (e.g. `"MARKET"`) used for the `match` dispatch in
`Engine._dispatch`. Mapping-typed fields (`MarketEvent.bars`,
`SignalEvent.scores`) are frozen into `MappingProxyType` on construction for
immutability, since the dataclasses themselves are frozen but dict values
aren't automatically protected.

## Data layer (`data/`)

`ParquetMarketData` reads one Parquet file per trading day from a directory
(filename `YYYY-MM-DD.parquet`), tickers as the row index, `close` required
and `open`/`high`/`low`/`volume` optional per file. Missing tickers in a
given file are silently skipped rather than erroring — the data layer does
not validate cross-ticker column consistency. A single instance is wired in
twice: as the `Engine`'s `DataHandler` and as the shared `PriceSource` for
`Portfolio`/`ExecutionHandler` (so its price cache only ever reflects bars
already consumed by the loop). `data/fetch_yfinance.py` downloads daily bars
into that layout.

## Components

- **`strategy/`** — `ZScoreMovingAverageStrategy` (mean-reversion on
  z-scored log returns) and `BuyAndHoldStrategy` (equal-weight benchmark).

- **`portfolio/`** — three implementations over a deliberately thin
  `BasePortfolio`, which owns only cash, positions, `mark_to_market` and
  `process_fill`. Each portfolio writes its own `process_signal`, because an
  order means something different under band trading (a one-shot open) than
  under rebalancing (a delta toward a target). `max_gross` is the leverage
  cap throughout (gross exposure as a multiple of equity); cash is an
  accounting balance, not a sizing constraint.

  - `InverseVolPortfolio` — **band trading, sized purely by risk**. Weight
    is `sign(score) / trailing σ`, normalized so the batch of new opens
    exactly fills the gross still available under `max_gross`. The score
    gates and directs but never sizes — a score of 0.6 and a score of 3.0
    open the same position. Held positions are never resized (flat → open →
    flat); a position closes when its score signed into the held direction
    falls below `exit_threshold`.
  - `ScoreProportionalPortfolio` — **continuous rebalancing, sized by raw
    conviction**. Every bar it rebuilds the whole target book
    (`score / total abs score` into the available budget, no entry/exit gate
    — any nonzero score carries some weight) and emits the *delta* against
    what is held, so a weight always reflects today's score rather than the
    score on the bar the position opened. A reversal is conviction the other
    way, so the position crosses zero in a single order instead of closing.
    `dollar_neutral=True` demeans the surviving scores so signed weights sum
    to zero.
  - `EqualWeightPortfolio` — deliberately the dumbest: a non-zero-scored
    ticker while flat takes an equal share of the remaining gross, then is
    never resized or closed. Exists so `BuyAndHoldStrategy` stays a genuine
    buy-and-hold reference rather than inheriting whatever the strategy
    portfolios do.

  Which one a run uses is chosen by `config.portfolio` via
  `portfolio/factory.py` (`inverse_vol` | `score_proportional` |
  `equal_weight`).

- **`execution/`** — `IdealExecutionHandler`: fills at the current cached
  price, no slippage or commission.

- **`risk/`** — `PositionExitRiskManager`: flattens a position on
  stop-loss, take-profit, or max-holding-days breach. Stateless — it reads
  entry price/date/quantity from the `Portfolio` via `PortfolioView` rather
  than replaying the fill stream.

- **`tracker/`** — `PerformanceTracker` (equity curve + metrics) and
  `report.py`/`plotting.py`, which render a multi-page PDF: an equity/
  drawdown chart with a trade-stats table and return-correlation heatmap, a
  monthly-returns heatmap, and a full config dump.

`scripts/run_zscore_backtest.py` shows the full wiring end to end.

## Logging conventions

Every module that makes a trading decision logs it, at a level chosen so
`INFO` alone reads as a clean trade blotter and `DEBUG` adds the full
numeric trail behind each entry.

- **DEBUG** — high-volume, per-bar/per-ticker computation: raw scores, vol
  estimates, threshold checks, warm-up progress, individual fills, the
  MARKET → SIGNAL → ORDER → FILL pipeline.
- **INFO** — every actual trade (open, close, risk exit, end-of-run
  liquidation), gross-budget scale-downs, a new ticker entering a
  strategy's universe, and run start/end summaries.
- **WARNING** — data went missing where it was expected (e.g. no price for
  a held position when marking equity).
- **ERROR** — an order genuinely can't be filled.

Every log line leads with the backtest's *simulated* timestamp, not
wall-clock time — that's what makes a run's log retraceable against the
data. Every trade goes through a single `log_trade(...)` helper
(`core/trade_log.py`), one column-aligned line each:

```
2016-03-10 00:00:00  OPEN      BUY  UUP    qty=  2175  price=     24.9700  score=2.295 weight=0.54301
2016-03-11 00:00:00  CLOSE     BUY  FXE    qty=   418  price=    109.0100  signed score=-1.204 below exit_threshold=0.000
2021-06-14 00:00:00  REBALANCE BUY  QQQ    qty=   489  price=    105.1100  weight=1.00000 qty 509 -> 998
2024-11-02 00:00:00  RISK_EXIT SELL AAPL   qty=   340  price=    172.1100  stop_loss
2024-12-31 00:00:00  LIQUIDATE SELL SPY    qty=    62  price=    586.0800  end of backtest run
```

Run at `-v`/`INFO` for a readable trade log; drop to `DEBUG` to retrace
*why* a specific bar's decision came out the way it did.

## Not modeled

This engine intentionally stops short of a few things a production system
would need:

- **No slippage or commission** — `IdealExecutionHandler` fills every order
  at the current cached price.
- **No turnover control on `ScoreProportionalPortfolio`** — it rebalances
  to the exact target weight every bar with no drift band, so turnover is
  uncontrolled by design; that would be the one place to add one.
- **Entry-referenced risk exits pair poorly with continuous rebalancing** —
  `PositionExitRiskManager`'s thresholds are relative to entry price, so a
  forced exit on a `ScoreProportionalPortfolio` position is simply
  re-entered at full size on the next bar if the score that sized it hasn't
  changed.
- **Single-threaded, single-process** — there's no concept of live/paper
  trading here; it's a research and reporting tool, not an execution
  system.
