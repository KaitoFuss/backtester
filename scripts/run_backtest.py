"""Run the z-score mean-reversion strategy against locally fetched Parquet data
and print first-pass performance metrics.

Usage:
    uv run scripts/run_backtest.py --data data/raw --tickers AAPL MSFT
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backtester.core.engine import Engine
from backtester.data.parquet_handler import ParquetHandler
from backtester.execution.simulated import IdealExecutionHandler
from backtester.portfolio.basic import WeightedPortfolio
from backtester.risk.performance import PerformanceTracker
from backtester.risk.plotting import plot_drawdown, plot_equity_curve
from backtester.strategy.zscore_ma import ZScoreMovingAverageStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description="Run z-score mean-reversion backtest")
    parser.add_argument("--data", required=True, help="Directory of daily Parquet files")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--window", type=int, default=20, help="Z-score lookback window")
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--plot-dir", default="output", help="Directory to write PNG plots to")
    args = parser.parse_args()

    data_handler = ParquetHandler(Path(args.data), tickers=args.tickers)
    portfolio = WeightedPortfolio(prices=data_handler, initial_cash=args.initial_cash)
    tracker = PerformanceTracker(portfolio=portfolio)

    engine = Engine(
        data_handler=data_handler,
        strategy=ZScoreMovingAverageStrategy(window=args.window),
        portfolio=portfolio,
        execution_handler=IdealExecutionHandler(prices=data_handler),
        risk_manager=tracker,
    )

    print(f"Running backtest on {args.data} …")
    engine.run()

    metrics = tracker.metrics()
    print()
    print("=== Performance ===")
    print(f"Bars processed:      {len(tracker.equity_curve)}")
    print(f"Total return:        {metrics.total_return:.2%}")
    print(f"Annualized return:   {metrics.annualized_return:.2%}")
    print(f"Annualized vol:      {metrics.annualized_vol:.2%}")
    print(f"Sharpe (rf=0):       {metrics.sharpe:.2f}")
    print(f"Max drawdown:        {metrics.max_drawdown:.2%}")

    plot_dir = Path(args.plot_dir)
    plot_equity_curve(tracker.equity_curve, plot_dir / "equity_curve.png")
    plot_drawdown(tracker.equity_curve, plot_dir / "drawdown.png")
    print(f"\nPlots written to {plot_dir}/")


if __name__ == "__main__":
    main()
