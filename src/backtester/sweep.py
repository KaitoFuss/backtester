"""Run one config across a ladder of trading costs and find where the edge dies."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace

from backtester.config import BacktestConfig
from backtester.runner import run_strategy_and_benchmark
from backtester.tracker.cost_curve import CostPoint

logger = logging.getLogger(__name__)

DEFAULT_LADDER: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0, 2.0, 5.0)


def run_cost_sweep(
    ladder: Sequence[float] = DEFAULT_LADDER, *, config: BacktestConfig
) -> list[CostPoint]:
    """Re-run ``config`` at each half-spread in ``ladder``, holding everything
    else fixed — **including ``config.commission_bps``**, which is charged on
    every rung. This is a half-spread sweep on top of a fixed commission, not a
    sweep of total cost, so rung ``0.0`` is not a frictionless run unless the
    config's commission is also zero."""
    points: list[CostPoint] = []
    for cost_bps in ladder:
        logger.info(
            "Running sweep rung at %.2f bp half-spread (+ %.2f bp commission)",
            cost_bps,
            config.commission_bps,
        )
        tracker = run_strategy_and_benchmark(replace(config, cost_bps=cost_bps))["Strategy"]
        metrics = tracker.metrics()
        points.append(
            CostPoint(
                cost_bps=cost_bps,
                commission_bps=config.commission_bps,
                total_return=metrics.total_return,
                sharpe=metrics.sharpe,
                max_drawdown=metrics.max_drawdown,
                # NOTE: this is whole-period turnover, not annualized, until a
                # follow-up PR annualizes and renames trade_metrics().turnover.
                # The field name here is already correct; only this
                # assignment changes then.
                annual_turnover=tracker.trade_metrics().turnover,
            )
        )
    return points
