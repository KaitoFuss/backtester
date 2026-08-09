import logging
import math
from collections import deque
from collections.abc import Mapping
from datetime import datetime

from backtester.core.engine import PriceSource
from backtester.core.events import SignalEvent, Ticker
from backtester.portfolio.base import BasePortfolio
from backtester.portfolio.utils import annualized_vol

logger = logging.getLogger(__name__)


class VolWeightedPortfolio(BasePortfolio):
    """Opens long/short positions sized by conviction times a target risk
    contribution per unit vol.

    A ticker's raw weight is ``score * target_vol / sigma`` (its trailing
    annualized return vol): the signal magnitude and sign is conviction and
    direction, and ``target_vol / sigma`` scales that into a weight sized so a
    unit-conviction position on this name contributes roughly ``target_vol`` of
    risk. A candidate without a full ``vol_window`` of returns yet is skipped
    for the bar (no fallback) rather than guessed at. The batch of new opens is
    then capped — never scaled up, only down — to fit within the gross exposure
    still available under ``max_gross``. Cash is tracked as an accounting
    balance but is not itself a sizing constraint; the leverage cap is.

    Position lifecycle (flat -> open -> flat) and the gross-budget accounting
    are inherited from ``BasePortfolio``.
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
        super().__init__(
            price_source=price_source,
            initial_cash=initial_cash,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            max_gross=max_gross,
        )
        self._vol_window = vol_window
        self._target_vol = target_vol
        self._returns: dict[Ticker, deque[float]] = {}
        self._last_price: dict[Ticker, float] = {}

    def _prepare(self, event: SignalEvent) -> None:
        # Update returns for tickers in this signal AND ones we currently hold,
        # so held names keep a live vol estimate on bars where they're absent
        # from `scores` (the `| set(...)` unions both ticker sets).
        tracked_tickers = set(event.scores) | set(self._positions)
        self._record_returns_for_vol(tracked_tickers, event.timestamp)

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

    def _target_weights(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        available: float,
    ) -> Mapping[Ticker, float]:
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
            return {}

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
        return {ticker: r * scale for ticker, r in raw.items()}
