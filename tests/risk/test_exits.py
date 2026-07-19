from datetime import datetime, timedelta
from typing import Literal

from backtester.core.events import Bar, FillEvent, MarketEvent
from backtester.risk.exits import PositionExitRiskManager

TS = datetime(2024, 1, 1)


def _fill(
    ticker: str = "AAPL",
    quantity: int = 10,
    direction: Literal["BUY", "SELL"] = "BUY",
    price: float = 100.0,
) -> FillEvent:
    return FillEvent(
        timestamp=TS, ticker=ticker, quantity=quantity, direction=direction, fill_price=price
    )


def _market(timestamp: datetime, ticker: str = "AAPL", close: float = 100.0) -> MarketEvent:
    return MarketEvent(timestamp=timestamp, bars={ticker: Bar(close=close)})


def test_stop_loss_triggers_flattening_order() -> None:
    risk = PositionExitRiskManager(stop_loss_pct=0.05)
    risk.evaluate_fill(_fill(direction="BUY", price=100.0))

    orders = risk.evaluate_market(_market(TS + timedelta(days=1), close=94.0))

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_take_profit_triggers_flattening_order() -> None:
    risk = PositionExitRiskManager(take_profit_pct=0.10)
    risk.evaluate_fill(_fill(direction="BUY", price=100.0))

    orders = risk.evaluate_market(_market(TS + timedelta(days=1), close=111.0))

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_max_holding_days_triggers_flattening_order() -> None:
    risk = PositionExitRiskManager(max_holding_days=5)
    risk.evaluate_fill(_fill(direction="BUY", price=100.0))

    orders = risk.evaluate_market(_market(TS + timedelta(days=6), close=100.0))

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_no_trigger_within_bounds() -> None:
    risk = PositionExitRiskManager(stop_loss_pct=0.05, take_profit_pct=0.10, max_holding_days=5)
    risk.evaluate_fill(_fill(direction="BUY", price=100.0))

    orders = risk.evaluate_market(_market(TS + timedelta(days=1), close=101.0))

    assert orders == []


def test_disabled_checks_via_none_never_trigger() -> None:
    risk = PositionExitRiskManager(stop_loss_pct=None, take_profit_pct=None, max_holding_days=None)
    risk.evaluate_fill(_fill(direction="BUY", price=100.0))

    orders = risk.evaluate_market(_market(TS + timedelta(days=1000), close=1.0))

    assert orders == []


def test_missing_ticker_in_bar_is_skipped() -> None:
    risk = PositionExitRiskManager(stop_loss_pct=0.01)
    risk.evaluate_fill(_fill(ticker="AAPL", direction="BUY", price=100.0))

    orders = risk.evaluate_market(_market(TS + timedelta(days=1), ticker="MSFT", close=1.0))

    assert orders == []


def test_short_position_stop_loss_direction() -> None:
    risk = PositionExitRiskManager(stop_loss_pct=0.05)
    risk.evaluate_fill(_fill(direction="SELL", price=100.0))

    orders = risk.evaluate_market(_market(TS + timedelta(days=1), close=106.0))

    assert len(orders) == 1
    assert orders[0].direction == "BUY"
    assert orders[0].quantity == 10


def test_state_cleared_after_position_closes() -> None:
    risk = PositionExitRiskManager(stop_loss_pct=0.05)
    risk.evaluate_fill(_fill(direction="BUY", price=100.0))
    risk.evaluate_fill(_fill(direction="SELL", price=100.0))

    orders = risk.evaluate_market(_market(TS + timedelta(days=1), close=1.0))

    assert orders == []


def test_resize_keeps_original_entry_price() -> None:
    risk = PositionExitRiskManager(stop_loss_pct=0.05)
    risk.evaluate_fill(_fill(direction="BUY", price=100.0, quantity=10))
    risk.evaluate_fill(_fill(direction="BUY", price=200.0, quantity=10))

    orders = risk.evaluate_market(_market(TS + timedelta(days=1), close=94.0))

    assert len(orders) == 1
    assert orders[0].quantity == 20
