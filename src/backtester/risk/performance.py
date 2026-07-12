import statistics
from dataclasses import dataclass
from datetime import datetime

from backtester.core.engine import EquitySource
from backtester.core.events import FillEvent, MarketEvent

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    annualized_return: float
    annualized_vol: float
    sharpe: float
    max_drawdown: float


class PerformanceTracker:
    def __init__(self, portfolio: EquitySource) -> None:
        self._portfolio = portfolio
        self._equity_curve: list[tuple[datetime, float]] = []

    def evaluate_market(self, event: MarketEvent) -> None:
        self._equity_curve.append((event.timestamp, self._portfolio.equity()))

    def evaluate_fill(self, event: FillEvent) -> None:
        pass

    @property
    def equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._equity_curve)

    def metrics(self) -> PerformanceMetrics:
        if len(self._equity_curve) < 2:
            return PerformanceMetrics(0.0, 0.0, 0.0, 0.0, 0.0)

        values = [equity for _, equity in self._equity_curve]
        returns = [values[i] / values[i - 1] - 1 for i in range(1, len(values))]

        total_return = values[-1] / values[0] - 1
        periods_per_year = TRADING_DAYS_PER_YEAR / len(returns)
        annualized_return = (1 + total_return) ** periods_per_year - 1
        annualized_vol = (
            statistics.stdev(returns) * TRADING_DAYS_PER_YEAR**0.5 if len(returns) > 1 else 0.0
        )
        sharpe = annualized_return / annualized_vol if annualized_vol > 0 else 0.0

        peak = values[0]
        max_drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            max_drawdown = min(max_drawdown, value / peak - 1)

        return PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            annualized_vol=annualized_vol,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
        )
