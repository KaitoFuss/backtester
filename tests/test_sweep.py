from collections.abc import Sequence
from dataclasses import dataclass, replace

import pytest

from backtester import sweep
from backtester.config import BacktestConfig
from backtester.sweep import run_cost_sweep
from backtester.tracker.metrics import PerformanceMetrics, TradeMetrics


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

    points = run_cost_sweep(ladder, config=config)

    assert [c.cost_bps for c in seen] == [0.0, 0.25, 2.0]
    assert [c.commission_bps for c in seen] == [0.5, 0.5, 0.5]
    # Nothing but cost_bps moves between rungs.
    assert all(c == replace(config, cost_bps=c.cost_bps) for c in seen)
    assert [p.cost_bps for p in points] == [0.0, 0.25, 2.0]
    assert [p.commission_bps for p in points] == [0.5, 0.5, 0.5]
    assert [p.annual_turnover for p in points] == [42.0, 42.0, 42.0]
