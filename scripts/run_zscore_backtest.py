"""Run the z-score mean-reversion strategy against locally fetched Parquet data,
alongside a buy-and-hold benchmark, and print first-pass performance metrics.

Usage:
    uv run scripts/run_zscore_backtest.py --data data/raw --tickers AAPL MSFT
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from backtester.core.engine import Engine, Strategy
from backtester.data.parquet_market_data import ParquetMarketData
from backtester.execution.ideal import IdealExecutionHandler
from backtester.portfolio.weighted import WeightedPortfolio
from backtester.risk.exits import PositionExitRiskManager
from backtester.strategy.buy_and_hold import BuyAndHoldStrategy
from backtester.strategy.zscore_ma import ZScoreMovingAverageStrategy
from backtester.tracker.metrics import PerformanceTracker
from backtester.tracker.plotting import plot_equity_curve

logger = logging.getLogger(__name__)


def _run_backtest(
    data_dir: Path,
    tickers: list[str] | None,
    strategy: Strategy,
    initial_cash: float,
    entry_threshold: float,
    exit_threshold: float,
    target_vol: float,
    vol_window: int,
    max_gross: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    max_holding_days: int | None,
) -> PerformanceTracker:
    market_data = ParquetMarketData(data_dir, tickers=tickers)
    portfolio = WeightedPortfolio(
        price_source=market_data,
        initial_cash=initial_cash,
        entry_threshold=entry_threshold,
        exit_threshold=exit_threshold,
        target_vol=target_vol,
        vol_window=vol_window,
        max_gross=max_gross,
    )
    tracker = PerformanceTracker(portfolio=portfolio)
    risk_manager = PositionExitRiskManager(
        portfolio=portfolio,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        max_holding_days=max_holding_days,
    )

    engine = Engine(
        data_handler=market_data,
        strategy=strategy,
        portfolio=portfolio,
        execution_handler=IdealExecutionHandler(price_source=market_data),
        risk_manager=risk_manager,
        tracker=tracker,
    )
    engine.run()
    return tracker


def _log_metrics(label: str, tracker: PerformanceTracker) -> None:
    metrics = tracker.metrics()
    logger.info("=== %s ===", label)
    logger.info("Bars processed:      %d", len(tracker.mark_to_market_history))
    logger.info("Total return:        %s", f"{metrics.total_return:.2%}")
    logger.info("Annualized return:   %s", f"{metrics.annualized_return:.2%}")
    logger.info("Annualized vol:      %s", f"{metrics.annualized_vol:.2%}")
    logger.info("Sharpe (rf=0):       %.2f", metrics.sharpe)
    logger.info("Max drawdown:        %s", f"{metrics.max_drawdown:.2%}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run z-score mean-reversion backtest")
    parser.add_argument("--data", required=True, help="Directory of daily Parquet files")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--window", type=int, default=20, help="Z-score lookback window")
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument(
        "--entry-threshold", type=float, default=0.0, help="abs(score) required to open a position"
    )
    parser.add_argument(
        "--exit-threshold", type=float, default=0.0, help="abs(score) below which a position closes"
    )
    parser.add_argument(
        "--target-vol", type=float, default=0.10, help="Annualized portfolio vol ceiling"
    )
    parser.add_argument(
        "--vol-window", type=int, default=20, help="Trailing window for per-ticker vol"
    )
    parser.add_argument(
        "--max-gross", type=float, default=1.0, help="Gross exposure cap (x equity)"
    )
    parser.add_argument(
        "--winsor-limit", type=float, default=3.0, help="Clip the z-score signal to +/- this"
    )
    parser.add_argument("--stop-loss-pct", type=float, default=None)
    parser.add_argument("--take-profit-pct", type=float, default=None)
    parser.add_argument("--max-holding-days", type=int, default=None)
    parser.add_argument(
        "--plot-dir",
        default="output",
        help="Root directory for plots; a per-strategy subfolder is created under it",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )
    data_dir = Path(args.data)

    logger.info("Running backtest on %s …", data_dir)
    run_kwargs = {
        "entry_threshold": args.entry_threshold,
        "exit_threshold": args.exit_threshold,
        "target_vol": args.target_vol,
        "vol_window": args.vol_window,
        "max_gross": args.max_gross,
        "stop_loss_pct": args.stop_loss_pct,
        "take_profit_pct": args.take_profit_pct,
        "max_holding_days": args.max_holding_days,
    }
    strategy_tracker = _run_backtest(
        data_dir,
        args.tickers,
        ZScoreMovingAverageStrategy(window=args.window, winsor_limit=args.winsor_limit),
        args.initial_cash,
        **run_kwargs,
    )
    benchmark_tracker = _run_backtest(
        data_dir, args.tickers, BuyAndHoldStrategy(), args.initial_cash, **run_kwargs
    )

    _log_metrics("Strategy", strategy_tracker)
    _log_metrics("Buy & Hold", benchmark_tracker)

    plot_dir = Path(args.plot_dir) / "zscore_ma"
    plot_equity_curve(
        {
            "Strategy": strategy_tracker.mark_to_market_history,
            "Buy & Hold": benchmark_tracker.mark_to_market_history,
        },
        plot_dir / "equity_curve.png",
    )
    logger.info("Plots written to %s/", plot_dir)


if __name__ == "__main__":
    main()
