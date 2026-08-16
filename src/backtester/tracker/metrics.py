"""Performance tracking and reporting metrics.

Two different "average return" conventions appear side by side here, and
they are not interchangeable: ``PerformanceMetrics.annualized_return`` is the
geometric CAGR (what the equity curve actually compounded at), while the
Sharpe ratio's numerator is the arithmetic mean of excess period returns
(what a mean-variance framework wants). Do not unify them.
"""

import calendar
import logging
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from backtester.core.engine import PortfolioView
from backtester.core.events import FillEvent, MarketEvent, Ticker
from backtester.utils.stats import mean_and_stdev

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return: float
    annualized_return: float
    annualized_vol: float
    sharpe: float
    max_drawdown: float
    drawdown_to_vol: float


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
    annual_turnover: float
    """Gross traded notional per year, as a multiple of average equity. Every
    fill counts once, so a full round trip of the whole book is 2.0."""


@dataclass(frozen=True)
class _Trade:
    """A closed round-trip: a signed entry quantity opened at ``entry_price``
    and flattened at ``exit_price``. ``quantity`` sign carries direction, so
    ``pnl`` is correct for both longs and shorts."""

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


@dataclass
class _OpenLot:
    """The still-open position for a ticker, as reconstructed from the fill
    stream. Mutable: fills add to it (weighted-average entry) or reduce it."""

    signed_qty: int
    avg_entry_price: float
    entry_commission: float


def sharpe_ratio(
    returns: Sequence[float],
    periods_per_year: float,
    risk_free_rate: float = 0.0,
) -> float:
    """Annualized Sharpe: mean excess period return over its standard
    deviation, scaled by the square root of periods per year.

    ``risk_free_rate`` is annualized and de-annualized geometrically. Note the
    numerator is the *arithmetic* mean of excess returns, not the geometric
    CAGR reported as ``annualized_return`` — the two answer different
    questions and both appear in the report.

    ``0.0`` when there is no dispersion to normalize against, or fewer than
    two returns to measure it from."""
    if len(returns) < 2:
        return 0.0
    rf_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    excess = [value - rf_period for value in returns]
    mean, stdev = mean_and_stdev(excess)
    if stdev == 0:
        return 0.0
    result: float = mean / stdev * periods_per_year**0.5
    return result


def drawdown_to_vol_ratio(max_drawdown: float, annualized_vol: float) -> float:
    """Depth of the worst drawdown per unit of annualized volatility. Higher
    means drawdowns are deep relative to the return dispersion that produced
    them. Uses ``abs(max_drawdown)`` so the ratio is positive; ``0.0`` when
    there is no volatility to normalize against."""
    return abs(max_drawdown) / annualized_vol if annualized_vol > 0 else 0.0


def max_drawdown(values: list[float]) -> float:
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1)
    return max_drawdown


