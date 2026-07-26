import math
import statistics
from collections import deque

from backtester.core.events import MarketEvent, SignalEvent, Ticker


class ZScoreMovingAverageStrategy:
    def __init__(self, window: int = 20) -> None:
        self._window = window
        self._returns: dict[Ticker, deque[float]] = {}
        self._last_close: dict[Ticker, float] = {}

    def process_market(self, event: MarketEvent) -> SignalEvent:
        scores: dict[Ticker, float] = {}

        for ticker, bar in event.bars.items():
            prev_close = self._last_close.get(ticker)
            self._last_close[ticker] = bar.close
            if prev_close is None:
                continue

            returns = self._returns.setdefault(ticker, deque(maxlen=self._window))
            returns.append(math.log(bar.close / prev_close))

            if len(returns) < self._window:
                continue

            stdev = statistics.stdev(returns)
            if stdev == 0:
                continue

            z = (returns[-1] - statistics.fmean(returns)) / stdev
            scores[ticker] = -z

        return SignalEvent(timestamp=event.timestamp, scores=scores)
