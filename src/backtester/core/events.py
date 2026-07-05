import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, NewType

Ticker = NewType("Ticker", str)


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
    bars: Mapping[Ticker, Bar]
    type: Literal["MARKET"] = field(default="MARKET", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", types.MappingProxyType(self.bars))


@dataclass(frozen=True)
class SignalEvent:
    timestamp: datetime
    scores: Mapping[Ticker, float]
    type: Literal["SIGNAL"] = field(default="SIGNAL", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scores", types.MappingProxyType(self.scores))


@dataclass(frozen=True)
class OrderEvent:
    timestamp: datetime
    ticker: Ticker
    quantity: int
    direction: Literal["BUY", "SELL"]
    type: Literal["ORDER"] = field(default="ORDER", init=False)


@dataclass(frozen=True)
class FillEvent:
    timestamp: datetime
    ticker: Ticker
    quantity: int
    direction: Literal["BUY", "SELL"]
    fill_price: float
    commission: float = 0.0
    slippage: float = 0.0
    type: Literal["FILL"] = field(default="FILL", init=False)


Event = MarketEvent | SignalEvent | OrderEvent | FillEvent
