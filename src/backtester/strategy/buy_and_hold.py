from collections.abc import Sequence

from backtester.core.events import MarketEvent, SignalEvent


class BuyAndHoldStrategy:
    """Buys every ticker seen in the first bar at equal weight, then never
    signals again — used as a passive benchmark against active strategies."""

    def __init__(self) -> None:
        self._invested = False

    def process_market(self, event: MarketEvent) -> Sequence[SignalEvent]:
        if self._invested or not event.bars:
            return []
        self._invested = True
        scores = dict.fromkeys(event.bars, 1.0)
        return [SignalEvent(timestamp=event.timestamp, scores=scores)]
