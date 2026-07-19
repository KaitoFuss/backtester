import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from backtester.core.events import FillEvent, MarketEvent, OrderEvent, Ticker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PositionEntry:
    entry_price: float
    entry_date: datetime
    signed_qty: int


class PositionExitRiskManager:
    """Flattens a position when its stop-loss, take-profit, or max-holding-days
    threshold is breached. Tracks entry price/date/quantity per ticker purely
    from observed fills — no dependency on Portfolio or PriceSource.

    Each threshold is disabled by passing ``None``. When multiple thresholds
    are configured and more than one is breached on the same bar, stop-loss is
    checked first, then take-profit, then max-holding-days.

    Position tracking is intentionally independent of ``Portfolio`` — this
    class only implements the structural ``RiskManager`` protocol, which has
    no dependency on any concrete portfolio implementation, and a portfolio
    isn't guaranteed to expose entry price/date at all.
    """

    def __init__(
        self,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        max_holding_days: int | None = None,
    ) -> None:
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct
        self._max_holding_days = max_holding_days
        self._entries: dict[Ticker, _PositionEntry] = {}

    def on_fill(self, event: FillEvent) -> None:
        signed_delta = event.quantity if event.direction == "BUY" else -event.quantity
        prior = self._entries.get(event.ticker)
        prior_qty = prior.signed_qty if prior is not None else 0
        new_qty = prior_qty + signed_delta

        if new_qty == 0:
            self._entries.pop(event.ticker, None)
        elif prior is None or (prior_qty > 0) != (new_qty > 0):
            self._entries[event.ticker] = _PositionEntry(
                entry_price=event.fill_price, entry_date=event.timestamp, signed_qty=new_qty
            )
        else:
            self._entries[event.ticker] = replace(prior, signed_qty=new_qty)

    def on_market(self, event: MarketEvent) -> Sequence[OrderEvent]:
        orders: list[OrderEvent] = []
        for ticker, entry in list(self._entries.items()):
            bar = event.bars.get(ticker)
            if bar is None:
                continue

            direction_sign = 1 if entry.signed_qty > 0 else -1
            pnl_pct = (bar.close - entry.entry_price) / entry.entry_price * direction_sign
            holding = event.timestamp - entry.entry_date

            if self._stop_loss_pct is not None and pnl_pct <= -self._stop_loss_pct:
                reason = "stop_loss"
            elif self._take_profit_pct is not None and pnl_pct >= self._take_profit_pct:
                reason = "take_profit"
            elif self._max_holding_days is not None and holding >= timedelta(
                days=self._max_holding_days
            ):
                reason = "max_holding_days"
            else:
                continue

            logger.info("Risk exit for %s: %s (pnl_pct=%.4f)", ticker, reason, pnl_pct)
            orders.append(
                OrderEvent(
                    timestamp=event.timestamp,
                    ticker=ticker,
                    quantity=abs(entry.signed_qty),
                    direction="SELL" if entry.signed_qty > 0 else "BUY",
                )
            )
        return orders
