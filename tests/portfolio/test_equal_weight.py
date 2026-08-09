from datetime import datetime

from backtester.core.events import FillEvent, SignalEvent
from backtester.portfolio.equal_weight import EqualWeightPortfolio

TS = datetime(2024, 1, 1)


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)


def test_scored_tickers_split_the_budget_evenly() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 200.0})
    portfolio = EqualWeightPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0, "MSFT": 1.0}))

    aapl = next(o for o in orders if o.ticker == "AAPL")
    msft = next(o for o in orders if o.ticker == "MSFT")
    assert aapl.quantity == round(0.5 * 10_000.0 / 100.0)
    assert msft.quantity == round(0.5 * 10_000.0 / 200.0)
    assert all(o.direction == "BUY" for o in orders)


def test_score_magnitude_is_ignored() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 100.0})
    portfolio = EqualWeightPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0, "MSFT": 9.0}))

    assert {o.quantity for o in orders} == {round(0.5 * 10_000.0 / 100.0)}


def test_held_ticker_is_never_retraded() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = EqualWeightPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY", fill_price=100.0)
    )

    assert portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0})) == []
    assert portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0})) == []
    assert portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": -1.0})) == []


def test_new_ticker_takes_only_the_remaining_budget() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 100.0})
    portfolio = EqualWeightPortfolio(price_source=prices, initial_cash=10_000.0)
    # Hold 60 shares of AAPL = 60% of equity; 40% remains for MSFT.
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=60, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"MSFT": 1.0}))

    assert len(orders) == 1
    assert orders[0].quantity == round(0.4 * 10_000.0 / 100.0)


def test_zero_score_and_unknown_price_are_skipped() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = EqualWeightPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(
        SignalEvent(timestamp=TS, scores={"AAPL": 0.0, "MSFT": 1.0}),
    )

    assert orders == []


def test_negative_score_opens_a_short() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = EqualWeightPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": -1.0}))

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
