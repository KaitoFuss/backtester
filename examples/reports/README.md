# Example reports

Two committed sample runs of z-score mean-reversion strategy
(`ZScoreMovingAverageStrategy`), each benchmarked against equal-weight
buy-and-hold on same 8-ETF universe (`SPY QQQ TLT IEF GLD DBC UUP FXE`,
2015-01-01 to 2025-01-01, daily bars from yfinance).

Both runs charge costs their config ships with: **1.0 bp half-spread per fill
(`cost_bps`) plus 0.5 bp commission (`commission_bps`)**. Every number below
is after those costs.

Score Scaling Neutral's config carries `drift_band: 0.005` — a 50 bp
rebalancing no-trade band, live because `ScoreProportionalPortfolio`
retrades a target delta every bar. Vol Sized's config omits it: its
`inverse_vol` model never resizes a held position, so there is nothing to
band. Vol Sized's config instead carries `stop_loss_pct` / `take_profit_pct`
/ `max_holding_days` — entry-referenced risk exits that pair with band
trading's flat→open→flat lifecycle but would just be re-entered next bar
under continuous rebalancing, so Score Scaling Neutral's config leaves them
unset.

| | Config | Portfolio model | Total return | Sharpe | Max DD | Annual turnover | Breakeven |
|---|---|---|---|---|---|---|---|
| [Score Scaling Neutral](score_scaling_neutral_report.pdf) | `configs/zscore_rebalanced_neutral.json` | `score_proportional`, dollar-neutral | -37.6% | -0.37 | -40.9% | ~689x | 0.19 bp |
| [Vol Sized](vol_sized_report.pdf) | `configs/zscore_backtest.json` | `inverse_vol`, band trading | -25.3% | -0.25 | -45.0% | ~163x | none |
| Buy & Hold (both reports) | — | `equal_weight` | +83.6% | 0.52 | -18.4% | ~0.2x | — |

Sharpe is computed against a **2% annualized risk-free rate**
(`config.risk_free_rate`, which both shipped configs set): mean excess daily
return over standard deviation of daily returns, annualized by square root of
observed return frequency. Benchmark leg is measured against same rate, so
its 0.52 is an excess-return Sharpe too, not a raw one. Turnover is **gross
traded notional per year** as multiple of equity: every fill counted once, so
a full round trip of the book counts twice. It is not halved. Reports print
that same annualized figure.

## What the cost curve shows

With no costs charged, Score Scaling Neutral returns **+74.9% at a Sharpe of
0.32**. It rebalances to its exact target weights every bar and turns over
roughly 689x its equity per year — including with the config's 50 bp
`drift_band` no-trade region live (see below), which does not materially
reduce this turnover. At that turnover level, the frictionless result sits
entirely inside the cost term.

Breakeven half-spread is the relevant figure: holding the shipped 0.5 bp
commission fixed and sweeping `cost_bps`, Sharpe crosses zero at **0.19 bp**,
roughly **0.7 bp of total cost per fill**. That is under a cent on a $100
ETF, and below typical ETF bid-ask spreads before commission, borrow, or
market impact. At this turnover, the frictionless return is a function of
the zero-cost assumption rather than an edge that survives realistic
trading costs.

Vol Sized has no breakeven: it is unprofitable (-4.9% return, Sharpe -0.09)
even with costs at zero, so there is no positive result for costs to erode.
Its turnover is roughly 4x lower than the neutral book's, and its return
degrades roughly 4x more slowly as costs increase.

Shipped 50 bp band barely moves it — most bars, target weight moves more than
that, band rarely fires. Widen band to 75% of equity (`drift_band=0.75`),
different story: turnover 689x → ~123x/yr, trades 14,998 → 1,277, result
flips to +22.8% return, Sharpe +0.06. Not signal improving though — band that
wide breaks the "rebuild whole book every bar" model this portfolio is,
turns it into coarse threshold trading instead (near `InverseVolPortfolio`'s
163x, which still loses money). Sharpe 0.06 also barely above zero. Read as
turnover-suppression effect, not edge found — band value chosen after seeing
it flip the number is exactly the kind of parameter search this report tries
not to present as a result.

Score Scaling Neutral is still the more interesting of the two structurally:
it runs dollar-neutral (long and short legs sized to net to zero) and carries
only 0.06 return correlation to the benchmark. Neither config is tuned for
performance, neither is cherry-picked — the point of this repo is the engine,
its cost model, and its reporting, not this particular signal.

## Regenerating

```bash
uv sync
uv run scripts/fetch_data.py configs/fetch_data.json
uv run scripts/run_zscore_backtest.py configs/zscore_rebalanced_neutral.json --cost-sweep
uv run scripts/run_zscore_backtest.py configs/zscore_backtest.json --cost-sweep
```

Each run writes a numbered PDF plus matching `_overview.png` (report's first
page) to `output/zscore_ma/`. Committed files here are those outputs renamed
— run number dropped from PDF, both run number and `_report` dropped from
PNG:

```
output/zscore_ma/score_scaling_neutral_report_1.pdf          → score_scaling_neutral_report.pdf
output/zscore_ma/score_scaling_neutral_report_1_overview.png → score_scaling_neutral_overview.png
output/zscore_ma/vol_sized_report_1.pdf                      → vol_sized_report.pdf
output/zscore_ma/vol_sized_report_1_overview.png             → vol_sized_overview.png
```

`--cost-sweep` re-runs the whole backtest once per rung of the cost ladder
and appends the Sharpe-vs-cost page to the PDF, so it takes several times
longer than a plain run. Drop it for a fast single run without a cost curve.

Numbers will differ slightly from committed reports if yfinance's historical
data has since been revised.
