from collections.abc import Sequence

from backtester.core.engine import RiskManager
from backtester.core.events import MarketEvent, OrderEvent


class ChainedRiskManager:
    """Runs several risk managers in order, threading each one's output into the
    next. The ``Engine`` holds a single ``RiskManager``; this composes many
    behind that slot. Order matters — put exit rules before the leverage cap so
    exposure-reducing exits are counted before what is left is capped."""

    def __init__(self, managers: Sequence[RiskManager]) -> None:
        self._managers = managers

    def reconcile(self, event: MarketEvent, orders: Sequence[OrderEvent]) -> Sequence[OrderEvent]:
        for manager in self._managers:
            orders = manager.reconcile(event, orders)
        return orders
