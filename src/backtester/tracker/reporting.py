import calendar
import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime

import pandas as pd

from backtester.tracker.metrics import TRADING_DAYS_PER_YEAR, max_drawdown, sharpe_ratio


def monthly_returns_table(history: Sequence[tuple[datetime, float]]) -> pd.DataFrame:
    """Year x month return grid, with trailing Annual Return / Max DD / Sharpe columns."""
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
        annual_vol = (
            statistics.stdev(year_returns) * TRADING_DAYS_PER_YEAR**0.5
            if len(year_returns) > 1
            else 0.0
        )
        annual_returns.append(annual_return)
        max_drawdowns.append(max_drawdown(year_values))
        sharpes.append(sharpe_ratio(annual_return, annual_vol))

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
