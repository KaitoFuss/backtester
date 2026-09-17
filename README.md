# backtester

Event-driven backtesting engine for equity strategies.

[![CI](https://github.com/KaitoFuss/backtester/actions/workflows/ci.yml/badge.svg)](https://github.com/KaitoFuss/backtester/actions/workflows/ci.yml)
![coverage](https://img.shields.io/badge/coverage-97%25-brightgreen)
![python](https://img.shields.io/badge/python-3.12-blue)
[![license](https://img.shields.io/badge/license-MIT-informational)](LICENSE)

## What is this

Single-threaded, deterministic engine. Small event loop:

```
DataHandler → MarketEvent → Strategy → SignalEvent → Portfolio → OrderEvent → ExecutionHandler → FillEvent → Portfolio
```

Every component (`DataHandler`, `Strategy`, `Portfolio`, `ExecutionHandler`,
`RiskManager`, `Tracker`) is structural `Protocol`. New strategies and
portfolio models plug in without touching engine. Ships three
portfolio-construction models (risk-sized band trading, continuous
conviction-weighted rebalancing, dumb equal-weight benchmark) — an order
means something different under each: band trading opens a position once and
holds it untouched until an exit gate fires, rebalancing retrades a target
delta every bar. Only band trading pairs with the entry-referenced
stop-loss/take-profit/max-holding risk checks shipped here; a rebalancer
would just re-enter a forced exit on the next bar, so the sample configs
enable those checks for band trading alone. Also ships cost-aware execution
(per-fill half-spread and commission, plus rebalancing drift band to
suppress churn), cost sweep reporting breakeven half-spread, multi-page PDF
report (equity curve, drawdown, trade stats, monthly returns, return
correlation, cost sensitivity).

Full design writeup: [ARCHITECTURE.md](ARCHITECTURE.md).

## Sample output

![Score Scaling Neutral performance overview](examples/reports/score_scaling_neutral_overview.png)

Dollar-neutral z-score mean-reversion strategy vs equal-weight buy-and-hold
benchmark. Same 8-ETF universe, 2015–2025, charged 1.0 bp half-spread and
0.5 bp commission per fill. Strategy returns **-37.6% at a Sharpe of -0.37**
against benchmark's +83.6% / 0.52. Both Sharpes are excess-return figures
against a 2% annualized risk-free rate (`config.risk_free_rate`).

Costs off, it returns **+74.9% at 0.32** — whole result lives inside cost term.
It rebalances every bar, turns over ~689x its equity a year (gross traded
notional, every fill counted once), and its Sharpe crosses zero at a
**0.19 bp** half-spread on top of shipped commission. Both committed sample reports, full cost
curve, and regeneration steps: [`examples/reports/`](examples/reports/).

## Quickstart

```bash
uv sync
uv run scripts/fetch_data.py configs/fetch_data.json
uv run scripts/run_zscore_backtest.py configs/zscore_rebalanced_neutral.json -v --cost-sweep
```

No dataset committed. First command pulls sample 8-ETF universe (2015–2025
daily bars) from yfinance into one tidy Parquet file, `data/raw.parquet`.
Second runs strategy, writes PDF report to `output/zscore_ma/`. `-v` prints
trade blotter as it goes (`-vv` adds full numeric trail). `--cost-sweep`
re-runs config across ladder of trading costs and folds Sharpe-vs-cost page
with breakeven half-spread into report. Swap in
`configs/zscore_backtest.json` for risk-sized band-trading variant.

## Project structure

```
src/backtester/   # library source (src layout)
tests/            # tests, mirroring src/backtester/ module paths
scripts/          # CLI entry points (data fetch, run a backtest)
configs/          # backtest/data-fetch configs consumed by scripts/
examples/reports/ # committed sample reports (see its own README)
pyproject.toml    # project metadata, dependencies, and tool config
                   # (ruff, mypy, pytest, coverage all configured here)
```

## Development

```bash
uv sync                      # install/sync deps
uv run ruff format .         # format
uv run ruff check . --fix    # lint
uv run mypy .                # strict type check
uv run pytest                # tests (coverage gate: --cov-fail-under=95)
```

Optional: install pre-commit hooks so formatting/linting run on `git commit`:

```bash
uv run --with pre-commit pre-commit install
```

## Conventions

- `mypy --strict` across `src` and `tests`.
- Ruff for lint + format. Rule set and config in `pyproject.toml`.
- Structural typing via `Protocol` over inheritance/ABCs for every pluggable
  component (see `core/engine.py`).
- Tests mirror `src/backtester/` module paths 1:1 under `tests/`.
- Add dependencies via `uv add` / `uv add --dev`, never by hand-editing
  `pyproject.toml`.

## License

MIT — see [LICENSE](LICENSE).
