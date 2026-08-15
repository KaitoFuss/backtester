"""The cost-sensitivity curve: one rung per cost level, and where Sharpe dies.

``CostPoint`` is a metrics dataclass in the same spirit as
``PerformanceMetrics``/``TradeMetrics`` in ``tracker/metrics.py`` — it lives
here rather than in ``sweep.py`` so that ``report.py`` can draw the curve
without importing the sweep runner, which pulls in the whole backtest stack
(engine, execution, portfolio, strategy) to *produce* these points. This
module imports nothing from the package, so ``report -> sweep -> runner``
never closes into a cycle.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class CostPoint:
    """One rung of the ladder: the strategy leg's result at ``cost_bps``.

    ``commission_bps`` is *not* swept — it is the config's fixed commission,
    carried on every point so anything rendering the curve can say what the
    half-spread was charged on top of."""

    cost_bps: float
    commission_bps: float
    total_return: float
    sharpe: float
    max_drawdown: float
    annual_turnover: float


def breakeven_cost(points: Sequence[CostPoint]) -> float | None:
    """The half-spread at which Sharpe first crosses zero, linearly interpolated
    between the two ladder rungs that straddle it.

    This is the swept half-spread only. The config's commission is held fixed
    across the ladder and is *not* included, so the total breakeven cost per
    fill is this figure plus ``commission_bps``.

    ``None`` when Sharpe never crosses within the ladder — either because the
    strategy survives every cost tested, or because it was already losing at
    zero cost, in which case there is no breakeven to report rather than one
    to extrapolate.

    Points are sorted by ``cost_bps`` before pairing, so a ladder handed over
    in any order (e.g. ``[5, 1, 0]``) still finds the crossing instead of
    interpolating across a negative span."""
    for low, high in pairwise(sorted(points, key=lambda point: point.cost_bps)):
        if low.sharpe >= 0.0 >= high.sharpe and low.sharpe != high.sharpe:
            span = high.cost_bps - low.cost_bps
            return low.cost_bps + span * low.sharpe / (low.sharpe - high.sharpe)
    return None
