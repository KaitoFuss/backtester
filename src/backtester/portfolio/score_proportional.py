import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal

from backtester.core.engine import PriceSource
from backtester.core.events import OrderEvent, SignalEvent, Ticker
from backtester.core.trade_log import log_trade
from backtester.portfolio.base import BasePortfolio
from backtester.portfolio.utils import existing_gross

logger = logging.getLogger(__name__)


class ScoreProportionalPortfolio(BasePortfolio):
    """Conviction-weighted portfolio that rebuilds its whole target book every
    bar and trades the difference.

    Every scored ticker gets a target weight of ``score / total abs score``
    normalized into the available gross budget, and the order for that ticker
    is the *delta* between its target quantity and what is currently held. A
    position whose score strengthens is scaled up, one that weakens is scaled
    down, and one whose score flips sign crosses through zero in a single
    order. This is the difference from ``InverseVolPortfolio``, which sizes a
    position once at entry and then leaves it alone: here a weight always
    reflects today's conviction rather than the conviction on the bar the
    position happened to open.

    ``entry_threshold`` / ``exit_threshold`` gate on the raw score as a dead
    zone around zero: a flat ticker needs ``abs(score)`` to reach
    ``entry_threshold`` before it gets any weight, and a held one keeps a
    weight until ``abs(score)`` falls below ``exit_threshold``. Note this reads
    the bands differently from ``InverseVolPortfolio``, which closes on any
    reversal (``score * held_sign < exit_threshold``) because it cannot resize
    a position it already holds. Here a reversal is not weak conviction, it is
    strong conviction the other way, and the position simply crosses zero — so
    only magnitude decides whether a name is in the book at all. A ticker
    absent from ``scores`` is held untouched, and the gross it occupies is
    reserved before the rest of the budget is shared out.

    With ``dollar_neutral``, the surviving scores are demeaned before they are
    normalized, so the signed weights sum to zero and the book carries no net
    market exposure. Note this makes weights relative: a ticker with a positive
    score sitting *below* the cross-sectional mean is shorted, which is the
    point in a relative-value book and surprising anywhere else. When only one
    ticker survives the thresholds it demeans to exactly zero, so no position is
    taken.

    Turnover is deliberately uncontrolled — there is no drift band yet, so any
    change in score retrades. Until the execution layer models slippage and
    commission, that churn is free here and would not be in reality.
    """

    def __init__(
        self,
        price_source: PriceSource,
        initial_cash: float = 100_000.0,
        entry_threshold: float = 0.0,
        exit_threshold: float = 0.0,
        max_gross: float = 1.0,
        dollar_neutral: bool = False,
    ) -> None:
        super().__init__(
            price_source=price_source,
            initial_cash=initial_cash,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            max_gross=max_gross,
        )
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
        gated = {
            ticker: self._gated_score(ticker, score, event.timestamp)
            for ticker, score in event.scores.items()
            if self._price_source.get_price(ticker) is not None
        }
        # Demean only the names that survived the entry/exit band — folding the
        # gated-out zeros into the mean would hand them a weight the band just
        # decided they should not have.
        survivors = {ticker: score for ticker, score in gated.items() if score != 0.0}
        if self._dollar_neutral and survivors:
            mean = sum(survivors.values()) / len(survivors)
            survivors = {ticker: score - mean for ticker, score in survivors.items()}
            logger.debug("%s  demeaned scores by %.5f for neutrality", event.timestamp, mean)

        total_abs = sum(abs(score) for score in survivors.values())
        weights = dict.fromkeys(gated, 0.0)
        if total_abs > 0.0:
            weights.update(
                {ticker: score / total_abs * budget for ticker, score in survivors.items()}
            )
        return weights

    def _gated_score(self, ticker: Ticker, score: float, timestamp: datetime) -> float:
        """The score this ticker is allowed to carry weight on, or 0.0 if the
        entry/exit band says it should hold no position."""
        position = self._positions.get(ticker)
        current_qty = position.quantity if position else 0
        if current_qty == 0:
            if abs(score) < self._entry_threshold:
                logger.debug(
                    "%s  %s: score=%.3f below entry_threshold=%.3f, stays flat",
                    timestamp,
                    ticker,
                    score,
                    self._entry_threshold,
                )
                return 0.0
            return score

        if abs(score) < self._exit_threshold:
            logger.debug(
                "%s  %s: score=%.3f below exit_threshold=%.3f, targeting flat",
                timestamp,
                ticker,
                score,
                self._exit_threshold,
            )
            return 0.0
        return score

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
