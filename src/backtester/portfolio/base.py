import logging

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, Position, Ticker
from backtester.portfolio.utils import apply_fill, compute_equity

logger = logging.getLogger(__name__)


class BasePortfolio:
    """Book-keeping shared by every portfolio here: the cash balance, the open
    positions, and the read-only ``PortfolioView`` those imply.

    Subclasses own ``process_signal`` outright — the concrete portfolios differ
    not just in how they compute a weight but in what an order *means*
    (a one-shot open under band trading, a delta toward a target weight under
    rebalancing), so there is no useful shared order-generation template.

    ``max_gross`` is the leverage cap throughout: gross exposure as a multiple
    of equity (``1.0`` = fully invested, ``2.0`` = up to 2x long/short). Cash is
    tracked as an accounting balance, not a sizing constraint — the leverage cap
    is.
    """

    def __init__(
        self,
        price_source: PriceSource,
        initial_cash: float = 100_000.0,
        entry_threshold: float = 0.0,
        exit_threshold: float = 0.0,
        max_gross: float = 1.0,
    ) -> None:
        self._price_source = price_source
        self._cash = initial_cash
        self._positions: dict[Ticker, Position] = {}
        self._entry_threshold = entry_threshold
        self._exit_threshold = exit_threshold
        self._max_gross = max_gross

    def get_position(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)

    def mark_to_market(self) -> float:
        return compute_equity(self._cash, self._positions, self._price_source)

    def process_fill(self, event: FillEvent) -> None:
        self._cash = apply_fill(self._cash, self._positions, event)
