from datetime import datetime
from typing import cast

import pytest

from backtester.tracker.reporting import monthly_returns_table, strategy_correlation_matrix


def test_monthly_returns_table_buckets_by_year_and_month() -> None:
    history = [
        (datetime(2024, 1, 1), 1_000.0),
        (datetime(2024, 1, 31), 1_100.0),
        (datetime(2024, 2, 1), 1_100.0),
        (datetime(2024, 2, 28), 1_210.0),
    ]

    table = monthly_returns_table(history)

    assert table.loc[2024, "Jan"] == pytest.approx(0.10)
    assert table.loc[2024, "Feb"] == pytest.approx(0.10)
    assert table.loc[2024, "Annual Return"] == pytest.approx(1.21 - 1)
    assert table.loc[2024, "Max DD"] == pytest.approx(0.0)


def test_monthly_returns_table_with_insufficient_history_is_empty() -> None:
    table = monthly_returns_table([(datetime(2024, 1, 1), 1_000.0)])

    assert table.empty


def test_strategy_correlation_matrix_is_one_for_identical_series() -> None:
    history = [
        (datetime(2024, 1, 1), 1_000.0),
        (datetime(2024, 1, 2), 1_010.0),
        (datetime(2024, 1, 3), 990.0),
        (datetime(2024, 1, 4), 1_020.0),
    ]

    correlation = strategy_correlation_matrix({"A": history, "B": history})

    assert correlation.loc["A", "B"] == pytest.approx(1.0)


def test_strategy_correlation_matrix_is_negative_for_inverse_series() -> None:
    base = [1_000.0, 1_010.0, 990.0, 1_020.0]
    inverse = [1_000.0, 990.0, 1_010.0, 980.0]
    timestamps = [datetime(2024, 1, i + 1) for i in range(len(base))]

    correlation = strategy_correlation_matrix(
        {
            "A": list(zip(timestamps, base, strict=True)),
            "B": list(zip(timestamps, inverse, strict=True)),
        }
    )

    assert cast(float, correlation.loc["A", "B"]) < 0
