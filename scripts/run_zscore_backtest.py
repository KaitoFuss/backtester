"""Run the z-score mean-reversion strategy against locally fetched Parquet data,
alongside a buy-and-hold benchmark, and write a performance report PDF.

Usage:
    uv run scripts/run_zscore_backtest.py configs/zscore_backtest.json
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path

from backtester.config import BacktestConfig
from backtester.core.engine import Engine, Portfolio, PriceSource, RiskManager, Strategy
from backtester.data.parquet_market_data import ParquetMarketData
from backtester.execution.ideal import IdealExecutionHandler
from backtester.portfolio.score_proportional import ScoreProportionalPortfolio
from backtester.portfolio.vol_weighted import VolWeightedPortfolio
from backtester.risk.exits import PositionExitRiskManager
from backtester.strategy.buy_and_hold import BuyAndHoldStrategy
from backtester.strategy.zscore_ma import ZScoreMovingAverageStrategy
from backtester.tracker.metrics import (
    PerformanceTracker,
    monthly_returns_table,
    strategy_correlation_matrix,
)
from backtester.tracker.report import save_report

logger = logging.getLogger(__name__)


PortfolioFactory = Callable[[PriceSource], Portfolio]
RiskManagerFactory = Callable[[Portfolio], RiskManager | None]


def _run_backtest(
    data_dir: Path,
    tickers: list[str] | None,
    strategy: Strategy,
    portfolio_factory: PortfolioFactory,
    risk_manager_factory: RiskManagerFactory,
) -> PerformanceTracker:
    market_data = ParquetMarketData(data_dir, tickers=tickers)
    portfolio = portfolio_factory(market_data)
    tracker = PerformanceTracker(portfolio=portfolio)
    risk_manager = risk_manager_factory(portfolio)

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
        ZScoreMovingAverageStrategy(window=config.window, winsor_limit=config.winsor_limit),
        lambda price_source: VolWeightedPortfolio(
            price_source=price_source,
            initial_cash=config.initial_cash,
            entry_threshold=config.entry_threshold,
            exit_threshold=config.exit_threshold,
            vol_window=config.vol_window,
            max_gross=config.max_gross,
            target_vol=config.target_vol,
        ),
        lambda portfolio: PositionExitRiskManager(
            portfolio=portfolio,
            stop_loss_pct=config.stop_loss_pct,
            take_profit_pct=config.take_profit_pct,
            max_holding_days=config.max_holding_days,
        ),
    )
    # Buy & Hold is a passive reference, not a strategy under test — it never
    # exits, so none of the strategy's risk-exit config (stop-loss,
    # take-profit, max-holding-days) applies to it.
    benchmark_tracker = _run_backtest(
        data_dir,
        config.tickers,
        BuyAndHoldStrategy(),
        lambda price_source: ScoreProportionalPortfolio(
            price_source=price_source, initial_cash=config.initial_cash, max_gross=config.max_gross
        ),
        lambda portfolio: None,
    )

    trackers = {"Strategy": strategy_tracker, "Buy & Hold": benchmark_tracker}
    histories = {label: tracker.mark_to_market_history for label, tracker in trackers.items()}

    report_path = save_report(
        output_dir=Path(config.output_dir) / "zscore_ma",
        histories=histories,
        metrics={label: tracker.metrics() for label, tracker in trackers.items()},
        trade_metrics={label: tracker.trade_metrics() for label, tracker in trackers.items()},
        monthly_tables={
            label: monthly_returns_table(history) for label, history in histories.items()
        },
        correlation=strategy_correlation_matrix(histories),
        config=config,
    )
    logger.info("Report written to %s", report_path)


if __name__ == "__main__":
    main()
