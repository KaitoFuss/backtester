import logging
from collections.abc import Sequence

from backtester.core.engine import ExecutionHandler
from backtester.core.events import FillEvent, OrderEvent

logger = logging.getLogger(__name__)

_BPS = 10_000.0


class CostAwareExecutionHandler:
    """Wraps another ``ExecutionHandler`` and charges trading costs on its fills.

    Composition rather than replacement: ``IdealExecutionHandler`` stays the
    frictionless base that decides *where* a fill happens, and this decides
    what it costs. Any future execution model gets costs for free.

    ``cost_bps`` is the **half-spread paid on a single fill**, always adverse
    (a BUY lifts the offer, a SELL hits the bid), so a round trip costs
    ``2 * cost_bps``. ``commission_bps`` is charged on the filled notional at
    the cost-adjusted price.

    The spread is folded into ``fill_price``, so equity, cash and realized PnL
    absorb it automatically through the normal fill path. ``FillEvent.slippage``
    records what was paid **for reporting only** and must never be subtracted
    again anywhere, or the cost is double-counted.
    """

    def __init__(
        self,
        inner: ExecutionHandler,
        cost_bps: float = 0.0,
        commission_bps: float = 0.0,
    ) -> None:
        self._inner = inner
        self._cost_bps = cost_bps
        self._commission_bps = commission_bps

    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]:
        return [self._charge(fill) for fill in self._inner.process_order(event)]

    def _charge(self, fill: FillEvent) -> FillEvent:
        half_spread = fill.fill_price * self._cost_bps / _BPS
        signed = half_spread if fill.direction == "BUY" else -half_spread
        price = fill.fill_price + signed
        quantity = abs(fill.quantity)
        commission = quantity * price * self._commission_bps / _BPS
        logger.debug(
            "%s  %s: cost-adjusted %.4f -> %.4f (spread=%.4f commission=%.4f)",
            fill.timestamp,
            fill.ticker,
            fill.fill_price,
            price,
            half_spread * quantity,
            commission,
        )
        return FillEvent(
            timestamp=fill.timestamp,
            ticker=fill.ticker,
            quantity=fill.quantity,
            direction=fill.direction,
            fill_price=price,
            commission=commission,
            slippage=half_spread * quantity,
        )
