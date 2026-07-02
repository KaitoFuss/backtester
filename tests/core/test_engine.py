from collections.abc import Sequence
from datetime import datetime

from backtester.core.engine import Engine, RiskManager
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


class RecordingStrategy:
    def __init__(self, emit: list[SignalEvent] | None = None) -> None:
        self.received: list[MarketEvent] = []
        self._emit = emit or []

    def process_market(self, event: MarketEvent) -> Sequence[SignalEvent]:
        self.received.append(event)
        return self._emit


class RecordingPortfolio:
    def __init__(
        self,
        emit_on_signal: list[OrderEvent] | None = None,
        emit_on_fill: list[OrderEvent] | None = None,
    ) -> None:
        self.signals: list[SignalEvent] = []
        self.fills: list[FillEvent] = []
        self._emit_on_signal = emit_on_signal or []
        self._emit_on_fill = emit_on_fill or []

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        self.signals.append(event)
        return self._emit_on_signal

    def process_fill(self, event: FillEvent) -> Sequence[OrderEvent]:
        self.fills.append(event)
        return self._emit_on_fill


class RecordingExecutionHandler:
    def __init__(self, emit: list[FillEvent] | None = None) -> None:
        self.orders: list[OrderEvent] = []
        self._emit = emit or []

    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]:
        self.orders.append(event)
        return self._emit


class RecordingRiskManager:
    def __init__(self) -> None:
        self.observed: list[FillEvent] = []

    def observe_fill(self, event: FillEvent) -> None:
        self.observed.append(event)


def _make_engine(
    bars: list[MarketEvent],
    strategy: RecordingStrategy,
    portfolio: RecordingPortfolio,
    execution_handler: RecordingExecutionHandler,
    risk_manager: RiskManager | None = None,
) -> Engine:
    return Engine(
        data_handler=StubDataHandler(bars),
        strategy=strategy,
        portfolio=portfolio,
        execution_handler=execution_handler,
        risk_manager=risk_manager,
    )


def _fill(
    *,
    ticker: str = "AAPL",
    quantity: int = 100,
    direction: str = "BUY",
    fill_price: float = 150.0,
    commission: float = 1.0,
    slippage: float = 0.05,
) -> FillEvent:
    return FillEvent(
        timestamp=TS,
        ticker=ticker,
        quantity=quantity,
        direction=direction,  # type: ignore[arg-type]
        fill_price=fill_price,
        commission=commission,
        slippage=slippage,
    )


def test_engine_routes_market_event() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy = RecordingStrategy()
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()

    assert strategy.received == [market]
    assert portfolio.signals == []
    assert execution.orders == []


def test_engine_routes_signal_event() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()

    assert portfolio.signals == [signal]


def test_engine_routes_order_event() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[order])
    execution = RecordingExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()

    assert execution.orders == [order]


def test_engine_routes_fill_event() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    fill = _fill()
    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[order])
    execution = RecordingExecutionHandler(emit=[fill])

    _make_engine([market], strategy, portfolio, execution).run()

    assert portfolio.fills == [fill]


def test_fill_orders_dispatched() -> None:
    """Orders returned by process_fill are dispatched back through the execution handler."""
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    initial_order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    fill = _fill()
    hedge_order = OrderEvent(timestamp=TS, ticker="SPY", quantity=50, direction="SELL")

    # Hedge order produces no fill, so the chain terminates after one round-trip.
    orders_received: list[OrderEvent] = []

    class TerminatingExecutionHandler:
        def process_order(self, event: OrderEvent) -> Sequence[FillEvent]:
            orders_received.append(event)
            return [fill] if event.ticker == "AAPL" else []

    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[initial_order], emit_on_fill=[hedge_order])

    Engine(
        data_handler=StubDataHandler([market]),
        strategy=strategy,
        portfolio=portfolio,
        execution_handler=TerminatingExecutionHandler(),
    ).run()

    assert orders_received == [initial_order, hedge_order]


def test_engine_processes_multiple_bars() -> None:
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


def test_engine_stops_when_data_exhausted() -> None:
    strategy = RecordingStrategy()
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine([], strategy, portfolio, execution).run()

    assert strategy.received == []


def test_risk_manager_observes_fills() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    fill = _fill()
    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[order])
    execution = RecordingExecutionHandler(emit=[fill])
    risk = RecordingRiskManager()

    _make_engine([market], strategy, portfolio, execution, risk_manager=risk).run()

    assert risk.observed == [fill]


def test_risk_manager_observes_fills_across_bars() -> None:
    """RiskManager receives one observe_fill call per bar (one trade each)."""
    ts2 = datetime(2024, 1, 2)
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    fill1 = _fill(commission=1.0)
    fill2 = _fill(fill_price=155.0, commission=1.25)

    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[order])
    execution = RecordingExecutionHandler(emit=[fill1, fill2])
    risk = RecordingRiskManager()

    bars = [
        MarketEvent(timestamp=TS, bars={"AAPL": BAR}),
        MarketEvent(timestamp=ts2, bars={"AAPL": Bar(close=155.0)}),
    ]
    _make_engine(bars, strategy, portfolio, execution, risk_manager=risk).run()

    assert risk.observed == [fill1, fill2, fill1, fill2]


def test_risk_manager_accumulates_metrics() -> None:
    """A stateful RiskManager can track running totals across fills."""

    class CostTracker:
        def __init__(self) -> None:
            self.total_commission: float = 0.0
            self.total_slippage: float = 0.0

        def observe_fill(self, event: FillEvent) -> None:
            self.total_commission += event.commission
            self.total_slippage += event.slippage

    ts2 = datetime(2024, 1, 2)
    signal = SignalEvent(timestamp=TS, scores={"AAPL": 0.9})
    order = OrderEvent(timestamp=TS, ticker="AAPL", quantity=100, direction="BUY")
    fill1 = _fill(commission=1.0, slippage=0.05)
    fill2 = _fill(fill_price=155.0, commission=1.25, slippage=0.10)

    strategy = RecordingStrategy(emit=[signal])
    portfolio = RecordingPortfolio(emit_on_signal=[order])
    execution = RecordingExecutionHandler(emit=[fill1, fill2])
    tracker = CostTracker()

    bars = [
        MarketEvent(timestamp=TS, bars={"AAPL": BAR}),
        MarketEvent(timestamp=ts2, bars={"AAPL": Bar(close=155.0)}),
    ]
    _make_engine(bars, strategy, portfolio, execution, risk_manager=tracker).run()

    assert tracker.total_commission == (1.0 + 1.25) * 2
    assert tracker.total_slippage == (0.05 + 0.10) * 2


def test_engine_runs_without_risk_manager() -> None:
    market = MarketEvent(timestamp=TS, bars={"AAPL": BAR})
    strategy = RecordingStrategy()
    portfolio = RecordingPortfolio()
    execution = RecordingExecutionHandler()

    _make_engine([market], strategy, portfolio, execution).run()
