import logging
import math
import statistics
from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, Position, SignalEvent, Ticker

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


class WeightedPortfolio:
    """Opens positions with inverse-volatility weights, scaled so the projected
    portfolio volatility does not exceed ``target_vol``.

    Positions move through discrete flat -> open -> flat cycles rather than
    resizing every bar: a flat ticker opens only once ``abs(score)`` reaches
    ``entry_threshold``, sized once from the current signal; an open position
    is held unchanged (no resizing) until it closes, which happens when the
    score's sign flips, drops below ``exit_threshold``, or is exactly 0.
    A ticker absent from a signal's ``scores`` is left untouched (hold).

    Sizing at open (two layers):

    * **Inverse-vol weights** — a ticker's raw weight is ``score / sigma`` (its
      trailing annualized return vol), so names contribute comparable risk
      rather than comparable dollars. Weights are normalized to the gross still
      available under the ``max_gross`` cap (held positions are never resized).
    * **Vol targeting** — the new positions are scaled by ``g <= 1`` so the
      projected annualized book vol equals ``target_vol``, treating names as
      uncorrelated (diagonal covariance). ``g`` only scales *down*, so
      ``target_vol`` is a ceiling: the book runs below it in calm regimes and
      is never levered past ``max_gross``.

    Until a ticker has ``vol_window`` observed returns its vol is unknown; on
    any bar where a position being opened (or already held) lacks a vol
    estimate, that bar falls back to score-proportional sizing.
    """

    def __init__(
        self,
        price_source: PriceSource,
        initial_cash: float = 100_000.0,
        entry_threshold: float = 0.0,
        exit_threshold: float = 0.0,
        target_vol: float = 0.10,
        vol_window: int = 20,
        max_gross: float = 1.0,
    ) -> None:
        self._price_source = price_source
        self._cash = initial_cash
        self._positions: dict[Ticker, Position] = {}
        self._entry_threshold = entry_threshold
        self._exit_threshold = exit_threshold
        self._target_vol = target_vol
        self._vol_window = vol_window
        self._max_gross = max_gross
        self._returns: dict[Ticker, deque[float]] = {}
        self._last_price: dict[Ticker, float] = {}

    def get_position(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)

    def mark_to_market(self) -> float:
        total = self._cash
        for ticker, position in self._positions.items():
            price = self._price_source.get_price(ticker)
            if price is None:
                logger.warning(
                    "No price for held position %s (qty=%d); excluding from equity",
                    ticker,
                    position.quantity,
                )
                continue
            total += position.quantity * price
        return total

    def _update_vol_state(self, tickers: set[Ticker]) -> None:
        """Append this bar's log return for each ticker, so ``_annualized_vol``
        has a trailing window to work from."""
        for ticker in tickers:
            price = self._price_source.get_price(ticker)
            if price is None or price <= 0:
                continue
            prev = self._last_price.get(ticker)
            self._last_price[ticker] = price
            if prev is not None and prev > 0:
                returns = self._returns.setdefault(ticker, deque(maxlen=self._vol_window))
                returns.append(math.log(price / prev))

    def _annualized_vol(self, ticker: Ticker) -> float | None:
        returns = self._returns.get(ticker)
        if returns is None or len(returns) < self._vol_window:
            return None
        stdev = statistics.stdev(returns)
        if stdev == 0:
            return None
        return stdev * math.sqrt(TRADING_DAYS_PER_YEAR)

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        self._update_vol_state(set(event.scores) | set(self._positions))
        equity = self.mark_to_market()

        orders: list[OrderEvent] = []
        open_candidates: list[tuple[Ticker, float, float]] = []
        for ticker, score in event.scores.items():
            price = self._price_source.get_price(ticker)
            if price is None:
                continue

            position = self._positions.get(ticker)
            current_qty = position.quantity if position else 0
            if current_qty == 0:
                if score == 0 or abs(score) < self._entry_threshold:
                    continue
                open_candidates.append((ticker, score, price))
            else:
                held_sign = 1 if current_qty > 0 else -1
                score_sign = (score > 0) - (score < 0)
                should_close = (
                    score == 0 or score_sign != held_sign or abs(score) < self._exit_threshold
                )
                if should_close:
                    orders.append(_order(event.timestamp, ticker, -current_qty))

        orders.extend(self._size_opens(event, open_candidates, equity))
        return orders

    def _size_opens(
        self, event: SignalEvent, candidates: list[tuple[Ticker, float, float]], equity: float
    ) -> list[OrderEvent]:
        if not candidates or equity <= 0:
            return []

        candidate_vols = {ticker: self._annualized_vol(ticker) for ticker, _, _ in candidates}
        held_vols = {ticker: self._annualized_vol(ticker) for ticker in self._positions}
        vols_ready = all(v is not None for v in candidate_vols.values()) and all(
            v is not None for v in held_vols.values()
        )
        if vols_ready:
            cvols = {ticker: v for ticker, v in candidate_vols.items() if v is not None}
            hvols = {ticker: v for ticker, v in held_vols.items() if v is not None}
            return self._size_vol_targeted(event, candidates, cvols, hvols, equity)

        total_abs_score = sum(abs(score) for score in event.scores.values())
        return self._size_score_proportional(event, candidates, equity, total_abs_score)

    def _size_score_proportional(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        equity: float,
        total_abs_score: float,
    ) -> list[OrderEvent]:
        orders: list[OrderEvent] = []
        for ticker, score, price in candidates:
            # `or 1.0` keeps an all-zero signal at weight 0 instead of dividing 0/0
            weight = score / (total_abs_score or 1.0)
            orders.append(_order(event.timestamp, ticker, round(weight * equity / price)))
        return [order for order in orders if order.quantity > 0]

    def _size_vol_targeted(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        candidate_vols: dict[Ticker, float],
        held_vols: dict[Ticker, float],
        equity: float,
    ) -> list[OrderEvent]:
        existing_gross = 0.0
        held_var = 0.0
        for ticker, sigma in held_vols.items():
            price = self._price_source.get_price(ticker)
            if price is None:
                continue
            weight = self._positions[ticker].quantity * price / equity
            existing_gross += abs(weight)
            held_var += (weight * sigma) ** 2

        available = max(0.0, self._max_gross - existing_gross)
        raw = {ticker: score / candidate_vols[ticker] for ticker, score, _ in candidates}
        total_abs_raw = sum(abs(r) for r in raw.values())
        if available == 0.0 or total_abs_raw == 0.0:
            return []

        # Normalize inverse-vol weights into the still-available gross budget.
        weights = {ticker: r / total_abs_raw * available for ticker, r in raw.items()}

        # Scale g so the diagonal projected book vol hits target_vol, capped at 1
        # (target is a ceiling, never a reason to lever new orders up).
        new_var_unit = sum((weights[ticker] * candidate_vols[ticker]) ** 2 for ticker in weights)
        if new_var_unit <= 0.0:
            return []
        g_sq = (self._target_vol**2 - held_var) / new_var_unit
        if g_sq <= 0.0:
            return []
        g = min(1.0, math.sqrt(g_sq))

        orders: list[OrderEvent] = []
        for ticker, _, price in candidates:
            notional = g * weights[ticker] * equity
            orders.append(_order(event.timestamp, ticker, round(notional / price)))
        return [order for order in orders if order.quantity > 0]

    def process_fill(self, event: FillEvent) -> None:
        signed_delta = event.quantity if event.direction == "BUY" else -event.quantity
        self._cash -= signed_delta * event.fill_price + event.commission

        prior = self._positions.get(event.ticker)
        prior_qty = prior.quantity if prior is not None else 0
        new_qty = prior_qty + signed_delta

        if new_qty == 0:
            self._positions.pop(event.ticker, None)
        elif prior is None or (prior_qty > 0) != (new_qty > 0):
            # Opening a fresh position or flipping direction resets the cost basis.
            self._positions[event.ticker] = Position(
                ticker=event.ticker,
                quantity=new_qty,
                entry_price=event.fill_price,
                entry_date=event.timestamp,
            )
        else:
            # Adding to an existing position keeps its original entry price/date.
            self._positions[event.ticker] = replace(prior, quantity=new_qty)


def _order(timestamp: datetime, ticker: Ticker, delta: int) -> OrderEvent:
    return OrderEvent(
        timestamp=timestamp,
        ticker=ticker,
        quantity=abs(delta),
        direction="BUY" if delta > 0 else "SELL",
    )
