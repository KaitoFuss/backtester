from collections.abc import Sequence
from datetime import datetime

from backtester.core.engine import Engine, ExecutionHandler, Portfolio, RiskManager, Strategy
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


class StubStrategy:
    """Emits one SignalEvent per bar with score 1.0 for every ticker received."""

    def __init__(self) -> None:
        self.received: list[MarketEvent] = []

    def process_market(self, event: MarketEvent) -> Sequence[SignalEvent]:
        self.received.append(event)
        return [SignalEvent(timestamp=event.timestamp, scores=dict.fromkeys(event.bars, 1.0))]


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

    def process_fill(self, event: FillEvent) -> Sequence[OrderEvent]:
        self.fills.append(event)
        return []


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
    def __init__(self) -> None:
        self.observed: list[FillEvent] = []

    def evaluate_fill(self, event: FillEvent) -> None:
        self.observed.append(event)


def _make_engine(
    bars: list[MarketEvent],
    strategy: Strategy,
    portfolio: Portfolio,
    execution: ExecutionHandler,
    risk_manager: RiskManager | None = None,
) -> Engine:
    return Engine(
        data_handler=StubDataHandler(bars),
        strategy=strategy,
        portfolio=portfolio,
        execution_handler=execution,
        risk_manager=risk_manager,
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


def test_fill_orders_dispatched() -> None:
    """Orders returned by process_fill are dispatched back through the execution handler."""

    class HedgingPortfolio(StubPortfolio):
        def process_fill(self, event: FillEvent) -> Sequence[OrderEvent]:
            self.fills.append(event)
            if event.ticker == "AAPL":
                return [
                    OrderEvent(
                        timestamp=event.timestamp, ticker="SPY", quantity=50, direction="SELL"
                    )
                ]
            return []

    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy, portfolio, execution = StubStrategy(), HedgingPortfolio(), StubExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()

    assert [o.ticker for o in execution.orders] == ["AAPL", "SPY"]


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


def test_risk_manager_evaluates_fills() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()
    risk = RecordingRiskManager()

    _make_engine([market], strategy, portfolio, execution, risk_manager=risk).run()

    assert len(risk.observed) == 1
    assert risk.observed[0].ticker == "AAPL"


def test_risk_manager_evaluates_fills_across_bars() -> None:
    ts2 = datetime(2024, 1, 2)
    bars = [
        MarketEvent(timestamp=TS, bars={"AAPL": BAR}),
        MarketEvent(timestamp=ts2, bars={"AAPL": Bar(close=155.0)}),
    ]
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()
    risk = RecordingRiskManager()

    _make_engine(bars, strategy, portfolio, execution, risk_manager=risk).run()

    assert len(risk.observed) == 2
    assert [f.ticker for f in risk.observed] == ["AAPL", "AAPL"]


def test_risk_manager_accumulates_metrics() -> None:
    """A stateful RiskManager can track running totals across fills."""

    class CostTracker:
        def __init__(self) -> None:
            self.total_commission: float = 0.0
            self.total_slippage: float = 0.0

        def evaluate_fill(self, event: FillEvent) -> None:
            self.total_commission += event.commission
            self.total_slippage += event.slippage

    ts2 = datetime(2024, 1, 2)
    bars = [
        MarketEvent(timestamp=TS, bars={"AAPL": BAR}),
        MarketEvent(timestamp=ts2, bars={"AAPL": Bar(close=155.0)}),
    ]
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()
    tracker = CostTracker()

    _make_engine(bars, strategy, portfolio, execution, risk_manager=tracker).run()

    assert tracker.total_commission == StubExecutionHandler.COMMISSION * 2
    assert tracker.total_slippage == StubExecutionHandler.SLIPPAGE * 2


def test_engine_runs_without_risk_manager() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy, portfolio, execution = StubStrategy(), StubPortfolio(), StubExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()
