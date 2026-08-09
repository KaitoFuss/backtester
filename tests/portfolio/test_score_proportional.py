import logging
from datetime import datetime

import pytest

from backtester.core.events import FillEvent, SignalEvent
from backtester.portfolio.score_proportional import ScoreProportionalPortfolio

TS = datetime(2024, 1, 1)


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)


def test_signal_sizes_orders_proportional_to_score() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 200.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 3.0, "MSFT": -1.0}))

    aapl = next(o for o in orders if o.ticker == "AAPL")
    msft = next(o for o in orders if o.ticker == "MSFT")
    assert aapl.direction == "BUY"
    assert aapl.quantity == round(0.75 * 10_000.0 / 100.0)
    assert msft.direction == "SELL"
    assert msft.quantity == round(0.25 * 10_000.0 / 200.0)


def test_a_tiny_nonzero_score_still_gets_weight_with_no_entry_gate() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0, "MSFT": 0.01}))

    assert {o.ticker for o in orders} == {"AAPL", "MSFT"}
    msft = next(o for o in orders if o.ticker == "MSFT")
    assert msft.direction == "BUY"


def test_equal_scores_split_the_budget_evenly() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 100.0, "GOOG": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=30_000.0)

    orders = portfolio.process_signal(
        SignalEvent(timestamp=TS, scores={"AAPL": 1.0, "MSFT": 1.0, "GOOG": 1.0})
    )

    assert {o.quantity for o in orders} == {round(30_000.0 / 3 / 100.0)}
    assert all(o.direction == "BUY" for o in orders)


def test_signal_skips_tickers_with_unknown_price() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"MSFT": 1.0}))

    assert orders == []


def test_zero_score_without_position_yields_no_orders() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0}))

    assert orders == []


def test_zero_score_closes_existing_position() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0}))

    assert len(orders) == 1
    assert orders[0].ticker == "AAPL"
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_absent_ticker_is_held_and_reserves_its_gross() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)
    # Hold 60 shares of MSFT = $6000 = 60% of equity; MSFT is not scored below,
    # so it must be left alone and its 60% withheld from AAPL's budget.
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="MSFT", quantity=60, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0}))

    assert all(o.ticker != "MSFT" for o in orders)
    aapl = next(o for o in orders if o.ticker == "AAPL")
    assert aapl.quantity == round(0.4 * 10_000.0 / 100.0)


def test_stronger_score_scales_an_existing_position_up_by_the_delta() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)

    portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0, "MSFT": 1.0}))
    for ticker in ("AAPL", "MSFT"):
        portfolio.process_fill(
            FillEvent(timestamp=TS, ticker=ticker, quantity=50, direction="BUY", fill_price=100.0)
        )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 3.0, "MSFT": 1.0}))

    aapl = next(o for o in orders if o.ticker == "AAPL")
    msft = next(o for o in orders if o.ticker == "MSFT")
    # Targets move from 50/50 to 75/25 shares; orders are the deltas only.
    assert (aapl.direction, aapl.quantity) == ("BUY", 25)
    assert (msft.direction, msft.quantity) == ("SELL", 25)


def test_unchanged_score_produces_no_order() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0}))

    assert orders == []


def test_sign_flip_crosses_zero_in_a_single_order() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": -1.0}))

    assert len(orders) == 1
    # +100 held, -100 targeted: one 200-share sell rather than a close and an open.
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 200


def test_dollar_neutral_weights_sum_to_zero() -> None:
    prices = FakePriceSource({"A": 100.0, "B": 100.0, "C": 100.0})
    portfolio = ScoreProportionalPortfolio(
        price_source=prices, initial_cash=30_000.0, dollar_neutral=True
    )

    orders = portfolio.process_signal(
        SignalEvent(timestamp=TS, scores={"A": 3.0, "B": 1.0, "C": -1.0})
    )

    signed_notional = sum(
        (o.quantity if o.direction == "BUY" else -o.quantity) * 100.0 for o in orders
    )
    assert signed_notional == pytest.approx(0.0, abs=100.0)


def test_dollar_neutral_shorts_a_positive_score_below_the_mean() -> None:
    prices = FakePriceSource({"A": 100.0, "B": 100.0})
    portfolio = ScoreProportionalPortfolio(
        price_source=prices, initial_cash=10_000.0, dollar_neutral=True
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"A": 3.0, "B": 1.0}))

    b = next(o for o in orders if o.ticker == "B")
    # B's raw score is positive but sits below the cross-sectional mean of 2.0,
    # so relative value shorts it.
    assert b.direction == "SELL"


def test_dollar_neutral_with_a_single_survivor_takes_no_position() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = ScoreProportionalPortfolio(
        price_source=prices, initial_cash=10_000.0, dollar_neutral=True
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 2.0}))

    # One name demeans to exactly zero — there is nothing to be neutral against.
    assert orders == []


def test_fill_updates_cash_and_positions() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)

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
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)
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


def test_closing_position_clears_it() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = ScoreProportionalPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=100.0)
    )

    assert portfolio.get_position("AAPL") is None
