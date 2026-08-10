from collections.abc import Sequence
from datetime import datetime

from backtester.core.events import FillEvent, OrderEvent
from backtester.execution.cost_aware import CostAwareExecutionHandler

TS = datetime(2024, 1, 1)


class FakeInner:
    """Fills every order at a fixed price, with no costs."""

    def __init__(self, price: float) -> None:
        self._price = price

    def process_order(self, event: OrderEvent) -> Sequence[FillEvent]:
        return [
            FillEvent(
                timestamp=event.timestamp,
                ticker=event.ticker,
                quantity=event.quantity,
                direction=event.direction,
                fill_price=self._price,
            )
        ]


def test_buy_pays_up_by_the_half_spread() -> None:
    handler = CostAwareExecutionHandler(FakeInner(100.0), cost_bps=10.0)

    fill = handler.process_order(
        OrderEvent(timestamp=TS, ticker="SPY", quantity=10, direction="BUY")
    )[0]

    assert fill.fill_price == 100.1  # 100 * (1 + 10/10_000)


def test_sell_receives_less_by_the_half_spread() -> None:
    handler = CostAwareExecutionHandler(FakeInner(100.0), cost_bps=10.0)

    fill = handler.process_order(
        OrderEvent(timestamp=TS, ticker="SPY", quantity=10, direction="SELL")
    )[0]

    assert fill.fill_price == 99.9


def test_zero_cost_leaves_the_inner_fill_untouched() -> None:
    handler = CostAwareExecutionHandler(FakeInner(100.0))

    fill = handler.process_order(
        OrderEvent(timestamp=TS, ticker="SPY", quantity=10, direction="BUY")
    )[0]

    assert fill.fill_price == 100.0
    assert fill.commission == 0.0
    assert fill.slippage == 0.0


def test_commission_is_charged_on_the_adjusted_notional() -> None:
    handler = CostAwareExecutionHandler(FakeInner(100.0), cost_bps=10.0, commission_bps=5.0)

    fill = handler.process_order(
        OrderEvent(timestamp=TS, ticker="SPY", quantity=10, direction="BUY")
    )[0]

    # notional = 10 * 100.1 = 1001.0; commission = 1001.0 * 5/10_000
    assert fill.commission == 1001.0 * 5 / 10_000


def test_slippage_records_the_spread_paid() -> None:
    handler = CostAwareExecutionHandler(FakeInner(100.0), cost_bps=10.0)

    fill = handler.process_order(
        OrderEvent(timestamp=TS, ticker="SPY", quantity=10, direction="BUY")
    )[0]

    assert fill.slippage == 0.1 * 10


def test_preserves_ticker_quantity_and_direction() -> None:
    handler = CostAwareExecutionHandler(FakeInner(100.0), cost_bps=10.0)

    fill = handler.process_order(
        OrderEvent(timestamp=TS, ticker="QQQ", quantity=7, direction="SELL")
    )[0]

    assert (fill.ticker, fill.quantity, fill.direction) == ("QQQ", 7, "SELL")
    assert fill.type == "FILL"
