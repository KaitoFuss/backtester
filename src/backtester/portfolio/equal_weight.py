import logging
from collections.abc import Sequence
from dataclasses import replace

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, Position, SignalEvent, Ticker

logger = logging.getLogger(__name__)


class EqualWeightPortfolio:
    """Default, no-frills portfolio: opens positions in proportion to signal
    score (``score / total abs score``), normalized into the gross exposure
    still available under ``max_gross``. No vol estimate is required, so a
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
        total = self._cash
        for ticker, position in self._positions.items():
            price = self._price_source.get_price(ticker)
            if price is None:
                logger.warning(
                    "No price for held position %s (qty=%d); excluding from equity",
                    ticker,
                    position.quantity,
                )
                continue
            total += position.quantity * price
        return total

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        equity = self.mark_to_market()

        orders: list[OrderEvent] = []
        open_candidates: list[tuple[Ticker, float, float]] = []
        for ticker, score in event.scores.items():
            price = self._price_source.get_price(ticker)
            if price is None:
                continue

            position = self._positions.get(ticker)
            current_qty = position.quantity if position else 0
            if current_qty == 0:
                if score == 0 or abs(score) < self._entry_threshold:
                    continue
                open_candidates.append((ticker, score, price))
            else:
                held_sign = 1 if current_qty > 0 else -1
                score_sign = (score > 0) - (score < 0)
                should_close = (
                    score == 0 or score_sign != held_sign or abs(score) < self._exit_threshold
                )
                if should_close:
                    orders.append(
                        OrderEvent(
                            timestamp=event.timestamp,
                            ticker=ticker,
                            quantity=abs(current_qty),
                            direction="SELL" if current_qty > 0 else "BUY",
                        )
                    )

        orders.extend(self._size_opens(event, open_candidates, equity))
        return orders

    def _size_opens(
        self, event: SignalEvent, candidates: list[tuple[Ticker, float, float]], equity: float
    ) -> list[OrderEvent]:
        if not candidates or equity <= 0:
            return []

        total_abs_score = sum(abs(score) for _, score, _ in candidates)
        if total_abs_score == 0.0:
            return []

        # Held positions are never resized, so new opens may only use the gross
        # budget left free under the max_gross leverage cap.
        existing_gross = 0.0
        for ticker, position in self._positions.items():
            price = self._price_source.get_price(ticker)
            if price is not None:
                existing_gross += abs(position.quantity * price / equity)
        available = max(0.0, self._max_gross - existing_gross)
        if available == 0.0:
            return []

        orders: list[OrderEvent] = []
        for ticker, score, price in candidates:
            weight = score / total_abs_score * available
            qty = round(weight * equity / price)
            if qty == 0:
                continue
            orders.append(
                OrderEvent(
                    timestamp=event.timestamp,
                    ticker=ticker,
                    quantity=abs(qty),
                    direction="BUY" if qty > 0 else "SELL",
                )
            )
        return orders

    def process_fill(self, event: FillEvent) -> None:
        signed_delta = event.quantity if event.direction == "BUY" else -event.quantity
        self._cash -= signed_delta * event.fill_price + event.commission

        prior = self._positions.get(event.ticker)
        prior_qty = prior.quantity if prior is not None else 0
        new_qty = prior_qty + signed_delta

        if new_qty == 0:
            self._positions.pop(event.ticker, None)
        elif prior is None or (prior_qty > 0) != (new_qty > 0):
            # Opening a fresh position or flipping direction resets the cost basis.
            self._positions[event.ticker] = Position(
                ticker=event.ticker,
                quantity=new_qty,
                entry_price=event.fill_price,
                entry_date=event.timestamp,
            )
        else:
            # Adding to an existing position keeps its original entry price/date.
            self._positions[event.ticker] = replace(prior, quantity=new_qty)
