import statistics
from dataclasses import dataclass
from datetime import datetime

from backtester.core.engine import PortfolioView
from backtester.core.events import FillEvent, MarketEvent

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    annualized_return: float
    annualized_vol: float
    sharpe: float
    max_drawdown: float


def _sharpe_ratio(annualized_return: float, annualized_vol: float) -> float:
    return annualized_return / annualized_vol if annualized_vol > 0 else 0.0


def _max_drawdown(values: list[float]) -> float:
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1)
    return max_drawdown


class PerformanceTracker:
    def __init__(self, portfolio: PortfolioView) -> None:
        self._portfolio = portfolio
        self._mark_to_market_history: list[tuple[datetime, float]] = []

    def track_market(self, event: MarketEvent) -> None:
        self._mark_to_market_history.append((event.timestamp, self._portfolio.mark_to_market()))

    def track_fill(self, event: FillEvent) -> None:
        # Reserved for fill-level stats the mark-to-market history can't derive on its own:
        # trade count, win rate, slippage/commission drag, turnover.
        pass

    @property
    def mark_to_market_history(self) -> list[tuple[datetime, float]]:
        return list(self._mark_to_market_history)

    def metrics(self) -> PerformanceMetrics:
        if len(self._mark_to_market_history) < 2:
            return PerformanceMetrics(0.0, 0.0, 0.0, 0.0, 0.0)

        values = [equity for _, equity in self._mark_to_market_history]
        returns = [values[i] / values[i - 1] - 1 for i in range(1, len(values))]

        total_return = values[-1] / values[0] - 1
        periods_per_year = TRADING_DAYS_PER_YEAR / len(returns)
        annualized_return = (1 + total_return) ** periods_per_year - 1
        annualized_vol = (
            statistics.stdev(returns) * TRADING_DAYS_PER_YEAR**0.5 if len(returns) > 1 else 0.0
        )

        return PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            annualized_vol=annualized_vol,
            sharpe=_sharpe_ratio(annualized_return, annualized_vol),
            max_drawdown=_max_drawdown(values),
        )
