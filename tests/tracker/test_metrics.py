import statistics
from datetime import datetime, timedelta
from typing import Literal, cast

import pytest

from backtester.core.events import Bar, FillEvent, MarketEvent, Position
from backtester.tracker.metrics import (
    PerformanceTracker,
    drawdown_to_vol_ratio,
    monthly_returns_table,
    sharpe_ratio,
    strategy_correlation_matrix,
)

TS = datetime(2024, 1, 1)

# A bar with at least one live price; the tracker only reads the timestamp and
# the portfolio valuation, but it skips bars with no prices, so tests that just
# need an observation recorded pass this rather than an empty ``bars``.
LIVE_BARS = {"AAPL": Bar(close=100.0)}


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
        tracker.track_market(MarketEvent(timestamp=_ts(i), bars=LIVE_BARS))

    metrics = tracker.metrics()

    assert metrics.total_return == 0.0
    assert metrics.annualized_vol == 0.0
    assert metrics.sharpe == 0.0
    assert metrics.max_drawdown == 0.0


def test_metrics_with_insufficient_history_are_zero() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioView([1_000.0]))
    tracker.track_market(MarketEvent(timestamp=_ts(0), bars=LIVE_BARS))

    metrics = tracker.metrics()

    assert metrics == tracker.metrics()
    assert metrics.total_return == 0.0


def test_max_drawdown_reflects_peak_to_trough_decline() -> None:
    values = [1_000.0, 1_200.0, 800.0, 900.0]
    tracker = PerformanceTracker(portfolio=FakePortfolioView(values))
    for i in range(len(values)):
        tracker.track_market(MarketEvent(timestamp=_ts(i), bars=LIVE_BARS))

    metrics = tracker.metrics()

    peak = 1200.0
    trough = 800.0
    assert metrics.max_drawdown == trough / peak - 1


def test_drawdown_to_vol_ratio_normalizes_drawdown_by_vol() -> None:
    assert drawdown_to_vol_ratio(-0.2, 0.4) == pytest.approx(0.5)


def test_drawdown_to_vol_ratio_is_zero_without_vol() -> None:
    assert drawdown_to_vol_ratio(-0.2, 0.0) == 0.0


