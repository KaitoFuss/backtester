# Example reports

Two committed sample runs of z-score mean-reversion strategy
(`ZScoreMovingAverageStrategy`), each benchmarked against equal-weight
buy-and-hold on same 8-ETF universe (`SPY QQQ TLT IEF GLD DBC UUP FXE`,
2015-01-01 to 2025-01-01, daily bars from yfinance).

Both runs charge costs their config ships with: **1.0 bp half-spread per fill
(`cost_bps`) plus 0.5 bp commission (`commission_bps`)**. Every number below
is after those costs.

Both configs carry `drift_band: 0.005` — a 50 bp rebalancing no-trade band —
but only to keep the two structurally comparable. `build_portfolio` passes it
to `ScoreProportionalPortfolio` alone. So it is live for Score Scaling
Neutral, inert dead config for Vol Sized, whose `inverse_vol` model never
resizes a held position and has nothing to band.

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

This is the finding. It is not a flattering one.

Run Score Scaling Neutral with no costs at all and it returns **+74.9% at a
Sharpe of 0.32** — exactly why a backtest without a cost model is worthless.
That strategy rebalances to its exact target weights every bar and turns over
roughly 689x its equity per year. At that turnover the entire frictionless
result sits *inside* the cost term.

The number that matters is breakeven half-spread: hold the shipped 0.5 bp
commission fixed, sweep `cost_bps`, and Sharpe crosses zero at **0.19 bp** —
about **0.7 bp of total cost per fill**. Under a cent on a $100 ETF is the
whole edge. Real ETF spreads are wider than that before commission, borrow,
or impact. Honest reading: this signal has no tradable edge at this
rebalancing frequency, and the frictionless number was never a result. It was
an artifact of not charging for trading.

Vol Sized has no breakeven at all. It loses money (-4.9%, Sharpe -0.09)
before any cost is charged, so there is nothing for costs to erode. It turns
over ~4x less than the neutral book and degrades ~4x more gently, which is
the only thing the comparison demonstrates.

The 50 bp drift band barely moves Score Scaling Neutral, the only run that
reads it: this signal's target weights churn by more than 50 bp of equity
most bars, so the band rarely fires. A band wide enough to cut that turnover
materially would also filter out the daily signal the strategy is built on.
That trade-off is the real constraint, not a tuning oversight.

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
