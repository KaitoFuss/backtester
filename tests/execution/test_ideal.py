from datetime import datetime

from backtester.core.events import OrderEvent
from backtester.execution.ideal import IdealExecutionHandler

TS = datetime(2024, 1, 1)


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)


def test_process_order_fills_at_current_price() -> None:
    handler = IdealExecutionHandler(prices=FakePriceSource({"AAPL": 150.0}))

    fills = handler.process_order(
        OrderEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY")
    )

    assert len(fills) == 1
    fill = fills[0]
    assert fill.ticker == "AAPL"
    assert fill.quantity == 10
    assert fill.direction == "BUY"
    assert fill.fill_price == 150.0


def test_process_order_drops_order_on_missing_price() -> None:
    handler = IdealExecutionHandler(prices=FakePriceSource({}))

    fills = handler.process_order(
        OrderEvent(timestamp=TS, ticker="MSFT", quantity=5, direction="SELL")
    )

    assert fills == []
