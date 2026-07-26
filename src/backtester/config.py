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
    data: str
    tickers: list[str] | None = None
    window: int = 20
    initial_cash: float = 100_000.0
    entry_threshold: float = 0.0
    exit_threshold: float = 0.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_holding_days: int | None = None
    plot_dir: str = "output"

    @classmethod
    def from_json(cls, path: Path) -> Self:
        return cls(**json.loads(path.read_text()))
