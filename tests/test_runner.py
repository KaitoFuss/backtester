import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from backtester.portfolio.equal_weight import EqualWeightPortfolio
from backtester.runner import run_backtest, verbosity_to_level
from backtester.strategy.buy_and_hold import BuyAndHoldStrategy


def test_no_flag_is_quiet() -> None:
    assert verbosity_to_level(0) == logging.WARNING


def test_single_v_is_the_trade_blotter() -> None:
    assert verbosity_to_level(1) == logging.INFO


def test_double_v_is_debug() -> None:
    assert verbosity_to_level(2) == logging.DEBUG


def test_more_vs_stay_at_debug() -> None:
    assert verbosity_to_level(7) == logging.DEBUG


@dataclass(frozen=True)
class _MinimalConfig:
    """Only the fields ``run_backtest()`` actually reads off a config — no
    ``BacktestConfig`` in sight. Proves ``run_backtest`` is typed against the
    structural ``EngineConfig`` protocol rather than the concrete dataclass."""

    data: str
    tickers: list[str] | None
    cost_bps: float
    commission_bps: float
    risk_free_rate: float


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    frame = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
            "ticker": ["QQQ", "QQQ"],
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 102.0],
            "volume": [1000.0, 1100.0],
        }
    )
    path = tmp_path / "raw.parquet"
    frame.to_parquet(path, index=False)
    return path


def test_run_backtest_accepts_a_minimal_custom_config(data_file: Path) -> None:
    config = _MinimalConfig(
        data=str(data_file),
        tickers=None,
        cost_bps=0.0,
        commission_bps=0.0,
        risk_free_rate=0.0,
    )

    tracker = run_backtest(
        BuyAndHoldStrategy(),
        lambda price_source: EqualWeightPortfolio(
            price_source=price_source, initial_cash=100_000.0
        ),
        lambda portfolio: None,
        config,
    )

    metrics = tracker.metrics()
    assert metrics.total_return != 0.0
