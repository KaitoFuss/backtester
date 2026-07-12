from collections.abc import Sequence

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent


class IdealExecutionHandler:
    def __init__(self, prices: PriceSource) -> None:
        self._prices = prices

    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]:
        price = self._prices.get_price(event.ticker)
        if price is None:
            return []
        return [
            FillEvent(
                timestamp=event.timestamp,
                ticker=event.ticker,
                quantity=event.quantity,
                direction=event.direction,
                fill_price=price,
            )
        ]