def test_metrics_expose_drawdown_to_vol_ratio() -> None:
    values = [1_000.0, 1_200.0, 800.0, 900.0]
    tracker = PerformanceTracker(portfolio=FakePortfolioView(values))
    for i in range(len(values)):
        tracker.track_market(MarketEvent(timestamp=_ts(i), bars=LIVE_BARS))

    metrics = tracker.metrics()

    assert metrics.drawdown_to_vol == pytest.approx(
        abs(metrics.max_drawdown) / metrics.annualized_vol
    )


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

    tracker.track_market(MarketEvent(timestamp=_ts(0), bars=LIVE_BARS))
    tracker.track_fill(
        FillEvent(timestamp=_ts(0), ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.set_position(
        "AAPL", Position(ticker="AAPL", quantity=10, entry_price=100.0, entry_date=_ts(0))
    )
    tracker.track_market(MarketEvent(timestamp=_ts(1), bars=LIVE_BARS))
    tracker.track_fill(
        FillEvent(timestamp=_ts(1), ticker="AAPL", quantity=10, direction="SELL", fill_price=110.0)
    )
    portfolio.set_position("AAPL", None)
    tracker.track_market(MarketEvent(timestamp=_ts(2), bars=LIVE_BARS))

    metrics = tracker.trade_metrics()

    expected_years = (_ts(2) - _ts(0)).days / 365.25
    assert metrics.time_in_market == 1 / 3
    assert metrics.annual_turnover == pytest.approx(
        (10 * 100.0 + 10 * 110.0) / 1_000.0 / expected_years
    )


def test_track_market_skips_bars_with_no_prices() -> None:
    # A no-data bar (universe outside its data window) must not record an equity
    # point; the reported series ends at the last live bar, not the last file.
    tracker = PerformanceTracker(portfolio=FakePortfolioView([1_000.0, 1_050.0]))

    tracker.track_market(MarketEvent(timestamp=_ts(0), bars=LIVE_BARS))
    tracker.track_market(MarketEvent(timestamp=_ts(1), bars={}))
    tracker.track_market(MarketEvent(timestamp=_ts(2), bars=LIVE_BARS))

    assert tracker.mark_to_market_history == [(_ts(0), 1_000.0), (_ts(2), 1_050.0)]


def _fill(
    day: int, ticker: str, quantity: int, direction: Literal["BUY", "SELL"], price: float
) -> FillEvent:
    return FillEvent(
        timestamp=_ts(day),
        ticker=ticker,
        quantity=quantity,
        direction=direction,
        fill_price=price,
    )


def test_scale_in_averages_the_entry_price() -> None:
    # Two adds then a full close: PnL must use the quantity-weighted entry
    # (110), not the first or last fill price.
    tracker = PerformanceTracker(portfolio=FakePortfolioView([]))
    tracker.track_fill(_fill(0, "AAPL", 10, "BUY", 100.0))
    tracker.track_fill(_fill(1, "AAPL", 10, "BUY", 120.0))
    tracker.track_fill(_fill(2, "AAPL", 20, "SELL", 130.0))

    metrics = tracker.trade_metrics()

    assert metrics.num_trades == 1
    assert metrics.avg_win == pytest.approx(20 * (130.0 - 110.0))


def test_partial_close_realizes_each_leg_against_the_same_basis() -> None:
    tracker = PerformanceTracker(portfolio=FakePortfolioView([]))
    tracker.track_fill(_fill(0, "AAPL", 10, "BUY", 100.0))
    tracker.track_fill(_fill(1, "AAPL", 4, "SELL", 110.0))  # +40
    tracker.track_fill(_fill(2, "AAPL", 6, "SELL", 90.0))  # -60

    metrics = tracker.trade_metrics()

    assert metrics.num_trades == 2
    assert metrics.win_rate == 0.5
    assert metrics.avg_win == pytest.approx(4 * (110.0 - 100.0))
    assert metrics.avg_loss == pytest.approx(6 * (90.0 - 100.0))


def test_flip_closes_the_old_position_and_opens_the_remainder() -> None:
    # BUY 10, then SELL 15 flips to short 5, then BUY 5 flattens: two closed
    # trades (a long and a short), the second built from the flipped remainder.
    tracker = PerformanceTracker(portfolio=FakePortfolioView([]))
    tracker.track_fill(_fill(0, "AAPL", 10, "BUY", 100.0))
    tracker.track_fill(_fill(1, "AAPL", 15, "SELL", 120.0))  # long +200, opens short 5
    tracker.track_fill(_fill(2, "AAPL", 5, "BUY", 110.0))  # short closed for +50

    metrics = tracker.trade_metrics()

    assert metrics.num_trades == 2
    assert metrics.win_rate == 1.0
    assert metrics.avg_win == pytest.approx((10 * 20.0 + 5 * 10.0) / 2)


def test_annualized_return_scales_with_elapsed_calendar_time() -> None:
    # Same total return and same sample count, but a 10-day span annualizes far
    # more aggressively than a 100-day span — the metric reads elapsed calendar
    # time, not the raw number of observations.
    def annualized(days: list[int]) -> float:
        tracker = PerformanceTracker(portfolio=FakePortfolioView([1_000.0, 1_000.0, 1_200.0]))
        for day in days:
            tracker.track_market(MarketEvent(timestamp=_ts(day), bars=LIVE_BARS))
        return tracker.metrics().annualized_return

    short_span = annualized([0, 5, 10])
    long_span = annualized([0, 50, 100])

    assert short_span > long_span > 0.2  # 0.2 == the raw total return


def test_monthly_returns_table_buckets_by_year_and_month() -> None:
    history = [
        (datetime(2024, 1, 1), 1_000.0),
        (datetime(2024, 1, 31), 1_100.0),
        (datetime(2024, 2, 1), 1_100.0),
        (datetime(2024, 2, 28), 1_210.0),
    ]

    table = monthly_returns_table(history)

    assert table.loc[2024, "Jan"] == pytest.approx(0.10)
    assert table.loc[2024, "Feb"] == pytest.approx(0.10)
    assert table.loc[2024, "Annual Return"] == pytest.approx(1.21 - 1)
    assert table.loc[2024, "Max DD"] == pytest.approx(0.0)


def test_monthly_returns_table_with_insufficient_history_is_empty() -> None:
    table = monthly_returns_table([(datetime(2024, 1, 1), 1_000.0)])

    assert table.empty


def test_strategy_correlation_matrix_is_one_for_identical_series() -> None:
    history = [
        (datetime(2024, 1, 1), 1_000.0),
        (datetime(2024, 1, 2), 1_010.0),
        (datetime(2024, 1, 3), 990.0),
        (datetime(2024, 1, 4), 1_020.0),
    ]

    correlation = strategy_correlation_matrix({"A": history, "B": history})

    assert correlation.loc["A", "B"] == pytest.approx(1.0)


def test_sharpe_is_annualized_mean_over_stdev() -> None:
    returns = [0.01, -0.005, 0.02, 0.0, 0.015]

    result = sharpe_ratio(returns, periods_per_year=252.0)

    mean = statistics.fmean(returns)
    expected = mean / statistics.stdev(returns) * 252.0**0.5
    assert result == pytest.approx(expected)


def test_risk_free_rate_lowers_sharpe() -> None:
    returns = [0.01, -0.005, 0.02, 0.0, 0.015]

    without = sharpe_ratio(returns, periods_per_year=252.0)
    with_rf = sharpe_ratio(returns, periods_per_year=252.0, risk_free_rate=0.02)

    assert with_rf < without


def test_risk_free_rate_is_deannualized_geometrically() -> None:
    # A constant-returns series would make `excess` constant too (stdev == 0,
    # dividing by zero even in the "expected" computation below), so this
    # needs genuine dispersion to exercise the geometric de-annualization.
    returns = [0.002, -0.001, 0.0015, 0.0005, 0.001, -0.0005, 0.0025, 0.0, 0.0012, -0.0008]
    rf = 0.02
    rf_period = (1 + rf) ** (1 / 252.0) - 1

    result = sharpe_ratio(returns, periods_per_year=252.0, risk_free_rate=rf)

    excess = [r - rf_period for r in returns]
    expected = statistics.fmean(excess) / statistics.stdev(excess) * 252.0**0.5
    assert result == pytest.approx(expected)


def test_zero_dispersion_gives_zero_sharpe() -> None:
    assert sharpe_ratio([0.01, 0.01, 0.01], periods_per_year=252.0) == 0.0


def test_fewer_than_two_returns_gives_zero_sharpe() -> None:
    assert sharpe_ratio([0.01], periods_per_year=252.0) == 0.0


def _tracker_over(values: list[float], risk_free_rate: float = 0.0) -> PerformanceTracker:
    """A tracker fed one bar per value, so its equity curve is exactly `values`."""
    tracker = PerformanceTracker(portfolio=FakePortfolioView(values), risk_free_rate=risk_free_rate)
    for i in range(len(values)):
        tracker.track_market(MarketEvent(timestamp=_ts(i), bars=LIVE_BARS))
    return tracker


def test_tracker_uses_the_configured_risk_free_rate() -> None:
    rising = [1_000.0 * 1.001**i for i in range(60)]

    plain = _tracker_over(rising)
    charged = _tracker_over(rising, risk_free_rate=0.05)

    assert charged.metrics().sharpe < plain.metrics().sharpe


def test_zero_risk_free_rate_is_the_default() -> None:
    rising = [1_000.0 * 1.001**i for i in range(60)]

    assert (
        _tracker_over(rising).metrics().sharpe
        == _tracker_over(rising, risk_free_rate=0.0).metrics().sharpe
    )


def test_strategy_correlation_matrix_is_negative_for_inverse_series() -> None:
    base = [1_000.0, 1_010.0, 990.0, 1_020.0]
    inverse = [1_000.0, 990.0, 1_010.0, 980.0]
    timestamps = [datetime(2024, 1, i + 1) for i in range(len(base))]

    correlation = strategy_correlation_matrix(
        {
            "A": list(zip(timestamps, base, strict=True)),
            "B": list(zip(timestamps, inverse, strict=True)),
        }
    )

    assert cast(float, correlation.loc["A", "B"]) < 0


def _tracker_spanning(years: float, traded_notional: float, equity: float) -> PerformanceTracker:
    """Equity flat at `equity` over `years`, with one round trip of
    `traded_notional` total (half on the buy, half on the sell)."""
    days = round(years * 365.25)
    tracker = PerformanceTracker(portfolio=FakePortfolioView([equity, equity]))
    tracker.track_market(MarketEvent(timestamp=_ts(0), bars=LIVE_BARS))
    tracker.track_market(MarketEvent(timestamp=_ts(days), bars=LIVE_BARS))

    half = traded_notional / 2
    for direction in cast(list[Literal["BUY", "SELL"]], ["BUY", "SELL"]):
        tracker.track_fill(
            FillEvent(
                timestamp=_ts(0),
                ticker="AAPL",
                quantity=100,
                direction=direction,
                fill_price=half / 100,
            )
        )
    return tracker


def test_turnover_is_annualized() -> None:
    """Same traded notional over twice the span must report half the turnover."""
    one_year = _tracker_spanning(years=1, traded_notional=1_000_000.0, equity=100_000.0)
    two_years = _tracker_spanning(years=2, traded_notional=1_000_000.0, equity=100_000.0)

    assert one_year.trade_metrics().annual_turnover == pytest.approx(10.0, rel=0.01)
    assert two_years.trade_metrics().annual_turnover == pytest.approx(5.0, rel=0.01)


def test_turnover_is_zero_without_a_measurable_span() -> None:
    """A single observation gives no elapsed time to annualize over. The round
    trip matters: without it `trade_metrics` returns early on "no trades" and
    the span guard this test exists for is never reached."""
    tracker = PerformanceTracker(portfolio=FakePortfolioView([100_000.0]))
    tracker.track_market(MarketEvent(timestamp=_ts(0), bars=LIVE_BARS))
    for direction in cast(list[Literal["BUY", "SELL"]], ["BUY", "SELL"]):
        tracker.track_fill(
            FillEvent(
                timestamp=_ts(0),
                ticker="AAPL",
                quantity=100,
                direction=direction,
                fill_price=50.0,
            )
        )

    assert tracker.trade_metrics().num_trades == 1
    assert tracker.trade_metrics().annual_turnover == 0.0
