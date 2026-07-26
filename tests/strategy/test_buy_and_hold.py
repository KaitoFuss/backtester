from datetime import datetime, timedelta

from backtester.core.events import Bar, MarketEvent
from backtester.strategy.buy_and_hold import BuyAndHoldStrategy

TS = datetime(2024, 1, 1)


def _ts(n: int) -> datetime:
    return TS + timedelta(days=n)


def test_first_bar_buys_all_tickers_at_equal_weight() -> None:
    strategy = BuyAndHoldStrategy()

    signal = strategy.process_market(
        MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0), "MSFT": Bar(close=200.0)})
    )

    assert signal.scores == {"AAPL": 1.0, "MSFT": 1.0}


def test_empty_signal_when_no_new_tickers_appear() -> None:
    strategy = BuyAndHoldStrategy()
    strategy.process_market(MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0)}))

    signal = strategy.process_market(MarketEvent(timestamp=_ts(1), bars={"AAPL": Bar(close=101.0)}))

    assert signal.scores == {}


def test_late_arriving_ticker_triggers_full_universe_resignal() -> None:
    strategy = BuyAndHoldStrategy()
    strategy.process_market(MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0)}))

    signal = strategy.process_market(
        MarketEvent(timestamp=_ts(1), bars={"AAPL": Bar(close=101.0), "MSFT": Bar(close=200.0)})
    )

    assert signal.scores == {"AAPL": 1.0, "MSFT": 1.0}


def test_empty_bars_yields_empty_signal() -> None:
    strategy = BuyAndHoldStrategy()

    signal = strategy.process_market(MarketEvent(timestamp=_ts(0), bars={}))

    assert signal.scores == {}
