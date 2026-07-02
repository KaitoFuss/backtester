from collections.abc import Iterator
from typing import Protocol

from backtester.core.events import MarketEvent


class DataHandlerProtocol(Protocol):
    def __iter__(self) -> Iterator[MarketEvent]: ...
    def __next__(self) -> MarketEvent: ...
