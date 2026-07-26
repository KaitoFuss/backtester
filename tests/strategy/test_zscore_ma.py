from datetime import datetime, timedelta

from backtester.core.events import Bar, MarketEvent
from backtester.strategy.zscore_ma import ZScoreMovingAverageStrategy

TS = datetime(2024, 1, 1)


def _ts(n: int) -> datetime:
    return TS + timedelta(days=n)


def _bars(*closes: float) -> list[MarketEvent]:
    return [
        MarketEvent(timestamp=_ts(i), bars={"AAPL": Bar(close=c)}) for i, c in enumerate(closes)
    ]


def test_ticker_skipped_until_window_warmed_up() -> None:
    strategy = ZScoreMovingAverageStrategy(window=3)

    events = _bars(100.0, 101.0, 102.0)
    results = [strategy.process_market(e) for e in events]

    assert all(r.scores == {} for r in results)


def test_below_average_return_yields_positive_score() -> None:
    strategy = ZScoreMovingAverageStrategy(window=3)

    *warmup, last = _bars(100.0, 101.0, 102.0, 95.0)
    for event in warmup:
        strategy.process_market(event)
    signal = strategy.process_market(last)

    assert signal.scores["AAPL"] > 0


def test_above_average_return_yields_negative_score() -> None:
    strategy = ZScoreMovingAverageStrategy(window=3)

    *warmup, last = _bars(100.0, 99.0, 98.0, 110.0)
    for event in warmup:
        strategy.process_market(event)
    signal = strategy.process_market(last)

    assert signal.scores["AAPL"] < 0


def test_tickers_warm_up_independently() -> None:
    strategy = ZScoreMovingAverageStrategy(window=3)

    events = [
        MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0)}),
        MarketEvent(timestamp=_ts(1), bars={"AAPL": Bar(close=101.0), "MSFT": Bar(close=200.0)}),
        MarketEvent(timestamp=_ts(2), bars={"AAPL": Bar(close=102.0), "MSFT": Bar(close=202.0)}),
        MarketEvent(timestamp=_ts(3), bars={"AAPL": Bar(close=95.0), "MSFT": Bar(close=204.0)}),
    ]

    signals = [strategy.process_market(e) for e in events]
    last_scores = signals[-1].scores

    assert "AAPL" in last_scores
    assert "MSFT" not in last_scores


def test_ticker_gap_does_not_crash_and_still_warms_up() -> None:
    strategy = ZScoreMovingAverageStrategy(window=3)

    events = [
        MarketEvent(timestamp=_ts(0), bars={"AAPL": Bar(close=100.0)}),
        MarketEvent(timestamp=_ts(1), bars={"AAPL": Bar(close=101.0)}),
        MarketEvent(timestamp=_ts(2), bars={}),
        MarketEvent(timestamp=_ts(3), bars={"AAPL": Bar(close=102.0)}),
        MarketEvent(timestamp=_ts(4), bars={"AAPL": Bar(close=95.0)}),
    ]

    signals = [strategy.process_market(e) for e in events]

    assert "AAPL" in signals[-1].scores


def test_constant_returns_produce_no_score() -> None:
    strategy = ZScoreMovingAverageStrategy(window=3)

    closes = [100.0, 200.0, 400.0, 800.0]

    signals = [strategy.process_market(e) for e in _bars(*closes)]

    assert signals[-1].scores == {}


def test_winsor_clips_extreme_z_to_limit() -> None:
    closes = (100.0, 100.0, 100.0, 101.0)  # a jump after flat returns yields |z| > 0.5
    clipped = ZScoreMovingAverageStrategy(window=3, winsor_limit=0.5)
    unclipped = ZScoreMovingAverageStrategy(window=3, winsor_limit=100.0)

    for event in _bars(*closes):
        clipped_signal = clipped.process_market(event)
        unclipped_signal = unclipped.process_market(event)

    assert clipped_signal.scores["AAPL"] == -0.5
    assert abs(unclipped_signal.scores["AAPL"]) > 0.5
