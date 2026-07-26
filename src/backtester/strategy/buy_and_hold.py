import logging

from backtester.core.events import MarketEvent, SignalEvent, Ticker

logger = logging.getLogger(__name__)


class BuyAndHoldStrategy:
    """Equal-weights every ticker seen so far, then holds — used as a
    passive benchmark against active strategies.

    Signals the full known universe whenever a new ticker shows up for the
    first time, so tickers that start trading mid-backtest still get bought
    instead of being silently excluded forever; on every other bar it emits
    an empty signal (holding all positions unchanged) so the risk manager
    still gets a reconcile pass each bar.
    """

    def __init__(self) -> None:
        self._known: set[Ticker] = set()

    def process_market(self, event: MarketEvent) -> SignalEvent:
        new_tickers = event.bars.keys() - self._known
        if not new_tickers:
            return SignalEvent(timestamp=event.timestamp, scores={})
        logger.info("%s: adding %s to held universe", event.timestamp, sorted(new_tickers))
        self._known |= new_tickers
        scores = dict.fromkeys(self._known, 1.0)
        return SignalEvent(timestamp=event.timestamp, scores=scores)
