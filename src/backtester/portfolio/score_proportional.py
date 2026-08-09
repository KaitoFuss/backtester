import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal

from backtester.core.engine import PriceSource
from backtester.core.events import OrderEvent, SignalEvent, Ticker
from backtester.core.trade_log import log_trade
from backtester.portfolio.base import BasePortfolio, existing_gross

logger = logging.getLogger(__name__)


class ScoreProportionalPortfolio(BasePortfolio):
    """Conviction-weighted portfolio that rebuilds its whole target book every
    bar and trades the difference.

    Every scored ticker gets a target weight of ``score / total abs score``
    normalized into the available gross budget — the raw score, with no
    entry/exit gate: any nonzero score carries some weight, however small. The
    order for that ticker is the *delta* between its target quantity and what
    is currently held. A position whose score strengthens is scaled up, one
    that weakens is scaled down, and one whose score flips sign crosses
    through zero in a single order, since a reversal here is not an exit, it
    is conviction the other way. This is the difference from
    ``InverseVolPortfolio``, which sizes a position once at entry via an
    explicit threshold band and then leaves it alone: here a weight always
    reflects today's raw conviction rather than the conviction on the bar the
    position happened to open. A ticker absent from ``scores`` is held
    untouched, and the gross it occupies is reserved before the rest of the
    budget is shared out.

    With ``dollar_neutral``, every scored ticker's score (including an exact
    ``0.0``, a real reading, not a placeholder for "no opinion") is demeaned
    before normalizing, so the signed weights sum to zero and the book
    carries no net market exposure. This makes weights relative: a ticker
    sitting *below* the cross-sectional mean is shorted regardless of its own
    sign, which is the point in a relative-value book and surprising
    anywhere else. When only one ticker is scored it demeans to exactly zero
    against itself, so no position is taken.

    Turnover is deliberately uncontrolled — there is no drift band yet, so any
    change in score retrades. Until the execution layer models slippage and
    commission, that churn is free here and would not be in reality.
    """

    def __init__(
        self,
        price_source: PriceSource,
        initial_cash: float = 100_000.0,
        max_gross: float = 1.0,
        dollar_neutral: bool = False,
    ) -> None:
        super().__init__(price_source=price_source, initial_cash=initial_cash, max_gross=max_gross)
        self._dollar_neutral = dollar_neutral

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        equity = self.mark_to_market()
        if equity <= 0:
            return []

        held_elsewhere = set(self._positions) - set(event.scores)
        reserved = existing_gross(
            {t: self._positions[t] for t in held_elsewhere}, self._price_source, equity
        )
        budget = max(0.0, self._max_gross - reserved)
        if reserved > 0:
            logger.info(
                "%s  Gross budget reduced to %.4f (max_gross=%.4f) by unscored held positions",
                event.timestamp,
                budget,
                self._max_gross,
            )

        weights = self._target_weights(event, budget)
        return self._orders_from_targets(weights, equity, event.timestamp)

    def _target_weights(self, event: SignalEvent, budget: float) -> Mapping[Ticker, float]:
        scored = {
            ticker: score
            for ticker, score in event.scores.items()
            if self._price_source.get_price(ticker) is not None
        }
        if self._dollar_neutral and scored:
            mean = sum(scored.values()) / len(scored)
            scored = {ticker: score - mean for ticker, score in scored.items()}
            logger.debug("%s  demeaned scores by %.5f for neutrality", event.timestamp, mean)

        total_abs = sum(abs(score) for score in scored.values())
        weights = dict.fromkeys(scored, 0.0)
        if total_abs > 0.0:
            weights.update({ticker: score / total_abs * budget for ticker, score in scored.items()})
        return weights

    def _orders_from_targets(
        self, weights: Mapping[Ticker, float], equity: float, timestamp: datetime
    ) -> list[OrderEvent]:
        """Trade each ticker's target weight minus what it already holds. The
        single place a target becomes an order, so a drift band (only retrade
        once the gap exceeds some threshold) would slot in here."""
        orders: list[OrderEvent] = []
        for ticker, weight in weights.items():
            price = self._price_source.get_price(ticker)
            if price is None:
                continue
            position = self._positions.get(ticker)
            current_qty = position.quantity if position else 0
            delta = round(weight * equity / price) - current_qty
            if delta == 0:
                continue

            direction: Literal["BUY", "SELL"] = "BUY" if delta > 0 else "SELL"
            log_trade(
                logger,
                timestamp,
                _action(current_qty, current_qty + delta),
                direction,
                ticker,
                abs(delta),
                price,
                f"weight={weight:.5f} qty {current_qty} -> {current_qty + delta}",
            )
            orders.append(
                OrderEvent(
                    timestamp=timestamp,
                    ticker=ticker,
                    quantity=abs(delta),
                    direction=direction,
                )
            )
        return orders


def _action(current_qty: int, target_qty: int) -> str:
    if current_qty == 0:
        return "OPEN"
    if target_qty == 0:
        return "CLOSE"
    return "REBALANCE"
