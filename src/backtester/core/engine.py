from collections.abc import Sequence
from typing import Protocol

from backtester.core.events import Event, FillEvent, MarketEvent, OrderEvent, SignalEvent
from backtester.core.queue import EventQueue


class DataHandler(Protocol):
    def get_next_bar(self) -> MarketEvent | None: ...


class PriceSource(Protocol):
    def get_price(self, ticker: str) -> float | None: ...


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
    def evaluate_market(self, event: MarketEvent) -> Sequence[OrderEvent]: ...
    def evaluate_fill(self, event: FillEvent) -> Sequence[OrderEvent]: ...


class Evaluator(Protocol):
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
        evaluator: Evaluator | None = None,
    ) -> None:
        self._data_handler = data_handler
        self._strategy = strategy
        self._portfolio = portfolio
        self._execution_handler = execution_handler
        self._risk_manager = risk_manager
        self._evaluator = evaluator
        self._queue = EventQueue()

    def _put_all(self, events: Sequence[Event]) -> None:
        for e in events:
            self._queue.put(e)

    def _settle_order(self, order: OrderEvent) -> None:
        for fill in self._execution_handler.process_order(order):
            self._process_fill(fill)

    def _process_fill(self, fill: FillEvent) -> None:
        if self._evaluator is not None:
            self._evaluator.evaluate_fill(fill)
        if self._risk_manager is not None:
            for order in self._risk_manager.evaluate_fill(fill):
                self._settle_order(order)
        self._put_all(self._portfolio.process_fill(fill))

    def _dispatch(self, event: Event) -> None:
        match event:
            case MarketEvent():
                if self._evaluator is not None:
                    self._evaluator.evaluate_market(event)
                if self._risk_manager is not None:
                    for order in self._risk_manager.evaluate_market(event):
                        self._settle_order(order)
                self._put_all(self._strategy.process_market(event))
            case SignalEvent():
                self._put_all(self._portfolio.process_signal(event))
            case OrderEvent():
                self._put_all(self._execution_handler.process_order(event))
            case FillEvent():
                self._process_fill(event)
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
