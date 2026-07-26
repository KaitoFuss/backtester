import logging
from collections.abc import Sequence
from datetime import datetime

from backtester.core.engine import PortfolioView
from backtester.core.events import MarketEvent, OrderEvent, Ticker

logger = logging.getLogger(__name__)


class LeverageRiskManager:
    """Caps gross exposure at ``max_gross`` times equity (the leverage limit),
    taking precedence over the portfolio's own sizing.

    Orders that *reduce* exposure (closes, trims toward flat) always pass
    through untouched — risk never blocks de-risking. Orders that *increase*
    exposure are scaled down proportionally to fit whatever gross budget the
    mandatory (reducing) orders leave under the ceiling. If the held book alone
    has already drifted past the ceiling — mark-to-market can push gross over
    the limit with no new orders at all — it emits proportional trim orders to
    bring the book back to the limit.

    Equity and positions are read from the ``Portfolio`` via the read-only
    ``PortfolioView``; per-ticker prices come from the bar's closes. Tickers the
    bar does not price are left untouched (they cannot be valued or trimmed).
    """

    def __init__(self, portfolio: PortfolioView, max_gross: float) -> None:
        self._portfolio = portfolio
        self._max_gross = max_gross

    def reconcile(self, event: MarketEvent, orders: Sequence[OrderEvent]) -> Sequence[OrderEvent]:
        equity = self._portfolio.mark_to_market()
        if equity <= 0:
            logger.warning("Equity %.2f <= 0; skipping leverage cap this bar", equity)
            return orders
        ceiling = self._max_gross * equity

        prices = {ticker: bar.close for ticker, bar in event.bars.items()}
        reducing: list[OrderEvent] = []
        increasing: list[OrderEvent] = []
        for order in orders:
            if order.ticker not in prices:
                reducing.append(order)  # unpriceable: cannot reason, pass through
            elif self._is_reducing(order):
                reducing.append(order)
            else:
                increasing.append(order)

        # Positions after the mandatory (reducing) orders, and their gross.
        post_reducing = self._project(event, reducing, prices)
        mandatory_gross = sum(abs(qty * prices[t]) for t, qty in post_reducing.items())

        budget = ceiling - mandatory_gross
        if budget <= 0:
            trims = self._trim_to(ceiling, mandatory_gross, event.timestamp, post_reducing)
            return [*reducing, *trims]

        return [*reducing, *self._scale_increases(increasing, prices, budget)]

    def _is_reducing(self, order: OrderEvent) -> bool:
        position = self._portfolio.get_position(order.ticker)
        current = position.quantity if position is not None else 0
        signed = order.quantity if order.direction == "BUY" else -order.quantity
        # Moving toward (or through) flat: opposite sign to the current holding.
        return current != 0 and (signed > 0) != (current > 0)

    def _project(
        self, event: MarketEvent, orders: Sequence[OrderEvent], prices: dict[Ticker, float]
    ) -> dict[Ticker, int]:
        projected: dict[Ticker, int] = {}
        for ticker in prices:
            position = self._portfolio.get_position(ticker)
            if position is not None and position.quantity != 0:
                projected[ticker] = position.quantity
        for order in orders:
            signed = order.quantity if order.direction == "BUY" else -order.quantity
            projected[order.ticker] = projected.get(order.ticker, 0) + signed
        return {ticker: qty for ticker, qty in projected.items() if qty != 0}

    def _scale_increases(
        self, increasing: Sequence[OrderEvent], prices: dict[Ticker, float], budget: float
    ) -> list[OrderEvent]:
        requested = sum(order.quantity * prices[order.ticker] for order in increasing)
        if requested <= budget:
            return list(increasing)
        factor = budget / requested
        scaled: list[OrderEvent] = []
        for order in increasing:
            qty = round(order.quantity * factor)
            if qty > 0:
                scaled.append(_replace_qty(order, qty))
        return scaled

    def _trim_to(
        self,
        ceiling: float,
        mandatory_gross: float,
        timestamp: datetime,
        positions: dict[Ticker, int],
    ) -> list[OrderEvent]:
        if mandatory_gross <= ceiling:
            return []
        factor = ceiling / mandatory_gross
        trims: list[OrderEvent] = []
        for ticker, qty in positions.items():
            target = round(qty * factor)
            delta = target - qty  # opposite sign to qty: a partial close
            if delta == 0:
                continue
            logger.info("Leverage trim on %s: %d -> %d", ticker, qty, target)
            trims.append(
                OrderEvent(
                    timestamp=timestamp,
                    ticker=ticker,
                    quantity=abs(delta),
                    direction="BUY" if delta > 0 else "SELL",
                )
            )
        return trims


def _replace_qty(order: OrderEvent, quantity: int) -> OrderEvent:
    return OrderEvent(
        timestamp=order.timestamp,
        ticker=order.ticker,
        quantity=quantity,
        direction=order.direction,
    )
