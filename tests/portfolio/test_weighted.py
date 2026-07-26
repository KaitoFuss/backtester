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


def test_zero_score_without_position_yields_no_orders() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0}))

    assert orders == []


def test_zero_score_closes_existing_position() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0}))

    assert len(orders) == 1
    assert orders[0].ticker == "AAPL"
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_absent_ticker_holds_existing_position() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 200.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="MSFT", quantity=5, direction="BUY", fill_price=200.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0}))

    assert all(o.ticker != "MSFT" for o in orders)


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

    assert portfolio.mark_to_market() == 10_000.0 - 1_000.0 - 1.0 + 10 * 100.0


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


def test_get_position_tracks_entry_price_and_date() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    entry = datetime(2024, 3, 1)

    assert portfolio.get_position("AAPL") is None

    portfolio.process_fill(
        FillEvent(timestamp=entry, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    position = portfolio.get_position("AAPL")
    assert position is not None
    assert position.quantity == 10
    assert position.entry_price == 100.0
    assert position.entry_date == entry


def test_adding_to_position_keeps_original_entry() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    first, second = datetime(2024, 3, 1), datetime(2024, 3, 8)
    portfolio.process_fill(
        FillEvent(timestamp=first, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.process_fill(
        FillEvent(timestamp=second, ticker="AAPL", quantity=5, direction="BUY", fill_price=200.0)
    )

    position = portfolio.get_position("AAPL")
    assert position is not None
    assert position.quantity == 15
    assert position.entry_price == 100.0
    assert position.entry_date == first


def test_closing_position_clears_it() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=100.0)
    )

    assert portfolio.get_position("AAPL") is None


def test_no_resize_while_held_even_with_stronger_same_sign_score() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=100.0)

    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=1, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0}))

    assert orders == []


def test_entry_threshold_blocks_weak_signal_when_flat() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0, entry_threshold=0.5)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.4}))

    assert orders == []


def test_entry_threshold_opens_position_once_crossed() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(price_source=prices, initial_cash=10_000.0, entry_threshold=0.5)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.6}))

    assert len(orders) == 1
    assert orders[0].direction == "BUY"
    assert orders[0].quantity == round(1.0 * 10_000.0 / 100.0)


def test_no_resize_while_held_with_banding_enabled() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(
        price_source=prices, initial_cash=10_000.0, entry_threshold=0.5, exit_threshold=0.2
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.9}))

    assert orders == []


def test_exit_threshold_closes_on_weak_signal() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(
        price_source=prices, initial_cash=10_000.0, entry_threshold=0.5, exit_threshold=0.2
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.1}))

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_sign_flip_closes_position_even_above_exit_threshold() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = WeightedPortfolio(
        price_source=prices, initial_cash=10_000.0, entry_threshold=0.5, exit_threshold=0.2
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": -0.9}))

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10
