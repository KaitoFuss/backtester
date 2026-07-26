from datetime import datetime, timedelta

from backtester.core.events import Bar, FillEvent, MarketEvent, Position
from backtester.tracker.metrics import PerformanceTracker

TS = datetime(2024, 1, 1)


def _ts(n: int) -> datetime:
    return TS + timedelta(days=n)


class FakePortfolioView:
    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)
        self._positions: dict[str, Position] = {}

    def get_position(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)

    def mark_to_market(self) -> float:
        return next(self._values)

    def set_position(self, ticker: str, position: Position | None) -> None:
        if position is None:
            self._positions.pop(ticker, None)
        else:
            self._positions[ticker] = position


def test_mark_to_market_history_samples_portfolio_valuation_per_bar() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioView([1_000.0, 1_050.0]))

    tracker.track_market(MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0)}))
    tracker.track_market(MarketEvent(timestamp=_ts(1), bars={"AAPL": Bar(close=110.0)}))

    assert tracker.mark_to_market_history == [(_ts(0), 1_000.0), (_ts(1), 1_050.0)]


def test_metrics_with_flat_equity_are_zero() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioView([1_000.0] * 5))
    for i in range(5):
        tracker.track_market(MarketEvent(timestamp=_ts(i), bars={}))

    metrics = tracker.metrics()

    assert metrics.total_return == 0.0
    assert metrics.annualized_vol == 0.0
    assert metrics.sharpe == 0.0
    assert metrics.max_drawdown == 0.0


def test_metrics_with_insufficient_history_are_zero() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioView([1_000.0]))
    tracker.track_market(MarketEvent(timestamp=_ts(0), bars={}))

    metrics = tracker.metrics()

    assert metrics == tracker.metrics()
    assert metrics.total_return == 0.0


def test_max_drawdown_reflects_peak_to_trough_decline() -> None:
    values = [1_000.0, 1_200.0, 800.0, 900.0]
    tracker = PerformanceTracker(portfolio=FakePortfolioView(values))
    for i in range(len(values)):
        tracker.track_market(MarketEvent(timestamp=_ts(i), bars={}))

    metrics = tracker.metrics()

    peak = 1200.0
    trough = 800.0
    assert metrics.max_drawdown == trough / peak - 1


def test_trade_metrics_with_no_trades_are_zero() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioView([]))

    metrics = tracker.trade_metrics()

    assert metrics.num_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.payoff_factor == 0.0


def test_trade_metrics_computes_win_rate_and_payoff_factor() -> None:
    portfolio = FakePortfolioView([])
    tracker = PerformanceTracker(portfolio=portfolio)

    tracker.track_fill(
        FillEvent(timestamp=_ts(0), ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.set_position(
        "AAPL", Position(ticker="AAPL", quantity=10, entry_price=100.0, entry_date=_ts(0))
    )
    tracker.track_fill(
        FillEvent(timestamp=_ts(1), ticker="AAPL", quantity=10, direction="SELL", fill_price=110.0)
    )
    portfolio.set_position("AAPL", None)

    tracker.track_fill(
        FillEvent(timestamp=_ts(2), ticker="MSFT", quantity=5, direction="BUY", fill_price=50.0)
    )
    portfolio.set_position(
        "MSFT", Position(ticker="MSFT", quantity=5, entry_price=50.0, entry_date=_ts(2))
    )
    tracker.track_fill(
        FillEvent(timestamp=_ts(3), ticker="MSFT", quantity=5, direction="SELL", fill_price=40.0)
    )
    portfolio.set_position("MSFT", None)

    metrics = tracker.trade_metrics()

    assert metrics.num_trades == 2
    assert metrics.win_rate == 0.5
    assert metrics.avg_win == 100.0
    assert metrics.avg_loss == -50.0
    assert metrics.risk_reward_ratio == 2.0
    assert metrics.payoff_factor == 2.0
    assert metrics.cpc_index == 0.5 * 2.0 * 2.0


def test_time_in_market_and_turnover_track_open_positions_across_bars() -> None:
    portfolio = FakePortfolioView([1_000.0, 1_000.0, 1_000.0])
    tracker = PerformanceTracker(portfolio=portfolio)

    tracker.track_market(MarketEvent(timestamp=_ts(0), bars={}))
    tracker.track_fill(
        FillEvent(timestamp=_ts(0), ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.set_position(
        "AAPL", Position(ticker="AAPL", quantity=10, entry_price=100.0, entry_date=_ts(0))
    )
    tracker.track_market(MarketEvent(timestamp=_ts(1), bars={}))
    tracker.track_fill(
        FillEvent(timestamp=_ts(1), ticker="AAPL", quantity=10, direction="SELL", fill_price=110.0)
    )
    portfolio.set_position("AAPL", None)
    tracker.track_market(MarketEvent(timestamp=_ts(2), bars={}))

    metrics = tracker.trade_metrics()

    assert metrics.time_in_market == 1 / 3
    assert metrics.turnover == (10 * 100.0 + 10 * 110.0) / 1_000.0
