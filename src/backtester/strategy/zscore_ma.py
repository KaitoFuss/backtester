import logging
import math
from collections import deque

from backtester.core.events import MarketEvent, SignalEvent, Ticker
from backtester.stats import mean_and_stdev

logger = logging.getLogger(__name__)


class ZScoreMovingAverageStrategy:
    """Mean-reversion on z-scored log returns. The z-score is winsorized to
    ``±winsor_limit`` before it becomes a signal, so an extreme move (often a
    regime break where the mean-reversion premise no longer holds) is capped
    rather than sized into linearly. Set ``winsor_limit`` very high to disable.
    """

    def __init__(self, window: int = 20, winsor_limit: float = 3.0) -> None:
        self._window = window
        self._winsor_limit = winsor_limit
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
                logger.debug(
                    "%s  %s: warming up (%d/%d returns)",
                    event.timestamp,
                    ticker,
                    len(returns),
                    self._window,
                )
                continue

            mean, stdev = mean_and_stdev(returns)
            if stdev == 0:
                logger.debug(
                    "%s  %s: zero return stdev over window, skipping", event.timestamp, ticker
                )
                continue

            raw_z = (returns[-1] - mean) / stdev
            z = max(-self._winsor_limit, min(self._winsor_limit, raw_z))
            scores[ticker] = -z
            logger.debug(
                "%s  %s: return=%.5f mean=%.5f stdev=%.5f raw_z=%.3f score=%.3f",
                event.timestamp,
                ticker,
                returns[-1],
                mean,
                stdev,
                raw_z,
                scores[ticker],
            )

        return SignalEvent(timestamp=event.timestamp, scores=scores)
