import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from backtester.core.engine import PortfolioView
from backtester.core.events import MarketEvent, OrderEvent, Position

logger = logging.getLogger(__name__)


class PositionExitRiskManager:
    """Flattens a position when its stop-loss, take-profit, or max-holding-days
    threshold is breached, taking precedence over the strategy: on each bar it
    reconciles the strategy's order batch, dropping any order on a ticker it is
    exiting and appending its own exit orders.

    Position state (entry price/date/quantity) is pulled from the ``Portfolio``
    via the read-only ``PortfolioView`` protocol rather than reconstructed from
    the fill stream — the portfolio already owns positions, so it owns their
    cost basis.

    Each threshold is disabled by passing ``None``. When multiple thresholds
    are configured and more than one is breached on the same bar, stop-loss is
    checked first, then take-profit, then max-holding-days.
    """

    def __init__(
        self,
        portfolio: PortfolioView,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        max_holding_days: int | None = None,
    ) -> None:
        self._portfolio = portfolio
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct
        self._max_holding_days = max_holding_days

    def reconcile(self, event: MarketEvent, orders: Sequence[OrderEvent]) -> Sequence[OrderEvent]:
        exits: list[OrderEvent] = []
        exit_tickers: set[str] = set()
        for ticker, bar in event.bars.items():
            position = self._portfolio.get_position(ticker)
            if position is None or position.quantity == 0:
                continue

            reason = self._breach_reason(position, bar.close, event.timestamp)
            if reason is None:
                logger.debug("%s: no risk breach (close=%.4f)", ticker, bar.close)
                continue

            logger.info("Risk exit for %s: %s (close=%.4f)", ticker, reason, bar.close)
            exit_tickers.add(ticker)
            exits.append(
                OrderEvent(
                    timestamp=event.timestamp,
                    ticker=ticker,
                    quantity=abs(position.quantity),
                    direction="SELL" if position.quantity > 0 else "BUY",
                )
            )

        passthrough = [order for order in orders if order.ticker not in exit_tickers]
        return [*exits, *passthrough]

    def _breach_reason(self, position: Position, close: float, timestamp: datetime) -> str | None:
        direction_sign = 1 if position.quantity > 0 else -1
        pnl_pct = (close - position.entry_price) / position.entry_price * direction_sign

        if self._stop_loss_pct is not None and pnl_pct <= -self._stop_loss_pct:
            return "stop_loss"
        if self._take_profit_pct is not None and pnl_pct >= self._take_profit_pct:
            return "take_profit"
        if self._max_holding_days is not None:
            holding = timestamp - position.entry_date
            if holding >= timedelta(days=self._max_holding_days):
                return "max_holding_days"
        return None
