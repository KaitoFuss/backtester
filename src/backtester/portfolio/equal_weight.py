import logging
from collections.abc import Sequence
from typing import Literal

from backtester.core.events import OrderEvent, SignalEvent
from backtester.core.trade_log import log_trade
from backtester.portfolio.base import BasePortfolio, existing_gross

logger = logging.getLogger(__name__)


class EqualWeightPortfolio(BasePortfolio):
    """Buys and holds: a ticker scored non-zero while flat takes an equal share
    of the gross budget still free under ``max_gross``, and is then never
    resized or closed.

    Deliberately the dumbest portfolio here — it exists so the buy-and-hold
    benchmark stays a genuine buy-and-hold reference rather than inheriting
    whatever the strategy portfolios happen to do. It has no thresholds and
    ignores score magnitude entirely; only the sign picks the direction.
    """

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        equity = self.mark_to_market()
        if equity <= 0:
            return []

        candidates: list[tuple[str, float, float]] = []
        for ticker, score in event.scores.items():
            price = self._price_source.get_price(ticker)
            position = self._positions.get(ticker)
            if score == 0.0 or price is None or (position and position.quantity != 0):
                continue
            candidates.append((ticker, score, price))
        if not candidates:
            return []

        available = max(
            0.0, self._max_gross - existing_gross(self._positions, self._price_source, equity)
        )
        weight = available / len(candidates)
        if weight == 0.0:
            return []

        orders: list[OrderEvent] = []
        for ticker, score, price in candidates:
            qty = round(weight * equity / price)
            if qty == 0:
                logger.debug(
                    "%s  %s: weight=%.5f rounds to 0 shares, skipping open",
                    event.timestamp,
                    ticker,
                    weight,
                )
                continue
            direction: Literal["BUY", "SELL"] = "BUY" if score > 0 else "SELL"
            log_trade(
                logger,
                event.timestamp,
                "OPEN",
                direction,
                ticker,
                qty,
                price,
                f"equal weight={weight:.5f}",
            )
            orders.append(
                OrderEvent(
                    timestamp=event.timestamp, ticker=ticker, quantity=qty, direction=direction
                )
            )
        return orders
