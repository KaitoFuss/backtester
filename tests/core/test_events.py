import dataclasses
from datetime import datetime

import pytest

from backtester.core.events import Bar, FillEvent, MarketEvent, OrderEvent, SignalEvent

TS = datetime(2024, 1, 1)


def test_bar_defaults():
    bar = Bar(close=100.0)
    assert bar.close == 100.0
    assert bar.open is None
    assert bar.high is None
    assert bar.low is None
    assert bar.volume is None


def test_bar_full():
    bar = Bar(close=100.0, open=98.0, high=102.0, low=97.0, volume=1_000_000.0)
    assert bar.high == 102.0


def test_bar_frozen():
    bar = Bar(close=100.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bar.close = 200.0  # type: ignore[misc]


def test_market_event_type():
    event = MarketEvent(timestamp=TS, bars={"AAPL": Bar(close=150.0)})
    assert event.type == "MARKET"
    assert event.bars["AAPL"].close == 150.0


def test_market_event_frozen():
    event = MarketEvent(timestamp=TS, bars={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.timestamp = datetime(2024, 2, 1)  # type: ignore[misc]


def test_market_event_bars_immutable():
    event = MarketEvent(timestamp=TS, bars={"AAPL": Bar(close=150.0)})
    with pytest.raises(TypeError):
        event.bars["AAPL"] = Bar(close=0.0)  # type: ignore[index]


def test_signal_event_type():
    event = SignalEvent(timestamp=TS, scores={"AAPL": 0.8, "GOOG": -0.3})
    assert event.type == "SIGNAL"
    assert event.scores["AAPL"] == pytest.approx(0.8)


def test_signal_event_frozen():
    event = SignalEvent(timestamp=TS, scores={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.scores = {}  # type: ignore[misc]


def test_signal_event_scores_immutable():
    event = SignalEvent(timestamp=TS, scores={"AAPL": 0.8})
    with pytest.raises(TypeError):
        event.scores["AAPL"] = 0.0  # type: ignore[index]


def test_order_event_buy():
    event = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    assert event.type == "ORDER"
    assert event.direction == "BUY"


def test_order_event_sell():
    event = OrderEvent(timestamp=TS, ticker="MSFT", quantity=50, direction="SELL")
    assert event.direction == "SELL"


def test_order_event_frozen():
    event = OrderEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.quantity = 999  # type: ignore[misc]


def test_fill_event_type():
    event = FillEvent(
        timestamp=TS,
        ticker="AAPL",
        quantity=100,
        direction="BUY",
        fill_price=150.25,
        commission=1.0,
        slippage=0.05,
    )
    assert event.type == "FILL"
    assert event.fill_price == pytest.approx(150.25)
    assert event.commission == pytest.approx(1.0)
    assert event.slippage == pytest.approx(0.05)


def test_fill_event_frozen():
    event = FillEvent(
        timestamp=TS,
        ticker="AAPL",
        quantity=100,
        direction="BUY",
        fill_price=150.0,
        commission=1.0,
        slippage=0.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.fill_price = 0.0  # type: ignore[misc]
