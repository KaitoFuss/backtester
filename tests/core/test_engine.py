from collections.abc import Sequence
from datetime import datetime

from backtester.core.engine import Engine
from backtester.core.events import Bar, Event, FillEvent, MarketEvent, OrderEvent, SignalEvent

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


class RecordingStrategy:
    def __init__(self, emit: list[SignalEvent] | None = None) -> None:
        self.received: list[MarketEvent] = []
        self._emit = emit or []

    def process_market(self, event: MarketEvent) -> Sequence[SignalEvent]:
        self.received.append(event)
        return self._emit


class RecordingPortfolio:
    def __init__(self, emit_on_signal: list[OrderEvent] | None = None) -> None:
        self.signals: list[SignalEvent] = []
        self.fills: list[FillEvent] = []
        self._emit_on_signal = emit_on_signal or []

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        self.signals.append(event)
        return self._emit_on_signal

    def process_fill(self, event: FillEvent) -> Sequence[Event]:
        self.fills.append(event)
        return []


class RecordingExecutionHandler:
    def __init__(self, emit: list[FillEvent] | None = None) -> None:
        self.orders: list[OrderEvent] = []
        self._emit = emit or []

    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]:
        self.orders.append(event)
        return self._emit


def _make_engine(
    bars: list[MarketEvent],
    strategy: RecordingStrategy,
    portfolio: RecordingPortfolio,
    execution_handler: RecordingExecutionHandler,
) -> Engine:
    return Engine(
        data_handler=StubDataHandler(bars),
        strategy=strategy,
        portfolio=portfolio,
        execution_handler=execution_handler,
    )


def test_engine_routes_market_event():
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy = RecordingStrategy()
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()

    assert strategy.received == [market]
    assert portfolio.signals == []
    assert execution.orders == []


def test_engine_routes_signal_event():
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()

    assert portfolio.signals == [signal]


def test_engine_routes_order_event():
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[order])
    execution = RecordingExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()

    assert execution.orders == [order]


def test_engine_routes_fill_event():
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    fill = FillEvent(
        timestamp=TS,
        ticker="AAPL",
        quantity=100,
        direction="BUY",
        fill_price=150.0,
        commission=1.0,
        slippage=0.05,
    )
    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[order])
    execution = RecordingExecutionHandler(emit=[fill])

    _make_engine([market], strategy, portfolio, execution).run()

    assert portfolio.fills == [fill]


def test_engine_processes_multiple_bars():
    ts2 = datetime(2024, 1, 2)
    bars = [
        MarketEvent(timestamp=TS, bars={"AAPL": BAR}),
        MarketEvent(timestamp=ts2, bars={"AAPL": Bar(close=155.0)}),
    ]
    strategy = RecordingStrategy()
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine(bars, strategy, portfolio, execution).run()

    assert len(strategy.received) == 2
    assert strategy.received[0].timestamp == TS
    assert strategy.received[1].timestamp == ts2


def test_engine_stops_when_data_exhausted():
    strategy = RecordingStrategy()
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine([], strategy, portfolio, execution).run()

    assert strategy.received == []


def test_risk_manager_observes_fills():
    class RecordingRiskManager:
        def __init__(self) -> None:
            self.observed: list[FillEvent] = []

        def observe_fill(self, event: FillEvent) -> None:
            self.observed.append(event)

    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    fill = FillEvent(
        timestamp=TS,
        ticker="AAPL",
        quantity=100,
        direction="BUY",
        fill_price=150.0,
        commission=1.0,
        slippage=0.05,
    )
    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[order])
    execution = RecordingExecutionHandler(emit=[fill])
    risk = RecordingRiskManager()

    engine = Engine(
        data_handler=StubDataHandler([market]),
        strategy=strategy,
        portfolio=portfolio,
        execution_handler=execution,
        risk_manager=risk,
    )
    engine.run()

    assert risk.observed == [fill]


def test_engine_runs_without_risk_manager():
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy = RecordingStrategy()
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()
