# Architecture

Event-driven backtesting engine for equity strategies. Single-threaded,
deterministic, built around structural typing (`Protocol`) rather than a
plugin/inheritance framework.

## Event loop

```
DataHandler → [MarketEvent] → Strategy → [SignalEvent] → Portfolio → [OrderEvent] → ExecutionHandler → [FillEvent] → Portfolio
```

`Engine` (`src/backtester/core/engine.py`) drives this synchronously. Pulls
one bar at a time from `DataHandler`, pushes it onto in-memory `EventQueue`
(`core/queue.py`), drains queue via `_dispatch`, which pattern-matches on
event type.

Every event rides the queue. A `MarketEvent` enqueues `Strategy`'s single
`SignalEvent` for the bar. That `SignalEvent` runs `Portfolio.process_signal`
to build the bar's order batch, hands it to optional `RiskManager.reconcile`,
enqueues result. Resulting orders and fills flow through
`process_order`/`process_fill`. `Strategy.process_market` returns exactly one
`SignalEvent` per bar (its `scores` may be empty), guaranteeing `RiskManager`
gets a reconcile pass every bar.

`RiskManager` is an order interceptor, not a queue stage.
`reconcile(event, orders)` drops any strategy order on a ticker it is
force-exiting (stop-loss / take-profit / max-holding) and appends its own
exit orders — risk beats strategy. Reads position cost basis from `Portfolio`
via read-only `PortfolioView`, so holds no state of its own.

Every `MarketEvent` and `FillEvent` also goes to optional
`Tracker.track_market` / `track_fill` (non-blocking, no return). That slot
currently holds `PerformanceTracker`.

## Protocols and wiring

Every component (`DataHandler`, `Strategy`, `Portfolio`, `ExecutionHandler`,
`RiskManager`, `Tracker`) is a structural `Protocol` defined in `engine.py`
itself. Concrete implementations live in their own top-level package
(`strategy/`, `portfolio/`, `execution/`) and need only satisfy the shape,
not inherit anything.

`engine.py` also defines two wiring protocols `Engine` never calls directly:
`PriceSource` (shared pull-based price lookup used by `Portfolio` and
`ExecutionHandler`) and `PortfolioView` (read-only `get_position` +
`mark_to_market`, used by risk manager and performance tracker).

## Events (`core/events.py`)

All events are frozen dataclasses forming the
`Event = MarketEvent | SignalEvent | OrderEvent | FillEvent` union, each with
a `Literal` `type` tag (e.g. `"MARKET"`) used for `match` dispatch in
`Engine._dispatch`. Mapping-typed fields (`MarketEvent.bars`,
`SignalEvent.scores`) are frozen into `MappingProxyType` on construction for
immutability: the dataclasses are frozen but dict values are not
automatically protected.

## Data layer (`data/`)

`FrameMarketData` reads one tidy Parquet file — one row per `(date, ticker)`,
columns `date, ticker, open, high, low, close, volume`, `close` required and
`open`/`high`/`low`/`volume` optional per row. Whole history is read once at
construction, filtered to config's universe, grouped by date into the run's
`MarketEvent` list. A backtest costs one file open, not one per trading day.
A row whose optional fields are null yields a `Bar` without them. A ticker
with no row on a day has no bar at all, so the data layer never fabricates a
price and does not validate cross-ticker column consistency.

A single instance is wired in twice: as `Engine`'s `DataHandler` and as the
shared `PriceSource` for `Portfolio`/`ExecutionHandler`. `get_price` reads a
cache that `get_next_bar` populates, so it only ever reflects bars already
consumed by the loop — that is what keeps execution from reading ahead.
`data/fetch_yfinance.py` downloads daily bars into that layout, sorted by
date then ticker, overwriting the target file wholesale so a previous fetch
with a different universe cannot leak into the current one.

## Components

- **`strategy/`** — `ZScoreMovingAverageStrategy` (mean-reversion on z-scored
  log returns) and `BuyAndHoldStrategy` (equal-weight benchmark).

