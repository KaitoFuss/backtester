from collections.abc import Sequence
from dataclasses import dataclass, replace

import pytest

from backtester import sweep
from backtester.config import BacktestConfig
from backtester.cost_curve import CostPoint
from backtester.sweep import format_sweep, run_cost_sweep
from backtester.tracker.metrics import PerformanceMetrics, TradeMetrics


def _point(cost: float, total_return: float, sharpe: float) -> CostPoint:
    return CostPoint(
        cost_bps=cost,
        commission_bps=0.5,
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=-0.409,
        annual_turnover=688.0,
    )


def test_format_sweep_renders_the_table_the_readme_quotes() -> None:
    """A golden string: this is a nested f-string of hand-counted column widths
    feeding a published table, so a format typo would otherwise ship silently."""
    points = [_point(0.0, 0.749, 0.38), _point(1.0, -0.376, -0.31)]

    assert format_sweep(points) == (
        "Commission fixed at 0.50 bp per fill; the ladder sweeps the half-spread on top of it.\n"
        " half-spread(bps)    TotRet   Sharpe    MaxDD   Turnover\n"
        "             0.00     74.9%     0.38   -40.9%       688x\n"
        "             1.00    -37.6%    -0.31   -40.9%       688x\n"
        "\n"
        "Breakeven (Sharpe = 0): ~0.55 bp half-spread, on top of the 0.50 bp commission"
    )


def test_format_sweep_says_so_when_the_ladder_never_crosses_zero() -> None:
    points = [_point(0.0, 0.749, 1.20), _point(1.0, 0.600, 0.95)]

    assert format_sweep(points) == (
        "Commission fixed at 0.50 bp per fill; the ladder sweeps the half-spread on top of it.\n"
        " half-spread(bps)    TotRet   Sharpe    MaxDD   Turnover\n"
        "             0.00     74.9%     1.20   -40.9%       688x\n"
        "             1.00     60.0%     0.95   -40.9%       688x\n"
        "\n"
        "Breakeven (Sharpe = 0): none within the tested ladder"
    )


@dataclass(frozen=True)
class _StubTracker:
    """Just the two accessors ``run_cost_sweep`` reads off the strategy leg."""

    def metrics(self) -> PerformanceMetrics:
        return PerformanceMetrics(0.1, 0.1, 0.1, 1.0, -0.05, 0.5)

    def trade_metrics(self) -> TradeMetrics:
        return TradeMetrics(10, 0.6, 100.0, -50.0, 2.0, 2.0, 1.2, 0.5, 42.0)


def test_run_cost_sweep_varies_the_half_spread_and_holds_the_commission_fixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The published breakeven is a half-spread charged *on top of* the config's
    commission. If a future edit to the ``replace(...)`` call also swept
    ``commission_bps``, every breakeven number in the README would quietly
    change meaning, so pin both here."""
    seen: list[BacktestConfig] = []

    def _fake_run(config: BacktestConfig) -> dict[str, _StubTracker]:
        seen.append(config)
        return {"Strategy": _StubTracker(), "Buy & Hold": _StubTracker()}

    monkeypatch.setattr(sweep, "run_strategy_and_benchmark", _fake_run)
    config = BacktestConfig(name="T", data="data/raw", cost_bps=99.0, commission_bps=0.5)
    ladder: Sequence[float] = (0.0, 0.25, 2.0)

    points = run_cost_sweep(config, ladder)

    assert [c.cost_bps for c in seen] == [0.0, 0.25, 2.0]
    assert [c.commission_bps for c in seen] == [0.5, 0.5, 0.5]
    # Nothing but cost_bps moves between rungs.
    assert all(c == replace(config, cost_bps=c.cost_bps) for c in seen)
    assert [p.cost_bps for p in points] == [0.0, 0.25, 2.0]
    assert [p.commission_bps for p in points] == [0.5, 0.5, 0.5]
    assert [p.annual_turnover for p in points] == [42.0, 42.0, 42.0]
