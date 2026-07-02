from dataclasses import dataclass
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
    timestamp: datetime
    bars: dict[str, Bar]
    type: Literal["MARKET"] = "MARKET"


@dataclass(frozen=True)
class SignalEvent:
    timestamp: datetime
    scores: dict[str, float]
    type: Literal["SIGNAL"] = "SIGNAL"


@dataclass(frozen=True)
class OrderEvent:
    timestamp: datetime
    ticker: str
    quantity: int
    direction: Literal["BUY", "SELL"]
    type: Literal["ORDER"] = "ORDER"


@dataclass(frozen=True)
class FillEvent:
    timestamp: datetime
    ticker: str
    quantity: int
    direction: Literal["BUY", "SELL"]
    fill_price: float
    commission: float
    slippage: float
    type: Literal["FILL"] = "FILL"


Event = MarketEvent | SignalEvent | OrderEvent | FillEvent
