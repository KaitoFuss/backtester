import logging
import statistics
from dataclasses import dataclass
from datetime import datetime

from backtester.core.engine import PortfolioView
from backtester.core.events import FillEvent, MarketEvent, Ticker

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    annualized_return: float
    annualized_vol: float
    sharpe: float
    max_drawdown: float


@dataclass(frozen=True)
class TradeMetrics:
    num_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    risk_reward_ratio: float
    payoff_factor: float
    cpc_index: float
    time_in_market: float
    turnover: float


@dataclass(frozen=True)
class _Trade:
    ticker: Ticker
    quantity: int
    entry_price: float
    exit_price: float
    entry_commission: float
    exit_commission: float

    @property
    def pnl(self) -> float:
        return (
            self.quantity * (self.exit_price - self.entry_price)
            - self.entry_commission
            - self.exit_commission
        )


def sharpe_ratio(annualized_return: float, annualized_vol: float) -> float:
    return annualized_return / annualized_vol if annualized_vol > 0 else 0.0


def max_drawdown(values: list[float]) -> float:
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
        self._open_trades: dict[Ticker, _Trade] = {}
        self._trades: list[_Trade] = []
        self._open_tickers: set[Ticker] = set()
        self._bars_in_market = 0
        self._traded_notional = 0.0

    def track_market(self, event: MarketEvent) -> None:
        # A bar with no prices for any traded ticker is outside the data window
        # for this universe (e.g. before the first listing, or after a data
        # feed ends). Recording it would mark held positions at stale prices and
        # pad the equity series with dead, zero-return points, flattening the
        # tail of every report and biasing the annualized metrics. Skipping such
        # bars lets the reported window track the actual data range dynamically.
        if not event.bars:
            logger.debug("%s: no prices in bar, skipping equity mark", event.timestamp)
            return
        equity = self._portfolio.mark_to_market()
        self._mark_to_market_history.append((event.timestamp, equity))
        logger.debug("%s: equity=%.2f", event.timestamp, equity)
        if self._open_tickers:
            self._bars_in_market += 1

    def track_fill(self, event: FillEvent) -> None:
        self._traded_notional += event.quantity * event.fill_price
        position_before = self._portfolio.get_position(event.ticker)

        if position_before is None:
            self._open_trades[event.ticker] = _Trade(
                ticker=event.ticker,
                quantity=event.quantity if event.direction == "BUY" else -event.quantity,
                entry_price=event.fill_price,
                exit_price=event.fill_price,
                entry_commission=event.commission,
                exit_commission=0.0,
            )
            self._open_tickers.add(event.ticker)
            return

        open_trade = self._open_trades.pop(event.ticker, None)
        self._open_tickers.discard(event.ticker)
        if open_trade is None:
            return
        closed_trade = _Trade(
            ticker=open_trade.ticker,
            quantity=open_trade.quantity,
            entry_price=open_trade.entry_price,
            exit_price=event.fill_price,
            entry_commission=open_trade.entry_commission,
            exit_commission=event.commission,
        )
        self._trades.append(closed_trade)
        logger.debug(
            "%s: trade closed, entry=%.4f exit=%.4f pnl=%.2f",
            closed_trade.ticker,
            closed_trade.entry_price,
            closed_trade.exit_price,
            closed_trade.pnl,
        )

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
            sharpe=sharpe_ratio(annualized_return, annualized_vol),
            max_drawdown=max_drawdown(values),
        )

    def trade_metrics(self) -> TradeMetrics:
        if not self._trades:
            return TradeMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        pnls = [trade.pnl for trade in self._trades]
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]

        win_rate = len(wins) / len(pnls)
        avg_win = statistics.mean(wins) if wins else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        risk_reward_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else 0.0
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        payoff_factor = gross_profit / gross_loss if gross_loss != 0 else 0.0
        cpc_index = win_rate * risk_reward_ratio * payoff_factor

        num_bars = len(self._mark_to_market_history)
        time_in_market = self._bars_in_market / num_bars if num_bars else 0.0

        equity = [value for _, value in self._mark_to_market_history]
        avg_equity = statistics.mean(equity) if equity else 0.0
        turnover = self._traded_notional / avg_equity if avg_equity else 0.0

        return TradeMetrics(
            num_trades=len(self._trades),
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            risk_reward_ratio=risk_reward_ratio,
            payoff_factor=payoff_factor,
            cpc_index=cpc_index,
            time_in_market=time_in_market,
            turnover=turnover,
        )
