from datetime import datetime

from backtester.core.events import Bar, MarketEvent, OrderEvent, Position
from backtester.risk.leverage import LeverageRiskManager

TS = datetime(2024, 1, 1)


class FakePortfolio:
    def __init__(self, equity: float, positions: dict[str, int]) -> None:
        self._equity = equity
        self._positions = positions

    def get_position(self, ticker: str) -> Position | None:
        qty = self._positions.get(ticker)
        if not qty:
            return None
        return Position(ticker=ticker, quantity=qty, entry_price=100.0, entry_date=TS)

    def mark_to_market(self) -> float:
        return self._equity


def _bar(**prices: float) -> MarketEvent:
    return MarketEvent(timestamp=TS, bars={t: Bar(close=p) for t, p in prices.items()})


def _order(ticker: str, quantity: int, direction: str) -> OrderEvent:
    return OrderEvent(timestamp=TS, ticker=ticker, quantity=quantity, direction=direction)  # type: ignore[arg-type]


def test_passes_through_orders_within_the_ceiling() -> None:
    rm = LeverageRiskManager(FakePortfolio(equity=10_000.0, positions={}), max_gross=1.0)
    orders = [_order("AAPL", 50, "BUY")]  # 5_000 gross, ceiling 10_000

    result = rm.reconcile(_bar(AAPL=100.0), orders)

    assert list(result) == orders


def test_scales_down_opening_orders_over_the_ceiling() -> None:
    rm = LeverageRiskManager(FakePortfolio(equity=10_000.0, positions={}), max_gross=1.0)
    orders = [_order("AAPL", 200, "BUY")]  # 20_000 gross vs 10_000 ceiling

    result = rm.reconcile(_bar(AAPL=100.0), orders)

    assert len(result) == 1
    assert result[0].direction == "BUY"
    assert result[0].quantity == 100


def test_reducing_orders_are_never_scaled() -> None:
    rm = LeverageRiskManager(FakePortfolio(equity=10_000.0, positions={"AAPL": 200}), max_gross=1.0)
    close = _order("AAPL", 200, "SELL")  # closes an over-limit holding

    result = rm.reconcile(_bar(AAPL=100.0), [close])

    assert list(result) == [close]


def test_trims_held_position_when_drift_breaches_the_ceiling() -> None:
    # Held gross 20_000 vs ceiling 10_000, no incoming orders: trim to the limit.
    rm = LeverageRiskManager(FakePortfolio(equity=10_000.0, positions={"AAPL": 200}), max_gross=1.0)

    result = rm.reconcile(_bar(AAPL=100.0), [])

    assert len(result) == 1
    assert result[0].direction == "SELL"
    assert result[0].quantity == 100


def test_non_positive_equity_skips_the_cap() -> None:
    rm = LeverageRiskManager(FakePortfolio(equity=0.0, positions={}), max_gross=1.0)
    orders = [_order("AAPL", 200, "BUY")]

    result = rm.reconcile(_bar(AAPL=100.0), orders)

    assert list(result) == orders
