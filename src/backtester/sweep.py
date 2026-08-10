"""Run one config across a ladder of trading costs and find where the edge dies."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace

from backtester.config import BacktestConfig
from backtester.cost_curve import CostPoint, breakeven_cost
from backtester.runner import run_strategy_and_benchmark

logger = logging.getLogger(__name__)

DEFAULT_LADDER: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0, 2.0, 5.0)


def run_cost_sweep(
    config: BacktestConfig, ladder: Sequence[float] = DEFAULT_LADDER
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


def format_sweep(points: Sequence[CostPoint]) -> str:
    """The ladder as a table. The swept column is the half-spread alone, so the
    commission is named above the table and again beside the breakeven — the
    figure is meaningless without it."""
    commission = points[0].commission_bps if points else 0.0
    lines = [
        f"Commission fixed at {commission:.2f} bp per fill; "
        "the ladder sweeps the half-spread on top of it.",
        f"{'half-spread(bps)':>17}{'TotRet':>10}{'Sharpe':>9}{'MaxDD':>9}{'Turnover':>11}",
    ]
    for point in points:
        lines.append(
            f"{point.cost_bps:>17.2f}{point.total_return:>10.1%}{point.sharpe:>9.2f}"
            f"{point.max_drawdown:>9.1%}{point.annual_turnover:>10.0f}x"
        )
    breakeven = breakeven_cost(points)
    lines.append("")
    lines.append(
        f"Breakeven (Sharpe = 0): ~{breakeven:.2f} bp half-spread, "
        f"on top of the {commission:.2f} bp commission"
        if breakeven is not None
        else "Breakeven (Sharpe = 0): none within the tested ladder"
    )
    return "\n".join(lines)
