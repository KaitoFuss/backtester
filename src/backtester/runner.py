"""Backtest wiring, importable so both the CLI and the cost sweep share one path."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from backtester.config import BacktestConfig
from backtester.core.engine import Engine, Portfolio, PriceSource, RiskManager, Strategy
from backtester.data.parquet_market_data import ParquetMarketData
from backtester.execution.cost_aware import CostAwareExecutionHandler
from backtester.execution.ideal import IdealExecutionHandler
from backtester.portfolio.equal_weight import EqualWeightPortfolio
from backtester.portfolio.factory import build_portfolio
from backtester.risk.exits import PositionExitRiskManager
from backtester.strategy.buy_and_hold import BuyAndHoldStrategy
from backtester.strategy.zscore_ma import ZScoreMovingAverageStrategy
from backtester.tracker.metrics import PerformanceTracker

logger = logging.getLogger(__name__)

PortfolioFactory = Callable[[PriceSource], Portfolio]
RiskManagerFactory = Callable[[Portfolio], RiskManager | None]

_LEVELS = (logging.WARNING, logging.INFO, logging.DEBUG)


def verbosity_to_level(count: int) -> int:
    """Map repeated ``-v`` flags onto log levels: none is quiet, ``-v`` is the
    trade blotter, ``-vv`` is the full numeric trail."""
    return _LEVELS[min(count, len(_LEVELS) - 1)]


def run_backtest(
    config: BacktestConfig,
    strategy: Strategy,
    portfolio_factory: PortfolioFactory,
    risk_manager_factory: RiskManagerFactory,
) -> PerformanceTracker:
    market_data = ParquetMarketData(Path(config.data), tickers=config.tickers)
    portfolio = portfolio_factory(market_data)
    tracker = PerformanceTracker(portfolio=portfolio)

    engine = Engine(
        data_handler=market_data,
        strategy=strategy,
        portfolio=portfolio,
        execution_handler=CostAwareExecutionHandler(
            IdealExecutionHandler(price_source=market_data),
            cost_bps=config.cost_bps,
            commission_bps=config.commission_bps,
        ),
        risk_manager=risk_manager_factory(portfolio),
        tracker=tracker,
    )
    engine.run()
    return tracker


def run_strategy_and_benchmark(config: BacktestConfig) -> dict[str, PerformanceTracker]:
    """The strategy leg under ``config.portfolio``, plus the fixed equal-weight
    buy-and-hold reference. The benchmark keeps ``max_gross=1.0`` and no risk
    exits regardless of config — it is a passive reference, not a thing under
    test — but it pays the same trading costs, so the comparison is fair."""
    strategy_tracker = run_backtest(
        config,
        ZScoreMovingAverageStrategy(window=config.window, winsor_limit=config.winsor_limit),
        lambda price_source: build_portfolio(config, price_source),
        lambda portfolio: PositionExitRiskManager(
            portfolio=portfolio,
            stop_loss_pct=config.stop_loss_pct,
            take_profit_pct=config.take_profit_pct,
            max_holding_days=config.max_holding_days,
        ),
    )
    benchmark_tracker = run_backtest(
        config,
        BuyAndHoldStrategy(),
        lambda price_source: EqualWeightPortfolio(
            price_source=price_source, initial_cash=config.initial_cash
        ),
        lambda portfolio: None,
    )
    return {"Strategy": strategy_tracker, "Buy & Hold": benchmark_tracker}


def warn_if_risk_exits_fight_rebalancing(config: BacktestConfig) -> None:
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
