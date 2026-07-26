import logging
from collections.abc import Sequence

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent

logger = logging.getLogger(__name__)


class IdealExecutionHandler:
    def __init__(self, price_source: PriceSource) -> None:
        self._price_source = price_source

    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]:
        price = self._price_source.get_price(event.ticker)
        if price is None:
            logger.error(
                "No price for order ticker %s (qty=%d); cannot fill", event.ticker, event.quantity
            )
            raise RuntimeError(
                f"no price available to fill order for {event.ticker!r}; "
                "the price source must have consumed a bar for this ticker before "
                "an order can reach execution"
            )
        logger.debug("Filled %s %d %s @ %.4f", event.direction, event.quantity, event.ticker, price)
        return [
            FillEvent(
                timestamp=event.timestamp,
                ticker=event.ticker,
                quantity=event.quantity,
                direction=event.direction,
                fill_price=price,
            )
        ]
