# Example reports

Two committed sample runs of the z-score mean-reversion strategy
(`ZScoreMovingAverageStrategy`), each benchmarked against an equal-weight
buy-and-hold on the same 8-ETF universe (`SPY QQQ TLT IEF GLD DBC UUP FXE`,
2015-01-01 to 2025-01-01, daily bars from yfinance).

**These are unoptimized reference configurations included to demonstrate the
engine and its reporting.** Neither has been tuned for performance; they
exist to exercise every portfolio-construction and reporting code path end
to end.

| | Config | Portfolio model | Total return | Sharpe | Max DD | vs. Buy & Hold |
|---|---|---|---|---|---|---|
| [Score Scaling Neutral](score_scaling_neutral_report.pdf) | `configs/zscore_rebalanced_neutral.json` | `score_proportional`, dollar-neutral | +75.0% | 0.38 | -23.2% | +83.6% / 0.73 — but only 0.06 return correlation to it |
| [Vol Sized](vol_sized_report.pdf) | `configs/zscore_backtest.json` | `inverse_vol`, band trading | -4.9% | -0.03 | -37.1% | +83.6% / 0.73 |

Score Scaling Neutral is the more interesting of the two: it runs
dollar-neutral (long and short legs sized to net to zero), so its near-zero
correlation to the benchmark is the point, not its raw return. Vol Sized
loses money outright over the window — it's shown as-is, not cherry-picked,
because the point of this repo is the engine and its reporting, not this
particular signal.

Regenerate either from a clean clone:

```bash
uv sync
uv run scripts/fetch_data.py configs/fetch_data.json
uv run scripts/run_zscore_backtest.py configs/zscore_rebalanced_neutral.json
uv run scripts/run_zscore_backtest.py configs/zscore_backtest.json
```

Each run writes a numbered PDF to `output/zscore_ma/`. Numbers will differ
slightly from the committed reports if yfinance's historical data has since
been revised.
