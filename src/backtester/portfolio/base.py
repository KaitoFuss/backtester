import logging
from collections.abc import Collection, Mapping
from dataclasses import replace

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, Position, Ticker

logger = logging.getLogger(__name__)


def existing_gross(
    positions: Mapping[Ticker, Position],
    price_source: PriceSource,
    equity: float,
    closing: Collection[Ticker] = (),
) -> float:
    """Gross exposure of a set of positions, as a fraction of equity. Shared
    across every portfolio, including a call sizing gross for a subset of its
    own positions (``ScoreProportionalPortfolio``, over just the ones held
    outside this bar's signal). ``closing`` excludes tickers with a close
    order already queued this bar — their ``Position`` is still present until
    the close's ``FillEvent`` settles, but the capital they'll free is
    available to size this bar's new opens against."""
    gross = 0.0
    for ticker, position in positions.items():
        if ticker in closing:
            continue
        price = price_source.get_price(ticker)
        if price is not None:
            gross += abs(position.quantity * price / equity)
    return gross


def _compute_equity(
    cash: float, positions: Mapping[Ticker, Position], price_source: PriceSource
) -> float:
    total = cash
    for ticker, position in positions.items():
        price = price_source.get_price(ticker)
        if price is None:
            logger.warning(
                "No price for held position %s (qty=%d); excluding from equity",
                ticker,
                position.quantity,
            )
            continue
        total += position.quantity * price
    return total


def _apply_fill(cash: float, positions: dict[Ticker, Position], event: FillEvent) -> float:
    signed_delta = event.quantity if event.direction == "BUY" else -event.quantity
    new_cash = cash - (signed_delta * event.fill_price + event.commission)

    prior = positions.get(event.ticker)
    prior_qty = prior.quantity if prior is not None else 0
    new_qty = prior_qty + signed_delta

    if new_qty == 0:
        positions.pop(event.ticker, None)
    elif prior is None or (prior_qty > 0) != (new_qty > 0):
        positions[event.ticker] = Position(
            ticker=event.ticker,
            quantity=new_qty,
            entry_price=event.fill_price,
            entry_date=event.timestamp,
        )
    elif abs(new_qty) > abs(prior_qty):
        # Adding to a position re-bases the cost basis onto the quantity-weighted
        # average, so anything reading entry_price off a resized position (the
        # risk manager's stop-loss and take-profit) measures from what the
        # position actually cost. entry_date stays at first entry so holding
        # period still means time since the position was established.
        added = abs(new_qty) - abs(prior_qty)
        avg_price = (prior.entry_price * abs(prior_qty) + event.fill_price * added) / abs(new_qty)
        positions[event.ticker] = replace(prior, quantity=new_qty, entry_price=avg_price)
    else:
        positions[event.ticker] = replace(prior, quantity=new_qty)
    return new_cash


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
        max_gross: float = 1.0,
    ) -> None:
        self._price_source = price_source
        self._cash = initial_cash
        self._positions: dict[Ticker, Position] = {}
        self._max_gross = max_gross

    def get_position(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)

    def mark_to_market(self) -> float:
        return _compute_equity(self._cash, self._positions, self._price_source)

    def process_fill(self, event: FillEvent) -> None:
        self._cash = _apply_fill(self._cash, self._positions, event)
