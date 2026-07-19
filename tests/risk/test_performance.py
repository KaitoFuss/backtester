from datetime import datetime, timedelta

from backtester.core.events import Bar, MarketEvent
from backtester.risk.performance import PerformanceTracker

TS = datetime(2024, 1, 1)


def _ts(n: int) -> datetime:
    return TS + timedelta(days=n)


class FakePortfolioValuer:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)

    def mark_to_market(self) -> float:
        return next(self._values)


def test_mark_to_market_history_samples_portfolio_valuation_per_bar() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioValuer([1_000.0, 1_050.0]))

    tracker.evaluate_market(MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0)}))
    tracker.evaluate_market(MarketEvent(timestamp=_ts(1), bars={"AAPL": Bar(close=110.0)}))

    assert tracker.mark_to_market_history == [(_ts(0), 1_000.0), (_ts(1), 1_050.0)]


def test_metrics_with_flat_equity_are_zero() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioValuer([1_000.0] * 5))
    for i in range(5):
        tracker.evaluate_market(MarketEvent(timestamp=_ts(i), bars={}))

    metrics = tracker.metrics()

    assert metrics.total_return == 0.0
    assert metrics.annualized_vol == 0.0
    assert metrics.sharpe == 0.0
    assert metrics.max_drawdown == 0.0


def test_metrics_with_insufficient_history_are_zero() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioValuer([1_000.0]))
    tracker.evaluate_market(MarketEvent(timestamp=_ts(0), bars={}))

    metrics = tracker.metrics()

    assert metrics == tracker.metrics()
    assert metrics.total_return == 0.0


def test_max_drawdown_reflects_peak_to_trough_decline() -> None:
    values = [1_000.0, 1_200.0, 800.0, 900.0]
    tracker = PerformanceTracker(portfolio=FakePortfolioValuer(values))
    for i in range(len(values)):
        tracker.evaluate_market(MarketEvent(timestamp=_ts(i), bars={}))

    metrics = tracker.metrics()

    peak = 1200.0
    trough = 800.0
    assert metrics.max_drawdown == trough / peak - 1
