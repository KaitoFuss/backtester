import logging
import math
import statistics
from collections import deque
from collections.abc import Sequence
from datetime import datetime

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, Position, SignalEvent, Ticker
from backtester.portfolio.utils import (
    apply_fill,
    compute_equity,
    existing_gross,
    partition_signal,
    size_to_orders,
)

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


class VolWeightedPortfolio:
    """Opens long/short positions sized by conviction times a target risk
    contribution per unit vol.

    A ticker's raw weight is ``score * target_vol / sigma`` (its trailing
    annualized return vol): the signal magnitude and sign is conviction and
    direction, and ``target_vol / sigma`` scales that into a weight sized so a
    unit-conviction position on this name contributes roughly ``target_vol`` of
    risk. A candidate without a full ``vol_window`` of returns yet is skipped
    for the bar (no fallback) rather than guessed at. The batch of new opens is
    then capped — never scaled up, only down — to fit within the gross exposure
    still available under ``max_gross``, the leverage limit (gross exposure as
    a multiple of equity; ``1.0`` = fully invested, ``2.0`` = up to 2x
    long/short). Cash is tracked as an accounting balance but is not itself a
    sizing constraint; the leverage cap is.

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
        target_vol: float = 0.2,
    ) -> None:
        self._price_source = price_source
        self._cash = initial_cash
        self._positions: dict[Ticker, Position] = {}
        self._entry_threshold = entry_threshold
        self._exit_threshold = exit_threshold
        self._vol_window = vol_window
        self._max_gross = max_gross
        self._target_vol = target_vol
        self._returns: dict[Ticker, deque[float]] = {}
        self._last_price: dict[Ticker, float] = {}

    def get_position(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)

    def mark_to_market(self) -> float:
        return compute_equity(self._cash, self._positions, self._price_source)

    def _record_returns_for_vol(self, tickers: set[Ticker], timestamp: datetime) -> None:
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
                logger.debug(
                    "%s  %s: return=%.5f window=%d/%d",
                    timestamp,
                    ticker,
                    returns[-1],
                    len(returns),
                    self._vol_window,
                )

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        # Update returns for tickers in this signal AND ones we currently hold,
        # so held names keep a live vol estimate on bars where they're absent
        # from `scores` (the `| set(...)` unions both ticker sets).
        tracked_tickers = set(event.scores) | set(self._positions)
        self._record_returns_for_vol(tracked_tickers, event.timestamp)
        equity = self.mark_to_market()

        close_orders, open_candidates = partition_signal(
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

        # Signed conviction (score) scaled to a target risk contribution per
        # unit vol; a candidate without a ready vol estimate is skipped.
        candidate_vols: dict[Ticker, float] = {}
        for ticker, _, _ in candidates:
            vol = annualized_vol(self._returns.get(ticker), self._vol_window)
            if vol is None:
                logger.debug(
                    "%s  %s: vol not ready (%d/%d returns), skipping open",
                    event.timestamp,
                    ticker,
                    len(self._returns.get(ticker, [])),
                    self._vol_window,
                )
            else:
                candidate_vols[ticker] = vol
                logger.debug("%s  %s: annualized_vol=%.4f", event.timestamp, ticker, vol)

        raw = {
            ticker: score * self._target_vol / candidate_vols[ticker]
            for ticker, score, _ in candidates
            if ticker in candidate_vols
        }
        total_abs_raw = sum(abs(r) for r in raw.values())
        if total_abs_raw == 0.0:
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

        # target_vol sets each name's target size directly; only scale the
        # whole batch down if it would breach the budget, never up to fill it.
        scale = min(1.0, available / total_abs_raw)
        if scale < 1.0:
            logger.info(
                "%s  Gross budget %.4f < requested %.4f, scaling opens by %.3f",
                event.timestamp,
                available,
                total_abs_raw,
                scale,
            )
        weights = {ticker: r * scale for ticker, r in raw.items()}
        return size_to_orders(weights, candidates, equity, event.timestamp)

    def process_fill(self, event: FillEvent) -> None:
        self._cash = apply_fill(self._cash, self._positions, event)


def annualized_vol(returns: deque[float] | None, window: int) -> float | None:
    """Annualized stdev of a trailing return window, or ``None`` until the
    window is full or when the sample has no dispersion."""
    if returns is None or len(returns) < window:
        return None
    stdev = statistics.stdev(returns)
    if stdev == 0:
        return None
    return stdev * math.sqrt(TRADING_DAYS_PER_YEAR)
