from collections.abc import Sequence
from typing import Protocol

from backtester.core.events import Event, FillEvent, MarketEvent, OrderEvent, SignalEvent
from backtester.core.queue import EventQueue


class DataHandler(Protocol):
    def get_next_bar(self) -> MarketEvent | None: ...


class PriceSource(Protocol):
    def get_price(self, ticker: str) -> float | None: ...


class MarketDataSource(DataHandler, PriceSource, Protocol):
    """A single object meant to be wired as both the engine's `DataHandler`
    and a shared `PriceSource` — `get_price` reflects bars already
    consumed via `get_next_bar`, so all consumers must share one instance."""


class PortfolioValuer(Protocol):
    def mark_to_market(self) -> float: ...


class Strategy(Protocol):
    def process_market(self, event: MarketEvent) -> Sequence[SignalEvent]: ...


class Portfolio(Protocol):
    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]: ...
    def process_fill(self, event: FillEvent) -> Sequence[OrderEvent]: ...


class ExecutionHandler(Protocol):
    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]: ...


class RiskManager(Protocol):
    def evaluate_market(self, event: MarketEvent) -> None: ...
    def evaluate_fill(self, event: FillEvent) -> None: ...


class Engine:
    def __init__(
        self,
        data_handler: DataHandler,
        strategy: Strategy,
        portfolio: Portfolio,
        execution_handler: ExecutionHandler,
        risk_manager: RiskManager | None = None,
    ) -> None:
        self._data_handler = data_handler
        self._strategy = strategy
        self._portfolio = portfolio
        self._execution_handler = execution_handler
        self._risk_manager = risk_manager
        self._queue = EventQueue()

    def _put_all(self, events: Sequence[Event]) -> None:
        for e in events:
            self._queue.put(e)

    def _dispatch(self, event: Event) -> None:
        match event:
            case MarketEvent():
                if self._risk_manager is not None:
                    self._risk_manager.evaluate_market(event)
                self._put_all(self._strategy.process_market(event))
            case SignalEvent():
                self._put_all(self._portfolio.process_signal(event))
            case OrderEvent():
                self._put_all(self._execution_handler.process_order(event))
            case FillEvent():
                if self._risk_manager is not None:
                    self._risk_manager.evaluate_fill(event)
                self._put_all(self._portfolio.process_fill(event))
            case _:
                raise NotImplementedError(f"unhandled event type: {event!r}")

    def run(self) -> None:
        while True:
            bar = self._data_handler.get_next_bar()
            if bar is None:
                break
            self._queue.put(bar)
            while not self._queue.empty():
                self._dispatch(self._queue.get())
