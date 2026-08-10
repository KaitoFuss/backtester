from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Self


@dataclass(frozen=True)
class FetchDataConfig:
    tickers: list[str]
    start: str
    end: str
    out: str = "data/raw"

    @classmethod
    def from_json(cls, path: Path) -> Self:
        return cls(**json.loads(path.read_text()))


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
    cost_bps: float = 0.0
    """Half-spread paid per fill, in basis points. A round trip costs 2x this."""
    commission_bps: float = 0.0
    """Commission per fill, in basis points of filled notional."""
    drift_band: float = 0.0
    """Rebalancing no-trade band, as an absolute fraction of equity. 0.005 = 50bp."""
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_holding_days: int | None = None
    output_dir: str = "output"

    @classmethod
    def from_json(cls, path: Path) -> Self:
        return cls(**json.loads(path.read_text()))
