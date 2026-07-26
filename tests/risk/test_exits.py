from datetime import datetime, timedelta
from typing import Literal

from backtester.core.events import Bar, MarketEvent, OrderEvent, Position
from backtester.risk.exits import PositionExitRiskManager

TS = datetime(2024, 1, 1)


class StubPositionSource:
    def __init__(self, *positions: Position) -> None:
        self._positions = {p.ticker: p for p in positions}

    def get_position(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)


def _position(
    ticker: str = "AAPL",
    quantity: int = 10,
    entry_price: float = 100.0,
    entry_date: datetime = TS,
) -> Position:
    return Position(
        ticker=ticker, quantity=quantity, entry_price=entry_price, entry_date=entry_date
    )


def _market(timestamp: datetime, ticker: str = "AAPL", close: float = 100.0) -> MarketEvent:
    return MarketEvent(timestamp=timestamp, bars={ticker: Bar(close=close)})


def _order(
    ticker: str = "AAPL",
    quantity: int = 5,
    direction: Literal["BUY", "SELL"] = "BUY",
) -> OrderEvent:
    return OrderEvent(timestamp=TS, ticker=ticker, quantity=quantity, direction=direction)


def test_stop_loss_triggers_flattening_order() -> None:
    risk = PositionExitRiskManager(StubPositionSource(_position()), stop_loss_pct=0.05)

    orders = risk.reconcile(_market(TS + timedelta(days=1), close=94.0), [])

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_take_profit_triggers_flattening_order() -> None:
    risk = PositionExitRiskManager(StubPositionSource(_position()), take_profit_pct=0.10)

    orders = risk.reconcile(_market(TS + timedelta(days=1), close=111.0), [])

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_max_holding_days_triggers_flattening_order() -> None:
    risk = PositionExitRiskManager(StubPositionSource(_position()), max_holding_days=5)

    orders = risk.reconcile(_market(TS + timedelta(days=6), close=100.0), [])

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_no_trigger_within_bounds() -> None:
    risk = PositionExitRiskManager(
        StubPositionSource(_position()),
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
        max_holding_days=5,
    )

    orders = risk.reconcile(_market(TS + timedelta(days=1), close=101.0), [])

    assert orders == []


def test_disabled_checks_via_none_never_trigger() -> None:
    risk = PositionExitRiskManager(
        StubPositionSource(_position()),
        stop_loss_pct=None,
        take_profit_pct=None,
        max_holding_days=None,
    )

    orders = risk.reconcile(_market(TS + timedelta(days=1000), close=1.0), [])

    assert orders == []


def test_missing_ticker_in_bar_is_skipped() -> None:
    risk = PositionExitRiskManager(StubPositionSource(_position(ticker="AAPL")), stop_loss_pct=0.01)

    orders = risk.reconcile(_market(TS + timedelta(days=1), ticker="MSFT", close=1.0), [])

    assert orders == []


def test_no_position_means_no_exit() -> None:
    risk = PositionExitRiskManager(StubPositionSource(), stop_loss_pct=0.01)

    orders = risk.reconcile(_market(TS + timedelta(days=1), close=1.0), [])

    assert orders == []


def test_short_position_stop_loss_direction() -> None:
    risk = PositionExitRiskManager(StubPositionSource(_position(quantity=-10)), stop_loss_pct=0.05)

    orders = risk.reconcile(_market(TS + timedelta(days=1), close=106.0), [])

    assert len(orders) == 1
    assert orders[0].direction == "BUY"
    assert orders[0].quantity == 10


def test_passes_through_unaffected_strategy_orders() -> None:
    """Orders on tickers the risk manager is not exiting flow through untouched."""
    risk = PositionExitRiskManager(StubPositionSource(_position()), stop_loss_pct=0.05)
    incoming = [_order(ticker="MSFT", direction="BUY")]

    orders = risk.reconcile(_market(TS + timedelta(days=1), close=101.0), incoming)

    assert list(orders) == incoming


def test_risk_exit_replaces_strategy_order_on_same_ticker() -> None:
    """When risk exits a ticker, any strategy order on that ticker is dropped and
    the risk exit takes its place (risk beats strategy)."""
    risk = PositionExitRiskManager(StubPositionSource(_position()), stop_loss_pct=0.05)
    incoming = [_order(ticker="AAPL", quantity=5, direction="BUY")]

    orders = risk.reconcile(_market(TS + timedelta(days=1), close=94.0), incoming)

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10
