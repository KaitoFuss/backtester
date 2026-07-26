"""Run the z-score mean-reversion strategy against locally fetched Parquet data,
alongside a buy-and-hold benchmark, and write a performance report PDF.

Usage:
    uv run scripts/run_zscore_backtest.py configs/zscore_backtest.json
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from backtester.config import BacktestConfig
from backtester.core.engine import Engine, Strategy
from backtester.data.parquet_market_data import ParquetMarketData
from backtester.execution.ideal import IdealExecutionHandler
from backtester.portfolio.weighted import WeightedPortfolio
from backtester.risk.exits import PositionExitRiskManager
from backtester.strategy.buy_and_hold import BuyAndHoldStrategy
from backtester.strategy.zscore_ma import ZScoreMovingAverageStrategy
from backtester.tracker.metrics import PerformanceTracker
from backtester.tracker.plotting import plot_equity_curve
from backtester.tracker.report import save_report
from backtester.tracker.reporting import monthly_returns_table, strategy_correlation_matrix

logger = logging.getLogger(__name__)


def _run_backtest(
    data_dir: Path,
    tickers: list[str] | None,
    strategy: Strategy,
    initial_cash: float,
    entry_threshold: float,
    exit_threshold: float,
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


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_zscore_backtest.py <config.json>")
    config = BacktestConfig.from_json(Path(sys.argv[1]))

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )
    data_dir = Path(config.data)

    logger.info("Running backtest on %s …", data_dir)
    strategy_tracker = _run_backtest(
        data_dir,
        config.tickers,
        ZScoreMovingAverageStrategy(window=config.window),
        config.initial_cash,
        config.entry_threshold,
        config.exit_threshold,
        config.stop_loss_pct,
        config.take_profit_pct,
        config.max_holding_days,
    )
    benchmark_tracker = _run_backtest(
        data_dir,
        config.tickers,
        BuyAndHoldStrategy(),
        config.initial_cash,
        config.entry_threshold,
        config.exit_threshold,
        config.stop_loss_pct,
        config.take_profit_pct,
        config.max_holding_days,
    )

    trackers = {"Strategy": strategy_tracker, "Buy & Hold": benchmark_tracker}
    histories = {label: tracker.mark_to_market_history for label, tracker in trackers.items()}

    plot_dir = Path(config.plot_dir) / "zscore_ma"
    plot_equity_curve(histories, plot_dir / "equity_curve.png")

    report_path = save_report(
        output_dir=plot_dir,
        metrics={label: tracker.metrics() for label, tracker in trackers.items()},
        trade_metrics={label: tracker.trade_metrics() for label, tracker in trackers.items()},
        monthly_tables={
            label: monthly_returns_table(history) for label, history in histories.items()
        },
        correlation=strategy_correlation_matrix(histories),
        config=config,
    )
    logger.info("Report written to %s", report_path)
    logger.info("Plots written to %s/", plot_dir)


if __name__ == "__main__":
    main()
