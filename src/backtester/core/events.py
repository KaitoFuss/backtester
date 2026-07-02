from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class Bar:
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


@dataclass(frozen=True)
class MarketEvent:
    type: Literal["MARKET"] = field(default="MARKET", init=False)
    timestamp: datetime
    bars: dict[str, Bar]
