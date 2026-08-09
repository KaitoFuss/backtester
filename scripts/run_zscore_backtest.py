"""Run the z-score mean-reversion strategy against locally fetched Parquet data,
alongside a buy-and-hold benchmark, and write a performance report PDF.

Usage:
    uv run scripts/run_zscore_backtest.py configs/zscore_backtest.json

The strategy leg's portfolio comes from `config.portfolio`; the benchmark leg is
always equal-weight buy-and-hold. Three configs run the same signal and universe
through each sizing model, so their reports are directly comparable:

    configs/zscore_backtest.json           inverse_vol, band trading + risk exits
    configs/zscore_rebalanced.json         score_proportional, rebalanced every bar
    configs/zscore_rebalanced_neutral.json score_proportional + dollar_neutral

Note the neutral config keeps entry_threshold=2.0 for comparability, which is
restrictive once scores are demeaned: a lone surviving name demeans to exactly
zero, so the book needs two names crossing at once to hold anything at all.
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
from backtester.portfolio.equal_weight import EqualWeightPortfolio
from backtester.portfolio.factory import build_portfolio
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


def _warn_if_risk_exits_fight_rebalancing(config: BacktestConfig) -> None:
    """`PositionExitRiskManager` measures every threshold from a position's
    entry, which a continuously rebalanced book no longer really has — and a
    forced exit is re-entered at full size on the next bar, since the score
    that sized it is still there. The config is honored either way; this just
    makes the pairing visible."""
    exits = (config.stop_loss_pct, config.take_profit_pct, config.max_holding_days)
    if config.portfolio == "score_proportional" and any(e is not None for e in exits):
        logger.warning(
            "portfolio=score_proportional rebalances every bar, so entry-referenced risk "
            "exits will be re-entered on the next bar; consider nulling stop_loss_pct / "
            "take_profit_pct / max_holding_days"
        )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_zscore_backtest.py <config.json>")
    config = BacktestConfig.from_json(Path(sys.argv[1]))

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )
    data_dir = Path(config.data)

    _warn_if_risk_exits_fight_rebalancing(config)

    logger.info("Running backtest on %s …", data_dir)
    strategy_tracker = _run_backtest(
        data_dir,
        config.tickers,
        ZScoreMovingAverageStrategy(window=config.window, winsor_limit=config.winsor_limit),
        lambda price_source: build_portfolio(config, price_source),
        lambda portfolio: PositionExitRiskManager(
            portfolio=portfolio,
            stop_loss_pct=config.stop_loss_pct,
            take_profit_pct=config.take_profit_pct,
            max_holding_days=config.max_holding_days,
        ),
    )
    # Buy & Hold is a fixed passive reference, not a thing under test, so it
    # keeps its own portfolio regardless of config.portfolio, at the default
    # max_gross=1.0 rather than the strategy's configured leverage. It never
    # exits, so none of the strategy's risk-exit config applies to it either.
    benchmark_tracker = _run_backtest(
        data_dir,
        config.tickers,
        BuyAndHoldStrategy(),
        lambda price_source: EqualWeightPortfolio(
            price_source=price_source, initial_cash=config.initial_cash
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
