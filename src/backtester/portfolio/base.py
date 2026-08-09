import logging
from collections.abc import Mapping, Sequence

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, Position, SignalEvent, Ticker
from backtester.portfolio.utils import (
    apply_fill,
    compute_equity,
    existing_gross,
    partition_signal,
    size_to_orders,
)

logger = logging.getLogger(__name__)


class BasePortfolio:
    """Shared machinery for the concrete portfolios.

    Every portfolio here moves positions through the same discrete
    flat -> open -> flat cycle: a flat ticker opens only once ``abs(score)``
    reaches ``entry_threshold``, sized once from that bar's signal; an open
    position is held unchanged until a sign flip, a sub-``exit_threshold``
    score, or a zero score closes it; a ticker absent from a signal's
    ``scores`` is left untouched (hold). Because held positions are never
    resized, new opens may only claim the gross budget those positions leave
    free under ``max_gross`` (the leverage cap, gross exposure as a multiple
    of equity: ``1.0`` = fully invested, ``2.0`` = up to 2x long/short).

    Subclasses differ only in how they turn open candidates into weights, via
    ``_target_weights``; ``_prepare`` is an optional per-bar hook (e.g. to
    update a trailing vol estimate) that runs before sizing.
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

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        self._prepare(event)
        equity = self.mark_to_market()

        close_orders, open_candidates = partition_signal(
            event.scores,
            self._positions,
            self._price_source,
            self._entry_threshold,
            self._exit_threshold,
            event.timestamp,
        )
        closing = {order.ticker for order in close_orders}
        return [*close_orders, *self._size_opens(event, open_candidates, equity, closing)]

    def process_fill(self, event: FillEvent) -> None:
        self._cash = apply_fill(self._cash, self._positions, event)

    def _size_opens(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        equity: float,
        closing: set[Ticker],
    ) -> list[OrderEvent]:
        if not candidates or equity <= 0:
            return []

        # Held positions are never resized, so new opens may only use the gross
        # budget left free under the max_gross leverage cap. Tickers closing
        # this same bar are excluded — their fill hasn't settled yet, but the
        # capital they're about to free is available to size these opens.
        available = max(
            0.0,
            self._max_gross - existing_gross(self._positions, self._price_source, equity, closing),
        )
        if available == 0.0:
            return []

        weights = self._target_weights(event, candidates, available)
        if not weights:
            return []
        return size_to_orders(weights, candidates, equity, event.timestamp)

    def _prepare(self, event: SignalEvent) -> None:
        """Per-bar hook run before sizing. Default is a no-op; subclasses that
        maintain per-ticker state (e.g. a trailing vol window) override it."""

    def _target_weights(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        available: float,
    ) -> Mapping[Ticker, float]:
        """Map open candidates to per-ticker weight-of-equity fractions that
        fit within ``available`` gross budget. A candidate omitted from the
        result is skipped this bar."""
        raise NotImplementedError