- **`portfolio/`** — three implementations over a deliberately thin
  `BasePortfolio`, which owns only cash, positions, `mark_to_market` and
  `process_fill`. Each portfolio writes its own `process_signal`, because an
  order means something different under band trading (a one-shot open) than
  under rebalancing (a delta toward a target). `max_gross` is the leverage cap
  throughout (gross exposure as multiple of equity), approximate rather than
  hard under a drift band — see `ScoreProportionalPortfolio` below. Cash is an
  accounting balance, not a sizing constraint.

  - `InverseVolPortfolio` — **band trading, sized purely by risk**. Weight is
    `sign(score) / trailing σ`, normalized so the batch of new opens exactly
    fills the gross still available under `max_gross`. Score gates and directs
    but never sizes — a score of 0.6 and a score of 3.0 open the same
    position. Held positions are never resized (flat → open → flat). Under
    its own signal logic, a position closes when its score signed into the
    held direction falls below `exit_threshold` — independent of that,
    `RiskManager` can force-exit on stop-loss/take-profit/max-holding, and
    any open position is liquidated at run end.
  - `ScoreProportionalPortfolio` — **continuous rebalancing, sized by raw
    conviction**. Every bar it rebuilds the whole target book
    (`score / total abs score` into the available budget, no entry/exit gate —
    any nonzero score carries some weight) and emits the *delta* against what
    is held, so
    a weight always reflects today's score rather than the score on the bar
    the position opened. Under its own signal logic, a reversal is conviction
    the other way, so the position crosses zero in a single order instead of
    closing — independent of that, `RiskManager` and end-of-run liquidation
    still apply on the strategy leg.
    `dollar_neutral=True` demeans every scored ticker (an exact `0.0` is a
    real reading, not a placeholder, so it takes part too) so signed weights
    sum to zero. `config.drift_band` is the no-trade region around the target:
    a ticker whose weight gap sits inside the band is left alone. That is the
    one lever this model has against turnover, and a blunt one — a band wide
    enough to matter for a daily signal also filters the signal it is meant to
    trade. A nonzero band also softens `max_gross`: targets sum to the whole
    budget, but a banded ticker holds its current weight instead of moving to
    its target, so realized gross lands within `drift_band × n_scored` of the
    cap (4% of equity at `drift_band: 0.005` over 8 tickers).
  - `EqualWeightPortfolio` — deliberately the dumbest. A non-zero-scored
    ticker while flat takes an equal share of remaining gross, then is never
    resized or closed by its own signal logic — `runner.py` wires no
    `RiskManager` onto the benchmark leg either, so in practice only
    `Engine`'s end-of-run liquidation ever closes it. Exists so
    `BuyAndHoldStrategy` stays a genuine
    buy-and-hold reference rather than inheriting whatever the strategy
    portfolios do.

  `config.portfolio` picks one via `portfolio/factory.py` (`inverse_vol` |
  `score_proportional` | `equal_weight`).

- **`execution/`** — two handlers, composed rather than alternative.
  `IdealExecutionHandler` fills at the current cached price and decides
  *where* a fill happens. `CostAwareExecutionHandler` wraps it and decides
  what that fill *costs*. `config.cost_bps` is the half-spread charged on a
  single fill, always adverse (a BUY lifts the offer, a SELL hits the bid), so
  a round trip pays twice it. `config.commission_bps` is charged on the filled
  notional at the cost-adjusted price. The spread is folded into `fill_price`,
  so equity, cash and realized PnL absorb it through the normal fill path —
  `FillEvent.slippage` records what was paid for reporting only and must never
  be subtracted again, or the cost is double-counted. Because the wrapper only
  touches fills, any future execution model gets costs for free. `runner.py`
  always wires the pair. Costs default to `0.0`, so a config naming neither
  runs frictionless.

- **`risk/`** — `PositionExitRiskManager`: flattens a position on stop-loss,
  take-profit, or max-holding-days breach. Stateless — reads entry
  price/date/quantity from `Portfolio` via `PortfolioView` rather than
  replaying the fill stream.

