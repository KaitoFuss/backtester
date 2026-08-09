import logging
import math
import statistics
from collections import deque
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal

from backtester.core.engine import PriceSource
from backtester.core.events import OrderEvent, Position, SignalEvent, Ticker
from backtester.core.trade_log import log_trade
from backtester.portfolio.base import BasePortfolio, existing_gross
from backtester.tracker.metrics import TRADING_DAYS_PER_YEAR

logger = logging.getLogger(__name__)


def _annualized_vol(returns: deque[float] | None, window: int) -> float | None:
    """Annualized stdev of a trailing return window, or ``None`` until the
    window is full or when the sample has no dispersion."""
    if returns is None or len(returns) < window:
        return None
    stdev = statistics.stdev(returns)
    if stdev == 0:
        return None
    return stdev * math.sqrt(TRADING_DAYS_PER_YEAR)


def _sign(score: float) -> float:
    """True mathematical sign, unlike ``math.copysign`` which always returns
    +-1.0 and would otherwise force a direction onto an exact 0.0 (a real
    reading, not a placeholder) based on nothing but its float sign bit."""
    if score > 0:
        return 1.0
    if score < 0:
        return -1.0
    return 0.0


def _partition_signal(
    scores: Mapping[Ticker, float],
    positions: Mapping[Ticker, Position],
    price_source: PriceSource,
    entry_threshold: float,
    exit_threshold: float,
    timestamp: datetime,
) -> tuple[list[OrderEvent], list[tuple[Ticker, float, float]]]:
    """Split a signal's scores into close orders for positions that no longer
    qualify, and open candidates (ticker, score, price) for flat tickers whose
    score just crossed ``entry_threshold``.

    A held position closes when its score, signed into the held direction
    (``score * held_sign``), falls below ``exit_threshold``. This single test
    covers both an opposite-signed score (signed score goes negative, below any
    ``exit_threshold >= 0``, so a reversal always closes) and conviction that
    has merely decayed in the held direction."""
    close_orders: list[OrderEvent] = []
    open_candidates: list[tuple[Ticker, float, float]] = []
    for ticker, score in scores.items():
        price = price_source.get_price(ticker)
        if price is None:
            continue

        position = positions.get(ticker)
        current_qty = position.quantity if position else 0
        if current_qty == 0:
            if abs(score) < entry_threshold:
                logger.debug(
                    "%s  %s: score=%.3f below entry_threshold=%.3f, no open",
                    timestamp,
                    ticker,
                    score,
                    entry_threshold,
                )
                continue
            open_candidates.append((ticker, score, price))
        else:
            held_sign = 1 if current_qty > 0 else -1
            signed_score = score * held_sign
            if signed_score < exit_threshold:
                reason = (
                    f"signed score={signed_score:.3f} below exit_threshold={exit_threshold:.3f}"
                )
            else:
                reason = None
            if reason is not None:
                direction: Literal["BUY", "SELL"] = "SELL" if current_qty > 0 else "BUY"
                log_trade(
                    logger, timestamp, "CLOSE", direction, ticker, abs(current_qty), price, reason
                )
                close_orders.append(
                    OrderEvent(
                        timestamp=timestamp,
                        ticker=ticker,
                        quantity=abs(current_qty),
                        direction=direction,
                    )
                )
    return close_orders, open_candidates


