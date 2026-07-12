from datetime import datetime, timedelta

from backtester.core.events import Bar, MarketEvent
from backtester.strategy.buy_and_hold import BuyAndHoldStrategy

TS = datetime(2024, 1, 1)


def _ts(n: int) -> datetime:
    return TS + timedelta(days=n)


def test_first_bar_buys_all_tickers_at_equal_weight() -> None:
    strategy = BuyAndHoldStrategy()

    signals = strategy.process_market(
        MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0), "MSFT": Bar(close=200.0)})
    )

    assert len(signals) == 1
    assert signals[0].scores == {"AAPL": 1.0, "MSFT": 1.0}


def test_no_signal_on_subsequent_bars() -> None:
    strategy = BuyAndHoldStrategy()
    strategy.process_market(MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0)}))

    signals = strategy.process_market(
        MarketEvent(timestamp=_ts(1), bars={"AAPL": Bar(close=101.0)})
    )

    assert signals == []


def test_empty_bars_yields_no_signal() -> None:
    strategy = BuyAndHoldStrategy()

    signals = strategy.process_market(MarketEvent(timestamp=_ts(0), bars={}))

    assert signals == []
