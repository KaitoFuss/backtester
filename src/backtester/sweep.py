"""Run one config across a ladder of trading costs and find where the edge dies."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

from backtester.config import BacktestConfig
from backtester.runner import run_strategy_and_benchmark

logger = logging.getLogger(__name__)

DEFAULT_LADDER: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0, 2.0, 5.0)


@dataclass(frozen=True)
class CostPoint:
    """One rung of the ladder: the strategy leg's result at ``cost_bps``."""

    cost_bps: float
    total_return: float
    sharpe: float
    max_drawdown: float
    annual_turnover: float


def breakeven_cost(points: Sequence[CostPoint]) -> float | None:
    """The half-spread at which Sharpe first crosses zero, linearly interpolated
    between the two ladder rungs that straddle it.

    ``None`` when Sharpe never crosses within the ladder — either because the
    strategy survives every cost tested, or because it was already losing at
    zero cost, in which case there is no breakeven to report rather than one
    to extrapolate."""
    for low, high in pairwise(points):
        if low.sharpe >= 0.0 >= high.sharpe and low.sharpe != high.sharpe:
            span = high.cost_bps - low.cost_bps
            return low.cost_bps + span * low.sharpe / (low.sharpe - high.sharpe)
    return None


def run_cost_sweep(
    config: BacktestConfig, ladder: Sequence[float] = DEFAULT_LADDER
) -> list[CostPoint]:
    """Re-run ``config`` at each cost level, holding everything else fixed."""
    points: list[CostPoint] = []
    for cost_bps in ladder:
        logger.info("Running sweep rung at %.2f bp", cost_bps)
        tracker = run_strategy_and_benchmark(replace(config, cost_bps=cost_bps))["Strategy"]
        metrics = tracker.metrics()
        points.append(
            CostPoint(
                cost_bps=cost_bps,
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
    lines = [f"{'cost(bps)':>10}{'TotRet':>10}{'Sharpe':>9}{'MaxDD':>9}{'Turnover':>11}"]
    for point in points:
        lines.append(
            f"{point.cost_bps:>10.2f}{point.total_return:>10.1%}{point.sharpe:>9.2f}"
            f"{point.max_drawdown:>9.1%}{point.annual_turnover:>10.0f}x"
        )
    breakeven = breakeven_cost(points)
    lines.append("")
    lines.append(
        f"Breakeven (Sharpe = 0): ~{breakeven:.2f} bp"
        if breakeven is not None
        else "Breakeven (Sharpe = 0): none within the tested ladder"
    )
    return "\n".join(lines)