class PerformanceTracker:
    def __init__(self, portfolio: PortfolioView, risk_free_rate: float = 0.0) -> None:
        self._portfolio = portfolio
        self._risk_free_rate = risk_free_rate
        self._mark_to_market_history: list[tuple[datetime, float]] = []
        self._open_lots: dict[Ticker, _OpenLot] = {}
        self._trades: list[_Trade] = []
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
        if self._open_lots:
            self._bars_in_market += 1

    def track_fill(self, event: FillEvent) -> None:
        # A self-contained running-lot ledger, built only from the fill stream,
        # so trade pairing never depends on the portfolio's internal state or on
        # this hook running before the portfolio applies the fill. Handles the
        # general open / add / reduce / close / flip cases, not just the
        # flat -> open -> flat cycle the current portfolios happen to produce.
        self._traded_notional += event.quantity * event.fill_price
        signed = event.quantity if event.direction == "BUY" else -event.quantity
        lot = self._open_lots.get(event.ticker)

        if lot is None:
            self._open_lots[event.ticker] = _OpenLot(signed, event.fill_price, event.commission)
            return

        if (lot.signed_qty > 0) == (signed > 0):
            # Same direction: scale in, weighting the entry price by quantity.
            total_qty = lot.signed_qty + signed
            lot.avg_entry_price = (
                lot.avg_entry_price * abs(lot.signed_qty) + event.fill_price * abs(signed)
            ) / abs(total_qty)
            lot.signed_qty = total_qty
            lot.entry_commission += event.commission
            return

        # Opposite direction: close part or all of the position (and maybe flip).
        closed_qty = min(abs(signed), abs(lot.signed_qty))
        entry_commission = lot.entry_commission * closed_qty / abs(lot.signed_qty)
        closed_trade = _Trade(
            ticker=event.ticker,
            quantity=closed_qty if lot.signed_qty > 0 else -closed_qty,
            entry_price=lot.avg_entry_price,
            exit_price=event.fill_price,
            entry_commission=entry_commission,
            exit_commission=event.commission,
        )
        self._trades.append(closed_trade)
        logger.debug(
            "%s  %s: trade closed, entry=%.4f exit=%.4f pnl=%.2f",
            event.timestamp,
            closed_trade.ticker,
            closed_trade.entry_price,
            closed_trade.exit_price,
            closed_trade.pnl,
        )

        remaining = lot.signed_qty + signed
        if remaining == 0:
            del self._open_lots[event.ticker]
        elif (remaining > 0) == (lot.signed_qty > 0):
            # Partial close: same direction, smaller size, same cost basis.
            lot.signed_qty = remaining
            lot.entry_commission -= entry_commission
        else:
            # Flip: this fill closed the old position and opened a new one in
            # the opposite direction with the leftover quantity. The fill's
            # commission is attributed to the close above; the reopened lot
            # carries none.
            self._open_lots[event.ticker] = _OpenLot(remaining, event.fill_price, 0.0)

    @property
    def mark_to_market_history(self) -> list[tuple[datetime, float]]:
        return list(self._mark_to_market_history)

    def metrics(self) -> PerformanceMetrics:
        if len(self._mark_to_market_history) < 2:
            return PerformanceMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        timestamps = [timestamp for timestamp, _ in self._mark_to_market_history]
        values = [equity for _, equity in self._mark_to_market_history]
        returns = [values[i] / values[i - 1] - 1 for i in range(1, len(values))]

        total_return = values[-1] / values[0] - 1
        # Annualize off elapsed calendar time, not the raw sample count, so that
        # gaps in the data (empty bars skipped by track_market) don't inflate
        # the annualized figures. periods_per_year is the observed return
        # frequency, used to annualize vol by the sqrt-of-time rule.
        years = (timestamps[-1] - timestamps[0]).days / 365.25
        if years > 0:
            annualized_return = (1 + total_return) ** (1 / years) - 1
            periods_per_year = len(returns) / years
            annualized_vol = (
                statistics.stdev(returns) * periods_per_year**0.5 if len(returns) > 1 else 0.0
            )
            sharpe = sharpe_ratio(returns, periods_per_year, self._risk_free_rate)
        else:
            # Every observation lands on the same calendar day, so there is no
            # elapsed time to annualize over and no observed return frequency
            # to scale by. Computing a Sharpe here would mean assuming a
            # frequency the data does not have, and it would then sit beside a
            # zeroed annualized_return and annualized_vol as an incoherent
            # triple. All three report nothing together.
            annualized_return = 0.0
            annualized_vol = 0.0
            sharpe = 0.0

        return PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            annualized_vol=annualized_vol,
            sharpe=sharpe,
            max_drawdown=max_drawdown(values),
            drawdown_to_vol=drawdown_to_vol_ratio(max_drawdown(values), annualized_vol),
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
        timestamps = [timestamp for timestamp, _ in self._mark_to_market_history]
        years = (timestamps[-1] - timestamps[0]).days / 365.25 if len(timestamps) > 1 else 0.0
        annual_turnover = (
            self._traded_notional / avg_equity / years if avg_equity and years > 0 else 0.0
        )

        return TradeMetrics(
            num_trades=len(self._trades),
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            risk_reward_ratio=risk_reward_ratio,
            payoff_factor=payoff_factor,
            cpc_index=cpc_index,
            time_in_market=time_in_market,
            annual_turnover=annual_turnover,
        )


def monthly_returns_table(history: Sequence[tuple[datetime, float]]) -> pd.DataFrame:
    """Year x month return grid, with trailing Annual Return / Max DD / Sharpe columns.

    The per-year Sharpe is computed excess-free (``risk_free_rate=0.0``): a
    single year's worth of risk-free rate isn't threaded through this table,
    so it will not match the headline, risk-free-adjusted Sharpe reported
    elsewhere.
    """
    if len(history) < 2:
        return pd.DataFrame()

    sorted_history = sorted(history, key=lambda item: item[0])
    monthly_last: dict[tuple[int, int], float] = {}
    for timestamp, value in sorted_history:
        monthly_last[(timestamp.year, timestamp.month)] = value

    rows: list[dict[str, float | int]] = []
    prev_value = sorted_history[0][1]
    for year, month in sorted(monthly_last):
        value = monthly_last[(year, month)]
        rows.append({"year": year, "month": month, "return": value / prev_value - 1})
        prev_value = value

    table = pd.DataFrame(rows)
    pivot = table.pivot(index="year", columns="month", values="return")
    pivot = pivot.reindex(columns=range(1, 13))
    pivot.columns = pd.Index([calendar.month_abbr[m] for m in range(1, 13)])

    annual_returns: list[float] = []
    max_drawdowns: list[float] = []
    sharpes: list[float] = []
    for year in pivot.index:
        year_values = [value for timestamp, value in sorted_history if timestamp.year == year]
        if len(year_values) < 2:
            annual_returns.append(0.0)
            max_drawdowns.append(0.0)
            sharpes.append(0.0)
            continue
        year_returns = [year_values[i] / year_values[i - 1] - 1 for i in range(1, len(year_values))]
        annual_return = year_values[-1] / year_values[0] - 1
        annual_returns.append(annual_return)
        max_drawdowns.append(max_drawdown(year_values))
        sharpes.append(sharpe_ratio(year_returns, TRADING_DAYS_PER_YEAR))

    pivot["Annual Return"] = annual_returns
    pivot["Max DD"] = max_drawdowns
    pivot["Sharpe"] = sharpes
    return pivot


def strategy_correlation_matrix(
    histories: Mapping[str, Sequence[tuple[datetime, float]]],
) -> pd.DataFrame:
    """Pairwise return correlation across strategies, e.g. to check market-neutrality."""
    returns = {}
    for label, history in histories.items():
        index = [timestamp for timestamp, _ in history]
        values = [value for _, value in history]
        equity = pd.Series(values, index=pd.DatetimeIndex(index))
        returns[label] = equity.pct_change().dropna()
    return pd.DataFrame(returns).corr()
