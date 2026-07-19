from collections.abc import Sequence

from backtester.core.events import MarketEvent, SignalEvent, Ticker


class BuyAndHoldStrategy:
    """Equal-weights every ticker seen so far, then holds — used as a
    passive benchmark against active strategies.

    Re-signals the full known universe (forcing WeightedPortfolio to
    rebalance back to equal weight) whenever a new ticker shows up for the
    first time, so tickers that start trading mid-backtest still get
    bought instead of being silently excluded forever.
    """

    def __init__(self) -> None:
        self._known: set[Ticker] = set()

    def process_market(self, event: MarketEvent) -> Sequence[SignalEvent]:
        new_tickers = event.bars.keys() - self._known
        if not new_tickers:
            return []
        self._known |= new_tickers
        scores = dict.fromkeys(self._known, 1.0)
        return [SignalEvent(timestamp=event.timestamp, scores=scores)]
