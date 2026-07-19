import logging
from collections.abc import Sequence

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, SignalEvent, Ticker

logger = logging.getLogger(__name__)


class WeightedPortfolio:
    """Sizes positions proportionally to signal scores, normalized by total
    absolute score so gross exposure never exceeds current equity.

    Positions move through discrete flat -> open -> flat cycles rather than
    resizing every bar: a flat ticker opens only once ``abs(score)`` reaches
    ``entry_threshold``, sized once from the current signal; an open position
    is held unchanged (no resizing) until it closes, which happens when the
    score's sign flips, drops below ``exit_threshold``, or is exactly 0.
    A ticker absent from a signal's ``scores`` is left untouched (hold).
    """

    def __init__(
        self,
        price_source: PriceSource,
        initial_cash: float = 100_000.0,
        entry_threshold: float = 0.0,
        exit_threshold: float = 0.0,
    ) -> None:
        self._price_source = price_source
        self._cash = initial_cash
        self._positions: dict[Ticker, int] = {}
        self._entry_threshold = entry_threshold
        self._exit_threshold = exit_threshold

    def mark_to_market(self) -> float:
        total = self._cash
        for ticker, qty in self._positions.items():
            price = self._price_source.get_price(ticker)
            if price is None:
                logger.warning(
                    "No price for held position %s (qty=%d); excluding from equity", ticker, qty
                )
                continue
            total += qty * price
        return total

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        total_abs_score = sum(abs(score) for score in event.scores.values())
        equity = self.mark_to_market()

        orders: list[OrderEvent] = []
        for ticker, score in event.scores.items():
            price = self._price_source.get_price(ticker)
            if price is None:
                continue

            # `or 1.0` keeps an all-zero signal at weight 0 instead of dividing 0/0
            weight = score / (total_abs_score or 1.0)
            current_qty = self._positions.get(ticker, 0)

            if current_qty == 0:
                if score == 0 or abs(score) < self._entry_threshold:
                    continue
                delta = round(weight * equity / price)
            else:
                held_sign = 1 if current_qty > 0 else -1
                score_sign = (score > 0) - (score < 0)
                should_close = (
                    score == 0 or score_sign != held_sign or abs(score) < self._exit_threshold
                )
                if not should_close:
                    continue
                delta = -current_qty

            if delta == 0:
                continue

            orders.append(
                OrderEvent(
                    timestamp=event.timestamp,
                    ticker=ticker,
                    quantity=abs(delta),
                    direction="BUY" if delta > 0 else "SELL",
                )
            )
        return orders

    def process_fill(self, event: FillEvent) -> Sequence[OrderEvent]:
        signed_qty = event.quantity if event.direction == "BUY" else -event.quantity
        self._cash -= signed_qty * event.fill_price + event.commission
        self._positions[event.ticker] = self._positions.get(event.ticker, 0) + signed_qty
        return []
