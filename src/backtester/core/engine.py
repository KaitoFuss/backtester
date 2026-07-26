from collections.abc import Sequence
from typing import Protocol

from backtester.core.events import (
    Event,
    FillEvent,
    MarketEvent,
    OrderEvent,
    Position,
    SignalEvent,
)
from backtester.core.queue import EventQueue


class DataHandler(Protocol):
    def get_next_bar(self) -> MarketEvent | None: ...


class PriceSource(Protocol):
    def get_price(self, ticker: str) -> float | None: ...


class PortfolioView(Protocol):
    """Read-only view of the portfolio, shared with components that observe
    positions and equity without mutating them (risk manager, tracker)."""

    def get_position(self, ticker: str) -> Position | None: ...
    def mark_to_market(self) -> float: ...


class Strategy(Protocol):
    def process_market(self, event: MarketEvent) -> SignalEvent: ...


class Portfolio(PortfolioView, Protocol):
    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]: ...
    def process_fill(self, event: FillEvent) -> None: ...


class ExecutionHandler(Protocol):
    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]: ...


class RiskManager(Protocol):
    def reconcile(
        self, event: MarketEvent, orders: Sequence[OrderEvent]
    ) -> Sequence[OrderEvent]: ...


class Tracker(Protocol):
    def track_market(self, event: MarketEvent) -> None: ...
    def track_fill(self, event: FillEvent) -> None: ...


class Engine:
    def __init__(
        self,
        data_handler: DataHandler,
        strategy: Strategy,
        portfolio: Portfolio,
        execution_handler: ExecutionHandler,
        risk_manager: RiskManager | None = None,
        tracker: Tracker | None = None,
    ) -> None:
        self._data_handler = data_handler
        self._strategy = strategy
        self._portfolio = portfolio
        self._execution_handler = execution_handler
        self._risk_manager = risk_manager
        self._tracker = tracker
        self._queue = EventQueue()
        self._current_bar: MarketEvent | None = None

    def _put_all(self, events: Sequence[Event]) -> None:
        for e in events:
            self._queue.put(e)

    def _dispatch(self, event: Event) -> None:
        match event:
            case MarketEvent():
                if self._tracker is not None:
                    self._tracker.track_market(event)
                # The strategy emits exactly one SignalEvent per bar (possibly
                # empty), kept here so the SignalEvent stage can hand it to the
                # risk manager — which therefore reconciles once every bar.
                self._current_bar = event
                self._queue.put(self._strategy.process_market(event))
            case SignalEvent():
                orders = self._portfolio.process_signal(event)
                # The risk manager sees the full order batch for this bar and
                # returns the final set to trade: it drops strategy orders on
                # tickers it is exiting and appends its own exits (risk beats
                # strategy). `_current_bar` is the MarketEvent behind this signal.
                if self._risk_manager is not None:
                    assert self._current_bar is not None
                    orders = self._risk_manager.reconcile(self._current_bar, orders)
                self._put_all(orders)
            case OrderEvent():
                self._put_all(self._execution_handler.process_order(event))
            case FillEvent():
                if self._tracker is not None:
                    self._tracker.track_fill(event)
                self._portfolio.process_fill(event)
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
        self._liquidate_open_positions()

    def _liquidate_open_positions(self) -> None:
        """Force-close open positions on the last bar's tickers at the end of
        the run, so performance metrics reflect realized rather than
        marked-to-market PnL on positions still open when data runs out."""
        if self._current_bar is None:
            return
        for ticker in self._current_bar.bars:
            position = self._portfolio.get_position(ticker)
            if position is None or position.quantity == 0:
                continue
            self._queue.put(
                OrderEvent(
                    timestamp=self._current_bar.timestamp,
                    ticker=ticker,
                    quantity=abs(position.quantity),
                    direction="SELL" if position.quantity > 0 else "BUY",
                )
            )
        while not self._queue.empty():
            self._dispatch(self._queue.get())