class InverseVolPortfolio(BasePortfolio):
    """Band-trading portfolio that sizes purely by risk: a name's weight is
    ``sign(score) / sigma`` (its trailing annualized return vol), normalized so
    the batch of new opens exactly fills the gross exposure still available
    under ``max_gross``.

    The score is a gate and a direction, never a size — a score of 0.6 and a
    score of 3.0 open the same position. Conviction-weighting lives in
    ``ScoreProportionalPortfolio``; this portfolio's job is to let the
    lower-vol name hold more shares so each name contributes comparable risk.

    A candidate without a full ``vol_window`` of returns yet is skipped for the
    bar (no fallback) rather than guessed at.

    Position lifecycle is flat -> open -> flat: a flat ticker opens once
    ``abs(score)`` reaches ``entry_threshold``, sized once from that bar's
    signal; an open position is held unchanged until ``score * held_sign``
    falls below ``exit_threshold``; a ticker absent from a signal's ``scores``
    is left untouched.

    Known limitation of band trading: because held positions are never resized,
    the batch normalization applies only to *new* opens while held names keep
    the size they were opened at. Comparable risk per name therefore holds
    within a batch, not across the whole book.
    """

    def __init__(
        self,
        price_source: PriceSource,
        initial_cash: float = 100_000.0,
        entry_threshold: float = 0.0,
        exit_threshold: float = 0.0,
        vol_window: int = 20,
        max_gross: float = 1.0,
    ) -> None:
        super().__init__(price_source=price_source, initial_cash=initial_cash, max_gross=max_gross)
        self._entry_threshold = entry_threshold
        self._exit_threshold = exit_threshold
        self._vol_window = vol_window
        self._returns: dict[Ticker, deque[float]] = {}
        self._last_price: dict[Ticker, float] = {}

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        # Update returns for tickers in this signal AND ones we currently hold,
        # so held names keep a live vol estimate on bars where they're absent
        # from `scores` (the `| set(...)` unions both ticker sets).
        self._record_returns_for_vol(set(event.scores) | set(self._positions), event.timestamp)
        equity = self.mark_to_market()

        close_orders, open_candidates = _partition_signal(
            event.scores,
            self._positions,
            self._price_source,
            self._entry_threshold,
            self._exit_threshold,
            event.timestamp,
        )
        closing = {order.ticker for order in close_orders}
        return [*close_orders, *self._size_opens(event, open_candidates, equity, closing)]

    def _size_opens(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        equity: float,
        closing: set[Ticker],
    ) -> list[OrderEvent]:
        if not candidates or equity <= 0:
            return []

        # Held positions are never resized, so new opens may only use the gross
        # budget left free under the max_gross leverage cap. Tickers closing
        # this same bar are excluded — their fill hasn't settled yet, but the
        # capital they're about to free is available to size these opens.
        available = max(
            0.0,
            self._max_gross - existing_gross(self._positions, self._price_source, equity, closing),
        )
        if available == 0.0:
            return []

        weights = self._target_weights(event, candidates, available)
        if not weights:
            return []

        orders: list[OrderEvent] = []
        for ticker, score, price in candidates:
            if ticker not in weights:
                logger.debug("%s  %s: no weight assigned, skipping open", event.timestamp, ticker)
                continue
            qty = round(weights[ticker] * equity / price)
            if qty == 0:
                logger.debug(
                    "%s  %s: weight=%.5f rounds to 0 shares, skipping open",
                    event.timestamp,
                    ticker,
                    weights[ticker],
                )
                continue
            direction: Literal["BUY", "SELL"] = "BUY" if qty > 0 else "SELL"
            reason = f"score={score:.3f} weight={weights[ticker]:.5f}"
            log_trade(logger, event.timestamp, "OPEN", direction, ticker, abs(qty), price, reason)
            orders.append(
                OrderEvent(
                    timestamp=event.timestamp,
                    ticker=ticker,
                    quantity=abs(qty),
                    direction=direction,
                )
            )
        return orders

    def _record_returns_for_vol(self, tickers: set[Ticker], timestamp: datetime) -> None:
        """Append each ticker's latest log return to its trailing window, giving
        ``_annualized_vol`` the history it works from. ``Bar`` guarantees prices
        are positive, so the only bar skipped is a ticker's first observation
        (no prior price to diff against)."""
        for ticker in tickers:
            price = self._price_source.get_price(ticker)
            if price is None:
                continue
            prev = self._last_price.get(ticker)
            self._last_price[ticker] = price
            if prev is not None:
                returns = self._returns.setdefault(ticker, deque(maxlen=self._vol_window))
                returns.append(math.log(price / prev))
                logger.debug(
                    "%s  %s: return=%.5f window=%d/%d",
                    timestamp,
                    ticker,
                    returns[-1],
                    len(returns),
                    self._vol_window,
                )

    def _target_weights(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        available: float,
    ) -> Mapping[Ticker, float]:
        raw: dict[Ticker, float] = {}
        for ticker, score, _ in candidates:
            vol = _annualized_vol(self._returns.get(ticker), self._vol_window)
            if vol is None:
                logger.debug(
                    "%s  %s: vol not ready (%d/%d returns), skipping open",
                    event.timestamp,
                    ticker,
                    len(self._returns.get(ticker, [])),
                    self._vol_window,
                )
                continue
            logger.debug("%s  %s: annualized_vol=%.4f", event.timestamp, ticker, vol)
            raw[ticker] = _sign(score) / vol

        total_abs_raw = sum(abs(r) for r in raw.values())
        if total_abs_raw == 0.0:
            return {}

        # Inverse-vol weights are only meaningful relative to each other, so the
        # batch is always normalized onto the available budget rather than
        # capped at it.
        scale = available / total_abs_raw
        if available < self._max_gross:
            logger.info(
                "%s  Gross budget reduced to %.4f (max_gross=%.4f) by existing positions",
                event.timestamp,
                available,
                self._max_gross,
            )
        return {ticker: r * scale for ticker, r in raw.items()}
