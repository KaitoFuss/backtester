from collections.abc import Sequence

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, Position, SignalEvent, Ticker
from backtester.portfolio.utils import (
    apply_fill,
    compute_equity,
    existing_gross,
    partition_signal,
    size_to_orders,
)


class ScoreProportionalPortfolio:
    """Default, no-frills portfolio: opens positions in proportion to signal
    score (``score / total abs score``), normalized into the gross exposure
    still available under ``max_gross``. Only equal-weights when every open
    candidate's score has the same magnitude (e.g. ``BuyAndHoldStrategy``,
    which always signals ``1.0``); otherwise larger-magnitude scores get
    proportionally larger positions. No vol estimate is required, so a
    position opens on the same bar its score first qualifies — this is the
    reference portfolio for strategies like ``BuyAndHoldStrategy`` that need to
    invest immediately rather than wait out a vol warm-up window.

    Positions move through the same flat -> open -> flat cycle as
    ``VolWeightedPortfolio``: a flat ticker opens only once ``abs(score)``
    reaches ``entry_threshold``; an open position is held unchanged until a
    sign flip, a sub-``exit_threshold`` score, or a zero score closes it. A
    ticker absent from a signal's ``scores`` is left untouched (hold).
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

    def _size_opens(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        equity: float,
        closing: set[Ticker],
    ) -> list[OrderEvent]:
        if not candidates or equity <= 0:
            return []

        total_abs_score = sum(abs(score) for _, score, _ in candidates)
        if total_abs_score == 0.0:
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

        weights = {ticker: score / total_abs_score * available for ticker, score, _ in candidates}
        return size_to_orders(weights, candidates, equity, event.timestamp)

    def process_fill(self, event: FillEvent) -> None:
        self._cash = apply_fill(self._cash, self._positions, event)
