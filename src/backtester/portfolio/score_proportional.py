import logging
from collections.abc import Mapping

from backtester.core.events import SignalEvent, Ticker
from backtester.portfolio.base import BasePortfolio

logger = logging.getLogger(__name__)


class ScoreProportionalPortfolio(BasePortfolio):
    """Default, no-frills portfolio: opens positions in proportion to signal
    score (``score / total abs score``), normalized into the gross exposure
    still available under ``max_gross``. Only equal-weights when every open
    candidate's score has the same magnitude (e.g. ``BuyAndHoldStrategy``,
    which always signals ``1.0``); otherwise larger-magnitude scores get
    proportionally larger positions. No vol estimate is required, so a
    position opens on the same bar its score first qualifies — this is the
    reference portfolio for strategies like ``BuyAndHoldStrategy`` that need to
    invest immediately rather than wait out a vol warm-up window.

    Position lifecycle (flat -> open -> flat) is inherited from
    ``BasePortfolio``.
    """

    def _target_weights(
        self,
        event: SignalEvent,
        candidates: list[tuple[Ticker, float, float]],
        available: float,
    ) -> Mapping[Ticker, float]:
        total_abs_score = sum(abs(score) for _, score, _ in candidates)
        if total_abs_score == 0.0:
            return {}
        if available < self._max_gross:
            logger.info(
                "%s  Gross budget reduced to %.4f (max_gross=%.4f) by existing positions",
                event.timestamp,
                available,
                self._max_gross,
            )
        return {ticker: score / total_abs_score * available for ticker, score, _ in candidates}
