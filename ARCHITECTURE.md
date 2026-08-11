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
  cap throughout (gross exposure as a multiple of equity), approximate rather
  than hard under a drift band — see `ScoreProportionalPortfolio` below; cash
  is an accounting balance, not a sizing constraint.

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
    `dollar_neutral=True` demeans every scored ticker (an exact `0.0` is a
    real reading, not a placeholder, so it takes part too) so signed weights
    sum to zero. `config.drift_band` is the no-trade region around the
    target: a ticker whose weight gap sits inside the band is left alone,
    which is the one lever this model has against turnover. It is a blunt
    one — a band wide enough to matter for a daily signal also filters the
    signal it is meant to trade. A nonzero band also softens `max_gross`:
    targets sum to the whole budget, but a banded ticker holds its current
    weight instead of moving to its target, so realized gross lands within
    `drift_band × n_scored` of the cap (4% of equity at `drift_band: 0.005`
    over 8 tickers).
  - `EqualWeightPortfolio` — deliberately the dumbest: a non-zero-scored
    ticker while flat takes an equal share of the remaining gross, then is
    never resized or closed. Exists so `BuyAndHoldStrategy` stays a genuine
    buy-and-hold reference rather than inheriting whatever the strategy
    portfolios do.

  Which one a run uses is chosen by `config.portfolio` via
  `portfolio/factory.py` (`inverse_vol` | `score_proportional` |
  `equal_weight`).

- **`execution/`** — two handlers, composed rather than alternative.
  `IdealExecutionHandler` fills at the current cached price and decides
  *where* a fill happens; `CostAwareExecutionHandler` wraps it and decides
  what that fill *costs*. `config.cost_bps` is the half-spread charged on a
  single fill, always adverse (a BUY lifts the offer, a SELL hits the bid),
  so a round trip pays twice it; `config.commission_bps` is charged on the
  filled notional at the cost-adjusted price. The spread is folded into
  `fill_price`, so equity, cash and realized PnL absorb it through the normal
  fill path — `FillEvent.slippage` records what was paid for reporting only
  and must never be subtracted again, or the cost is double-counted. Because
  the wrapper only touches fills, any future execution model gets costs for
  free. `runner.py` always wires the pair; costs default to `0.0`, so a
  config that names neither runs frictionless.

- **`risk/`** — `PositionExitRiskManager`: flattens a position on
  stop-loss, take-profit, or max-holding-days breach. Stateless — it reads
  entry price/date/quantity from the `Portfolio` via `PortfolioView` rather
  than replaying the fill stream.

- **`tracker/`** — `PerformanceTracker` (equity curve + metrics) and
  `report.py`/`plotting.py`, which render a multi-page PDF: an equity/
  drawdown chart with a trade-stats table and return-correlation heatmap, a
  monthly-returns heatmap, an optional Sharpe-vs-cost sensitivity page, and a
  full config dump. The overview page is also written out as a PNG beside the
  PDF, which is where the README's hero image comes from.

`runner.py` owns the wiring end to end, so the CLI
(`scripts/run_zscore_backtest.py`) and the cost sweep (`sweep.py`) build an
identical engine — the sweep re-runs the same config once per rung of a cost
ladder and interpolates the half-spread at which Sharpe crosses zero. The
sweep is opt-in via `--cost-sweep`, which folds it into the report as a
Sharpe-vs-cost page; there is no separate CLI for it.

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

- **No market impact or capacity model** — a fill assumes the entire order
  transacts at one price regardless of size. Cost is a fixed number of basis
  points per fill, so a $1m order and a $1bn order pay the same rate; there
  is no participation-rate or square-root impact term, and no notion of the
  strategy's capacity.
- **No ADV/volume-aware sizing** — `volume` is an optional column the data
  layer will read but nothing consumes. Position sizes are never capped
  against a ticker's average daily volume, so a backtest will happily size
  into liquidity that does not exist.
- **No per-ticker cost table** — `cost_bps`/`commission_bps` are single
  scalars applied to every ticker. A real universe has per-instrument
  spreads that differ by an order of magnitude, and a strategy trading the
  wide names pays far more than a flat rate implies.
- **No short borrow cost** — the flagship config runs dollar-neutral, which
  means roughly half the book is short at all times, and it currently shorts
  for free. No borrow fee, no hard-to-borrow constraint, no recall risk. On
  a book this size that is a real and permanently favorable omission.
- **Entry-referenced risk exits pair poorly with continuous rebalancing** —
  `PositionExitRiskManager`'s thresholds are relative to entry price, so a
  forced exit on a `ScoreProportionalPortfolio` position is simply
  re-entered at full size on the next bar if the score that sized it hasn't
  changed.
- **Single-threaded, single-process** — there's no concept of live/paper
  trading here; it's a research and reporting tool, not an execution
  system.
