from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self


@dataclass(frozen=True)
class FetchDataConfig:
    tickers: list[str]
    start: str
    end: str
    out: str = "data/raw.parquet"

    @classmethod
    def from_json(cls, path: Path) -> Self:
        return cls(**json.loads(path.read_text()))


class EngineConfig(Protocol):
    """Structural type for what ``run_backtest()`` actually reads off a config.

    ``BacktestConfig`` satisfies this without any changes, but so does any
    other config dataclass a caller already has — letting them pass their own
    config straight into ``run_backtest()`` instead of lossily adapting it
    into a ``BacktestConfig`` first."""

    # Declared as read-only properties, not plain attributes: a plain attribute
    # in a Protocol also demands a setter, which a frozen dataclass (like
    # ``BacktestConfig``) can never satisfy.
    @property
    def data(self) -> str: ...
    @property
    def tickers(self) -> list[str] | None: ...
    @property
    def cost_bps(self) -> float: ...
    @property
    def commission_bps(self) -> float: ...
    @property
    def risk_free_rate(self) -> float: ...


@dataclass(frozen=True)
class BacktestConfig:
    name: str
    data: str
    tickers: list[str] | None = None
    portfolio: str = "inverse_vol"
    window: int = 20
    initial_cash: float = 100_000.0
    entry_threshold: float = 0.0
    exit_threshold: float = 0.0
    vol_window: int = 20
    max_gross: float = 1.0
    dollar_neutral: bool = False
    winsor_limit: float = 3.0
    cost_bps: float = 0.0  # half-spread paid per fill, in bp; a round trip costs 2x this
    commission_bps: float = 0.0  # commission per fill, in bp of filled notional
    drift_band: float = 0.0  # rebalancing no-trade band, as a fraction of equity; 0.005 = 50bp
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_holding_days: int | None = None
    output_dir: str = "output"
    risk_free_rate: float = 0.0
    """Annualized risk-free rate subtracted from returns when computing Sharpe."""

    @classmethod
    def from_json(cls, path: Path) -> Self:
        return cls(**json.loads(path.read_text()))
