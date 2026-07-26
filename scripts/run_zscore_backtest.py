"""Run the z-score mean-reversion strategy against locally fetched Parquet data,
alongside a buy-and-hold benchmark, and print first-pass performance metrics.

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


def _log_metrics(label: str, tracker: PerformanceTracker) -> None:
    metrics = tracker.metrics()
    logger.info("=== %s ===", label)
    logger.info("Bars processed:      %d", len(tracker.mark_to_market_history))
    logger.info("Total return:        %s", f"{metrics.total_return:.2%}")
    logger.info("Annualized return:   %s", f"{metrics.annualized_return:.2%}")
    logger.info("Annualized vol:      %s", f"{metrics.annualized_vol:.2%}")
    logger.info("Sharpe (rf=0):       %.2f", metrics.sharpe)
    logger.info("Max drawdown:        %s", f"{metrics.max_drawdown:.2%}")

    trade_metrics = tracker.trade_metrics()
    logger.info("Num trades:          %d", trade_metrics.num_trades)
    logger.info("Win rate:            %s", f"{trade_metrics.win_rate:.2%}")
    logger.info("Avg win / avg loss:  %.2f / %.2f", trade_metrics.avg_win, trade_metrics.avg_loss)
    logger.info("Risk/reward ratio:   %.2f", trade_metrics.risk_reward_ratio)
    logger.info("Payoff factor:       %.2f", trade_metrics.payoff_factor)
    logger.info("CPC index:           %.2f", trade_metrics.cpc_index)
    logger.info("Time in market:      %s", f"{trade_metrics.time_in_market:.2%}")
    logger.info("Turnover:            %.2f", trade_metrics.turnover)

    monthly_table = monthly_returns_table(tracker.mark_to_market_history)
    logger.info(
        "Monthly returns (%s):\n%s", label, monthly_table.to_string(float_format="{:.2%}".format)
    )


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

    _log_metrics("Strategy", strategy_tracker)
    _log_metrics("Buy & Hold", benchmark_tracker)

    correlation = strategy_correlation_matrix(
        {
            "Strategy": strategy_tracker.mark_to_market_history,
            "Buy & Hold": benchmark_tracker.mark_to_market_history,
        }
    )
    logger.info(
        "Strategy correlation matrix:\n%s", correlation.to_string(float_format="{:.2f}".format)
    )

    plot_dir = Path(config.plot_dir) / "zscore_ma"
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
