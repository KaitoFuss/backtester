import logging
from datetime import datetime

import pytest

from backtester.core.events import FillEvent, Position
from backtester.portfolio.base import BasePortfolio, existing_gross

TS = datetime(2024, 1, 1)


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)


def test_existing_gross_is_fraction_of_equity() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 50.0})
    positions = {
        "AAPL": Position(ticker="AAPL", quantity=10, entry_price=100.0, entry_date=TS),
        "MSFT": Position(ticker="MSFT", quantity=-20, entry_price=50.0, entry_date=TS),
    }

    assert existing_gross(positions, prices, equity=2_000.0) == (1_000.0 + 1_000.0) / 2_000.0


def test_existing_gross_excludes_closing_tickers() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 50.0})
    positions = {
        "AAPL": Position(ticker="AAPL", quantity=10, entry_price=100.0, entry_date=TS),
        "MSFT": Position(ticker="MSFT", quantity=-20, entry_price=50.0, entry_date=TS),
    }

    assert existing_gross(positions, prices, equity=2_000.0, closing={"MSFT"}) == 1_000.0 / 2_000.0


def test_mark_to_market_sums_cash_and_position_value() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = BasePortfolio(price_source=prices, initial_cash=1_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=90.0)
    )

    assert portfolio.mark_to_market() == 1_000.0 - 900.0 + 10 * 100.0


def test_equity_excludes_position_with_missing_price_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = BasePortfolio(price_source=prices, initial_cash=10_000.0)
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


def test_fill_opens_new_position() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = BasePortfolio(price_source=prices, initial_cash=10_000.0)
    fill = FillEvent(
        timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0, commission=1.0
    )

    portfolio.process_fill(fill)

    assert portfolio.mark_to_market() == 10_000.0 - 10 * 100.0 - 1.0 + 10 * 100.0
    assert portfolio.get_position("AAPL") == Position(
        ticker="AAPL", quantity=10, entry_price=100.0, entry_date=TS
    )


def test_fill_closing_position_to_flat_clears_it() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = BasePortfolio(price_source=prices, initial_cash=1_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=90.0)
    )

    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=95.0)
    )

    assert portfolio.get_position("AAPL") is None


def test_fill_flip_direction_resets_cost_basis() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = BasePortfolio(price_source=prices, initial_cash=1_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=90.0)
    )

    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=20, direction="SELL", fill_price=95.0)
    )

    assert portfolio.get_position("AAPL") == Position(
        ticker="AAPL", quantity=-10, entry_price=95.0, entry_date=TS
    )


def test_fill_adding_to_a_position_averages_the_cost_basis() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = BasePortfolio(price_source=prices, initial_cash=1_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=90.0)
    )
    later = datetime(2024, 3, 8)

    portfolio.process_fill(
        FillEvent(timestamp=later, ticker="AAPL", quantity=5, direction="BUY", fill_price=120.0)
    )

    # (10 * 90 + 5 * 120) / 15, and entry_date stays at the first entry so
    # holding period still measures from when the position was established.
    assert portfolio.get_position("AAPL") == Position(
        ticker="AAPL", quantity=15, entry_price=100.0, entry_date=TS
    )


def test_fill_adding_to_a_short_averages_the_cost_basis() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = BasePortfolio(price_source=prices, initial_cash=1_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=90.0)
    )

    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=110.0)
    )

    assert portfolio.get_position("AAPL") == Position(
        ticker="AAPL", quantity=-20, entry_price=100.0, entry_date=TS
    )


def test_fill_partial_reduce_keeps_the_cost_basis() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = BasePortfolio(price_source=prices, initial_cash=1_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=90.0)
    )

    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=4, direction="SELL", fill_price=120.0)
    )

    assert portfolio.get_position("AAPL") == Position(
        ticker="AAPL", quantity=6, entry_price=90.0, entry_date=TS
    )


def test_cash_ignores_the_slippage_field() -> None:
    """slippage is reporting-only: the spread is already inside fill_price,
    so counting it again would double-charge every trade."""
    portfolio = BasePortfolio(price_source=FakePriceSource({"SPY": 100.0}), initial_cash=10_000.0)

    portfolio.process_fill(
        FillEvent(
            timestamp=datetime(2024, 1, 1),
            ticker="SPY",
            quantity=10,
            direction="BUY",
            fill_price=100.1,
            commission=0.5,
            slippage=999.0,
        )
    )

    # cash = 10_000 - (10 * 100.1) - 0.5, with slippage=999.0 having no effect;
    # equity adds the position back at 100.0. Asserted through mark_to_market()
    # rather than _cash, matching how every other test in this module reads the
    # portfolio.
    assert portfolio.mark_to_market() == pytest.approx(10_000.0 - 1001.0 - 0.5 + 1000.0)
