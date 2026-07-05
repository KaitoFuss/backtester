from datetime import datetime

from backtester.core.events import Bar, FillEvent, MarketEvent, OrderEvent, SignalEvent, Ticker
from backtester.core.queue import EventQueue

TS = datetime(2024, 1, 1)
AAPL = Ticker("AAPL")


def test_queue_starts_empty():
    q = EventQueue()
    assert q.empty()


def test_queue_put_get_market():
    q = EventQueue()
    event = MarketEvent(timestamp=TS, bars={AAPL: Bar(close=100.0)})
    q.put(event)
    assert not q.empty()
    result = q.get()
    assert result == event
    assert q.empty()


def test_queue_fifo_ordering():
    q = EventQueue()
    e1 = MarketEvent(timestamp=TS, bars={})
    e2 = SignalEvent(timestamp=TS, scores={AAPL: 0.5})
    q.put(e1)
    q.put(e2)
    assert q.get() == e1
    assert q.get() == e2


def test_queue_accepts_all_event_types():
    q = EventQueue()
    q.put(MarketEvent(timestamp=TS, bars={}))
    q.put(SignalEvent(timestamp=TS, scores={}))
    q.put(OrderEvent(timestamp=TS, ticker=AAPL, quantity=10, direction="BUY"))
    q.put(
        FillEvent(
            timestamp=TS,
            ticker=AAPL,
            quantity=10,
            direction="BUY",
            fill_price=100.0,
            commission=0.5,
            slippage=0.1,
        )
    )
    count = 0
    while not q.empty():
        q.get()
        count += 1
    assert count == 4
