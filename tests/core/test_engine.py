from collections.abc import Sequence
from datetime import datetime

from backtester.core.engine import (
    Engine,
    ExecutionHandler,
    Portfolio,
    RiskManager,
    Strategy,
    Tracker,
)
from backtester.core.events import Bar, FillEvent, MarketEvent, OrderEvent, SignalEvent

TS = datetime(2024, 1, 1)
BAR = Bar(close=150.0)


class StubDataHandler:
    def __init__(self, bars: list[MarketEvent]) -> None:
        self._bars = bars
        self._idx = 0

    def get_next_bar(self) -> MarketEvent | None:
        if self._idx >= len(self._bars):
            return None
        event = self._bars[self._idx]
        self._idx += 1
        return event

    def get_price(self, ticker: str) -> float | None:
        return None


class StubStrategy:
    """Emits one SignalEvent per bar with score 1.0 for every ticker received."""

    def __init__(self) -> None:
        self.received: list[MarketEvent] = []

    def process_market(self, event: MarketEvent) -> SignalEvent:
        self.received.append(event)
        return SignalEvent(timestamp=event.timestamp, scores=dict.fromkeys(event.bars, 1.0))


class StubPortfolio:
    """Issues a 100-share BUY for every ticker with a positive score."""

    def __init__(self) -> None:
        self.signals: list[SignalEvent] = []
        self.fills: list[FillEvent] = []

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        self.signals.append(event)
        return [
            OrderEvent(timestamp=event.timestamp, ticker=t, quantity=100, direction="BUY")
            for t, s in event.scores.items()
            if s > 0
        ]

    def process_fill(self, event: FillEvent) -> None:
        self.fills.append(event)


class StubExecutionHandler:
    """Fills every order at the BAR close price with fixed commission and slippage."""

    COMMISSION = 1.0
    SLIPPAGE = 0.05

    def __init__(self) -> None:
        self.orders: list[OrderEvent] = []

    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]:
        self.orders.append(event)
        return [
            FillEvent(
                timestamp=event.timestamp,
                ticker=event.ticker,
                quantity=event.quantity,
                direction=event.direction,
                fill_price=BAR.close,
                commission=self.COMMISSION,
                slippage=self.SLIPPAGE,
            )
        ]


class RecordingRiskManager:
    """Passes every order batch through untouched, recording what it saw."""

    def __init__(self) -> None:
        self.market_events: list[MarketEvent] = []
        self.received_orders: list[list[OrderEvent]] = []

    def reconcile(self, event: MarketEvent, orders: Sequence[OrderEvent]) -> Sequence[OrderEvent]:
        self.market_events.append(event)
        self.received_orders.append(list(orders))
        return orders


class StubTracker:
    def __init__(self) -> None:
        self.observed: list[FillEvent] = []
        self.market_events: list[MarketEvent] = []

    def track_market(self, event: MarketEvent) -> None:
        self.market_events.append(event)

    def track_fill(self, event: FillEvent) -> None:
        self.observed.append(event)


def _make_engine(
    bars: list[MarketEvent],
    strategy: Strategy,
    portfolio: Portfolio,
    execution: ExecutionHandler,
    risk_manager: RiskManager | None = None,
    tracker: Tracker | None = None,
) -> Engine:
    return Engine(
        data_handler=StubDataHandler(bars),
        strategy=strategy,
        portfolio=portfolio,
        execution_handler=execution,
        risk_manager=risk_manager,
        tracker=tracker,
    )


def test_full_pipeline() -> None:
    """MarketEvent drives the full MARKET → SIGNAL → ORDER → FILL chain."""
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()

    assert strategy.received == [market]
    assert len(portfolio.signals) == 1
    assert "AAPL" in portfolio.signals[0].scores
    assert len(execution.orders) == 1
    assert execution.orders[0].ticker == "AAPL"
    assert len(portfolio.fills) == 1
    assert portfolio.fills[0].ticker == "AAPL"


def test_engine_processes_multiple_bars() -> None:
    ts2 = datetime(2024, 1, 2)
    bars = [
        MarketEvent(timestamp=TS, bars={"AAPL": BAR}),
        MarketEvent(timestamp=ts2, bars={"AAPL": Bar(close=155.0)}),
    ]
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()

    _make_engine(bars, strategy, portfolio, execution).run()

    assert len(strategy.received) == 2
    assert strategy.received[0].timestamp == TS
    assert strategy.received[1].timestamp == ts2
    assert len(portfolio.fills) == 2


def test_engine_stops_when_data_exhausted() -> None:
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()

    _make_engine([], strategy, portfolio, execution).run()

    assert strategy.received == []


def test_risk_manager_sees_strategy_order_batch() -> None:
    """The risk manager reconciles the strategy's order batch each bar."""
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()
    risk = RecordingRiskManager()

    _make_engine([market], strategy, portfolio, execution, risk_manager=risk).run()

    assert risk.market_events == [market]
    assert [o.ticker for o in risk.received_orders[0]] == ["AAPL"]


def test_risk_manager_reconciles_every_bar() -> None:
    ts2 = datetime(2024, 1, 2)
    bars = [
        MarketEvent(timestamp=TS, bars={"AAPL": BAR}),
        MarketEvent(timestamp=ts2, bars={"AAPL": Bar(close=155.0)}),
    ]
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()
    risk = RecordingRiskManager()

    _make_engine(bars, strategy, portfolio, execution, risk_manager=risk).run()

    assert risk.market_events == bars


def test_engine_runs_without_risk_manager() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()


def test_risk_manager_and_tracker_run_independently() -> None:
    """Both slots can be wired at once: tracker observes fills, risk reconciles orders."""
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()
    risk, tracker = RecordingRiskManager(), StubTracker()

    _make_engine([market], strategy, portfolio, execution, risk_manager=risk, tracker=tracker).run()

    assert risk.market_events == [market]
    assert [o.ticker for o in risk.received_orders[0]] == ["AAPL"]
    assert tracker.market_events == [market]
    assert tracker.observed[0].ticker == "AAPL"


class DropAllRiskManager:
    """Replaces the strategy's whole batch with a single fixed exit order."""

    def reconcile(self, event: MarketEvent, orders: Sequence[OrderEvent]) -> Sequence[OrderEvent]:
        return [OrderEvent(timestamp=event.timestamp, ticker="AAPL", quantity=7, direction="SELL")]


def test_risk_manager_beats_strategy() -> None:
    """Only the risk manager's reconciled orders reach the execution handler; the
    strategy's own order for the same ticker is overridden."""
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()

    _make_engine([market], strategy, portfolio, execution, risk_manager=DropAllRiskManager()).run()

    assert len(execution.orders) == 1
    assert execution.orders[0].direction == "SELL"
    assert execution.orders[0].quantity == 7
