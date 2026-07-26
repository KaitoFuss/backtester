import logging
import math
import statistics
from collections import deque
from collections.abc import Sequence
from dataclasses import replace

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, Position, SignalEvent, Ticker

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


class VolWeightedPortfolio:
    """Opens long/short positions sized by conviction-per-unit-risk.

    A ticker's raw weight is ``score / sigma`` (its trailing annualized return
    vol): the signal magnitude is conviction, ``1 / sigma`` is the risk weight,
    so a stronger signal on a calmer name gets more exposure. The batch of new
    opens is normalized into the gross exposure still available under
    ``max_gross`` — the leverage limit, gross exposure as a multiple of equity
    (``1.0`` = fully invested, ``2.0`` = up to 2x long/short). Cash is tracked
    as an accounting balance but is not itself a sizing constraint; the leverage
    cap is.

    Positions move through discrete flat -> open -> flat cycles rather than
    resizing every bar: a flat ticker opens only once ``abs(score)`` reaches
    ``entry_threshold``, sized once from the current signal; an open position is
    held unchanged until it closes, which happens when the score's sign flips,
    drops below ``exit_threshold``, or is exactly 0. A ticker absent from a
    signal's ``scores`` is left untouched (hold). Because held positions are
    never resized, new opens may only claim the gross budget those positions
    leave free under ``max_gross``.

    Until every relevant ticker (the ones being opened and the ones already
    held) has ``vol_window`` observed returns, vol is unknown, so that bar falls
    back to score-proportional sizing within the same gross budget.
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
        self._price_source = price_source
        self._cash = initial_cash
        self._positions: dict[Ticker, Position] = {}
        self._entry_threshold = entry_threshold
        self._exit_threshold = exit_threshold
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

    def _record_returns_for_vol(self, tickers: set[Ticker]) -> None:
        """Append each ticker's latest log return to its trailing window, giving
        ``annualized_vol`` the history it works from. ``Bar`` guarantees prices
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

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        # Update returns for tickers in this signal AND ones we currently hold,
        # so held names keep a live vol estimate on bars where they're absent
        # from `scores` (the `| set(...)` unions both ticker sets).
        tracked_tickers = set(event.scores) | set(self._positions)
        self._record_returns_for_vol(tracked_tickers)
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
                    orders.append(
                        OrderEvent(
                            timestamp=event.timestamp,
                            ticker=ticker,
                            quantity=abs(current_qty),
                            direction="SELL" if current_qty > 0 else "BUY",
                        )
                    )

        orders.extend(self._size_opens(event, open_candidates, equity))
        return orders

    def _size_opens(
        self, event: SignalEvent, candidates: list[tuple[Ticker, float, float]], equity: float
    ) -> list[OrderEvent]:
        if not candidates or equity <= 0:
            return []

        # Inverse-vol conviction weights (score / sigma) once every relevant
        # ticker has a vol estimate; otherwise fall back to score-proportional.
        candidate_vols = {
            ticker: annualized_vol(self._returns.get(ticker), self._vol_window)
            for ticker, _, _ in candidates
        }
        held_vols = {
            ticker: annualized_vol(self._returns.get(ticker), self._vol_window)
            for ticker in self._positions
        }
        vols_ready = all(v is not None for v in candidate_vols.values()) and all(
            v is not None for v in held_vols.values()
        )
        if vols_ready:
            raw = {ticker: score / candidate_vols[ticker] for ticker, score, _ in candidates}  # type: ignore[operator]
        else:
            raw = {ticker: score for ticker, score, _ in candidates}

        total_abs_raw = sum(abs(r) for r in raw.values())
        if total_abs_raw == 0.0:
            return []

        # Held positions are never resized, so new opens may only use the gross
        # budget left free under the max_gross leverage cap.
        existing_gross = 0.0
        for ticker, position in self._positions.items():
            price = self._price_source.get_price(ticker)
            if price is not None:
                existing_gross += abs(position.quantity * price / equity)
        available = max(0.0, self._max_gross - existing_gross)
        if available == 0.0:
            return []

        orders: list[OrderEvent] = []
        for ticker, _, price in candidates:
            weight = raw[ticker] / total_abs_raw * available
            qty = round(weight * equity / price)
            if qty == 0:
                continue
            orders.append(
                OrderEvent(
                    timestamp=event.timestamp,
                    ticker=ticker,
                    quantity=abs(qty),
                    direction="BUY" if qty > 0 else "SELL",
                )
            )
        return orders

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


def annualized_vol(returns: deque[float] | None, window: int) -> float | None:
    """Annualized stdev of a trailing return window, or ``None`` until the
    window is full or when the sample has no dispersion."""
    if returns is None or len(returns) < window:
        return None
    stdev = statistics.stdev(returns)
    if stdev == 0:
        return None
    return stdev * math.sqrt(TRADING_DAYS_PER_YEAR)