- **`tracker/`** — `PerformanceTracker` (equity curve + metrics) and
  `report.py`/`plotting.py`, which render a multi-page PDF: equity/drawdown
  chart with trade-stats table and return-correlation heatmap, monthly-returns
  heatmap, optional Sharpe-vs-cost sensitivity page, full config dump. The
  overview page is also written out as a PNG beside the PDF, which is where
  the README's hero image comes from.

  Two metric conventions are worth stating outright, because both legs of a
  report are measured by them. **Sharpe** is the arithmetic mean *excess*
  period return over the standard deviation of those excess returns,
  annualized by the square root of the observed return frequency. The excess
  is taken against `config.risk_free_rate` (annualized, de-annualized
  geometrically to the period), which the shipped configs set to `0.02`. It is
  deliberately *not* `annualized_return / annualized_vol` — `annualized_return`
  remains a geometric CAGR off elapsed calendar time, and the two answer
  different questions, so both appear in the report. **Turnover** is gross
  traded notional (every fill counted once, so a full round trip of the book
  counts twice) divided by average equity and by elapsed years — an annual
  rate, not a whole-period total. It is never halved.

`runner.py` owns the wiring end to end, so the CLI
(`scripts/run_zscore_backtest.py`) and the cost sweep (`sweep.py`) build an
identical engine. The sweep re-runs the same config once per rung of a cost
ladder and interpolates the half-spread at which Sharpe crosses zero. It is
opt-in via `--cost-sweep`, which folds it into the report as a Sharpe-vs-cost
page. There is no separate CLI for it.

## Logging conventions

Every module making a trading decision logs it, at a level chosen so `INFO`
alone reads as a clean trade blotter and `DEBUG` adds the full numeric trail
behind each entry.

- **DEBUG** — high-volume, per-bar/per-ticker computation: raw scores, vol
  estimates, threshold checks, warm-up progress, individual fills, the
  MARKET → SIGNAL → ORDER → FILL pipeline.
- **INFO** — every actual trade (open, close, risk exit, end-of-run
  liquidation), gross-budget scale-downs, a new ticker entering a strategy's
  universe, run start/end summaries.
- **WARNING** — data missing where expected (e.g. no price for a held
  position when marking equity).
- **ERROR** — an order genuinely cannot be filled.

Every log line leads with the backtest's *simulated* timestamp, not
wall-clock time — that is what makes a run's log retraceable against the data.
Every trade goes through a single `log_trade(...)` helper
(`core/trade_log.py`), one column-aligned line each:

```
2016-03-10 00:00:00  OPEN      BUY  UUP    qty=  2175  price=     24.9700  score=2.295 weight=0.54301
2016-03-11 00:00:00  CLOSE     BUY  FXE    qty=   418  price=    109.0100  signed score=-1.204 below exit_threshold=0.000
2021-06-14 00:00:00  REBALANCE BUY  QQQ    qty=   489  price=    105.1100  weight=1.00000 qty 509 -> 998
2024-11-02 00:00:00  RISK_EXIT SELL AAPL   qty=   340  price=    172.1100  stop_loss
2024-12-31 00:00:00  LIQUIDATE SELL SPY    qty=    62  price=    586.0800  end of backtest run
```

Run at `-v`/`INFO` for a readable trade log. Drop to `DEBUG` to retrace *why*
a specific bar's decision came out the way it did.

## Not modeled

This engine intentionally stops short of things a production system would
need:

- **No market impact or capacity model** — a fill assumes the entire order
  transacts at one price regardless of size. Cost is a fixed number of basis
  points per fill, so a $1m order and a $1bn order pay the same rate. No
  participation-rate or square-root impact term, no notion of the strategy's
  capacity.
- **No ADV/volume-aware sizing** — `volume` is an optional column the data
  layer reads but nothing consumes. Position sizes are never capped against a
  ticker's average daily volume, so a backtest will happily size into
  liquidity that does not exist.
- **No per-ticker cost table** — `cost_bps`/`commission_bps` are single
  scalars applied to every ticker. A real universe has per-instrument spreads
  differing by an order of magnitude, and a strategy trading the wide names
  pays far more than a flat rate implies.
- **No short borrow cost** — the flagship config runs dollar-neutral, so
  roughly half the book is short at all times, and it currently shorts for
  free. No borrow fee, no hard-to-borrow constraint, no recall risk. On a book
  this size that is a real and permanently favorable omission.
- **Entry-referenced risk exits pair poorly with continuous rebalancing** —
  `PositionExitRiskManager`'s thresholds are relative to entry price, so a
  forced exit on a `ScoreProportionalPortfolio` position is simply re-entered
  at full size on the next bar if the score that sized it has not changed.
- **Single-threaded, single-process** — no concept of live/paper trading here.
  Research and reporting tool, not an execution system.
