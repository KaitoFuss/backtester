"""Run the z-score mean-reversion strategy against locally fetched Parquet data
and print first-pass performance metrics.

Usage:
    uv run scripts/run_zscore_backtest.py --data data/raw --tickers AAPL MSFT
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from backtester.core.engine import Engine
from backtester.data.parquet_market_data import ParquetMarketData
from backtester.execution.ideal import IdealExecutionHandler
from backtester.portfolio.weighted import WeightedPortfolio
from backtester.risk.performance import PerformanceTracker
from backtester.risk.plotting import plot_drawdown, plot_mark_to_market_history
from backtester.strategy.zscore_ma import ZScoreMovingAverageStrategy

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run z-score mean-reversion backtest")
    parser.add_argument("--data", required=True, help="Directory of daily Parquet files")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--window", type=int, default=20, help="Z-score lookback window")
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument(
        "--plot-dir",
        default="output",
        help="Root directory for plots; a per-strategy subfolder is created under it",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )

    market_data = ParquetMarketData(Path(args.data), tickers=args.tickers)
    portfolio = WeightedPortfolio(price_source=market_data, initial_cash=args.initial_cash)
    tracker = PerformanceTracker(portfolio=portfolio)

    engine = Engine(
        data_handler=market_data,
        strategy=ZScoreMovingAverageStrategy(window=args.window),
        portfolio=portfolio,
        execution_handler=IdealExecutionHandler(price_source=market_data),
        risk_manager=tracker,
    )

    logger.info("Running backtest on %s …", args.data)
    engine.run()

    metrics = tracker.metrics()
    logger.info("=== Performance ===")
    logger.info("Bars processed:      %d", len(tracker.mark_to_market_history))
    logger.info("Total return:        %s", f"{metrics.total_return:.2%}")
    logger.info("Annualized return:   %s", f"{metrics.annualized_return:.2%}")
    logger.info("Annualized vol:      %s", f"{metrics.annualized_vol:.2%}")
    logger.info("Sharpe (rf=0):       %.2f", metrics.sharpe)
    logger.info("Max drawdown:        %s", f"{metrics.max_drawdown:.2%}")

    plot_dir = Path(args.plot_dir) / "zscore_ma"
    plot_mark_to_market_history(tracker.mark_to_market_history, plot_dir / "equity_curve.png")
    plot_drawdown(tracker.mark_to_market_history, plot_dir / "drawdown.png")
    logger.info("Plots written to %s/", plot_dir)


if __name__ == "__main__":
    main()
