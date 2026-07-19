import logging
from datetime import datetime

import pytest

from backtester.core.events import FillEvent, SignalEvent
from backtester.portfolio.weighted import WeightedPortfolio

TS = datetime(2024, 1, 1)


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)


def test_signal_sizes_orders_proportional_to_score() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 200.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0, "MSFT": -1.0}))

    assert {o.ticker: o for o in orders}.keys() == {"AAPL", "MSFT"}
    aapl = next(o for o in orders if o.ticker == "AAPL")
    msft = next(o for o in orders if o.ticker == "MSFT")
    assert aapl.direction == "BUY"
    assert aapl.quantity == round(0.5 * 10_000.0 / 100.0)
    assert msft.direction == "SELL"
    assert msft.quantity == round(0.5 * 10_000.0 / 200.0)


def test_signal_skips_tickers_with_unknown_price() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"MSFT": 1.0}))

    assert orders == []


def test_all_zero_scores_yield_no_orders() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0}))

    assert orders == []


def test_fill_updates_cash_and_positions() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)

    portfolio.process_fill(
        FillEvent(
            timestamp=TS,
            ticker="AAPL",
            quantity=10,
            direction="BUY",
            fill_price=100.0,
            commission=1.0,
        )
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0}))
    equity = (10_000.0 - 1_000.0 - 1.0) + 10 * 100.0
    target_shares = round(equity / 100.0)
    assert orders[0].quantity == target_shares - 10


def test_equity_excludes_position_with_missing_price_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="MSFT", quantity=5, direction="BUY", fill_price=50.0)
    )

    with caplog.at_level(logging.WARNING):
        equity = portfolio.mark_to_market()

    expected_cash = 10_000.0 - 10 * 100.0 - 5 * 50.0
    assert equity == expected_cash + 10 * 100.0
    assert "MSFT" in caplog.text


def test_no_order_when_position_already_at_target() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=100.0)

    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=1, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0}))

    assert orders == []
