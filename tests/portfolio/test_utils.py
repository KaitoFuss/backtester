from datetime import datetime

from backtester.core.events import FillEvent, Position
from backtester.portfolio.utils import (
    apply_fill,
    compute_equity,
    existing_gross,
    partition_signal,
    size_to_orders,
)

TS = datetime(2024, 1, 1)


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)


def test_compute_equity_sums_cash_and_position_value() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}

    assert compute_equity(1_000.0, positions, prices) == 2_000.0


def test_compute_equity_excludes_position_with_unknown_price() -> None:
    prices = FakePriceSource({})
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}

    assert compute_equity(1_000.0, positions, prices) == 1_000.0


def test_existing_gross_is_fraction_of_equity() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 50.0})
    positions = {
        "AAPL": Position(ticker="AAPL", quantity=10, entry_price=100.0, entry_date=TS),
        "MSFT": Position(ticker="MSFT", quantity=-20, entry_price=50.0, entry_date=TS),
    }

    assert existing_gross(positions, prices, equity=2_000.0) == (1_000.0 + 1_000.0) / 2_000.0


def test_existing_gross_excludes_closing_tickers() -> None:
    prices = FakePriceSource({"AAPL": 100.0, "MSFT": 50.0})
    positions = {
        "AAPL": Position(ticker="AAPL", quantity=10, entry_price=100.0, entry_date=TS),
        "MSFT": Position(ticker="MSFT", quantity=-20, entry_price=50.0, entry_date=TS),
    }

    assert existing_gross(positions, prices, equity=2_000.0, closing={"MSFT"}) == 1_000.0 / 2_000.0


def test_partition_signal_opens_candidate_above_entry_threshold() -> None:
    prices = FakePriceSource({"AAPL": 100.0})

    closes, candidates = partition_signal(
        {"AAPL": 0.5}, {}, prices, entry_threshold=0.2, exit_threshold=0.1, timestamp=TS
    )

    assert closes == []
    assert candidates == [("AAPL", 0.5, 100.0)]


def test_partition_signal_skips_candidate_below_entry_threshold() -> None:
    prices = FakePriceSource({"AAPL": 100.0})

    closes, candidates = partition_signal(
        {"AAPL": 0.1}, {}, prices, entry_threshold=0.2, exit_threshold=0.1, timestamp=TS
    )

    assert closes == []
    assert candidates == []


def test_partition_signal_closes_on_sign_flip() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}

    closes, candidates = partition_signal(
        {"AAPL": -0.5}, positions, prices, entry_threshold=0.0, exit_threshold=0.1, timestamp=TS
    )

    assert candidates == []
    assert len(closes) == 1
    assert closes[0].direction == "SELL"
    assert closes[0].quantity == 10


def test_partition_signal_closes_below_exit_threshold() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    positions = {"AAPL": Position(ticker="AAPL", quantity=-10, entry_price=90.0, entry_date=TS)}

    closes, candidates = partition_signal(
        {"AAPL": -0.05}, positions, prices, entry_threshold=0.0, exit_threshold=0.1, timestamp=TS
    )

    assert candidates == []
    assert len(closes) == 1
    assert closes[0].direction == "BUY"
    assert closes[0].quantity == 10


def test_partition_signal_holds_matching_sign_above_exit_threshold() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}

    closes, candidates = partition_signal(
        {"AAPL": 0.5}, positions, prices, entry_threshold=0.0, exit_threshold=0.1, timestamp=TS
    )

    assert closes == []
    assert candidates == []


def test_partition_signal_holds_zero_score_at_zero_exit_threshold() -> None:
    # The signed-score exit gate is strict (score * held_sign < exit_threshold),
    # so a zero score at the default exit_threshold=0.0 holds rather than closes:
    # 0 < 0 is false. A reversal to the opposite sign still closes.
    prices = FakePriceSource({"AAPL": 100.0})
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}

    closes, candidates = partition_signal(
        {"AAPL": 0.0}, positions, prices, entry_threshold=0.0, exit_threshold=0.0, timestamp=TS
    )

    assert closes == []
    assert candidates == []


def test_partition_signal_skips_unpriced_ticker() -> None:
    prices = FakePriceSource({})

    closes, candidates = partition_signal(
        {"AAPL": 0.5}, {}, prices, entry_threshold=0.0, exit_threshold=0.0, timestamp=TS
    )

    assert closes == []
    assert candidates == []


def test_size_to_orders_scales_by_weight_and_skips_zero_qty() -> None:
    candidates = [("AAPL", 1.0, 100.0), ("MSFT", -1.0, 200.0)]
    weights = {"AAPL": 0.5, "MSFT": -0.001}

    orders = size_to_orders(weights, candidates, equity=10_000.0, timestamp=TS)

    assert len(orders) == 1
    assert orders[0].ticker == "AAPL"
    assert orders[0].direction == "BUY"
    assert orders[0].quantity == round(0.5 * 10_000.0 / 100.0)


def test_size_to_orders_skips_candidate_missing_from_weights() -> None:
    candidates = [("AAPL", 1.0, 100.0)]

    orders = size_to_orders({}, candidates, equity=10_000.0, timestamp=TS)

    assert orders == []


def test_apply_fill_opens_new_position() -> None:
    positions: dict[str, Position] = {}
    fill = FillEvent(
        timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0, commission=1.0
    )

    new_cash = apply_fill(10_000.0, positions, fill)

    assert new_cash == 10_000.0 - 10 * 100.0 - 1.0
    assert positions["AAPL"] == Position(
        ticker="AAPL", quantity=10, entry_price=100.0, entry_date=TS
    )


def test_apply_fill_closes_position_to_flat() -> None:
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}
    fill = FillEvent(
        timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=95.0, commission=0.0
    )

    apply_fill(0.0, positions, fill)

    assert "AAPL" not in positions


def test_apply_fill_flip_direction_resets_cost_basis() -> None:
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}
    fill = FillEvent(
        timestamp=TS, ticker="AAPL", quantity=20, direction="SELL", fill_price=95.0, commission=0.0
    )

    apply_fill(0.0, positions, fill)

    assert positions["AAPL"] == Position(
        ticker="AAPL", quantity=-10, entry_price=95.0, entry_date=TS
    )


def test_apply_fill_adding_to_position_averages_the_cost_basis() -> None:
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}
    later = datetime(2024, 3, 8)
    fill = FillEvent(
        timestamp=later,
        ticker="AAPL",
        quantity=5,
        direction="BUY",
        fill_price=120.0,
        commission=0.0,
    )

    apply_fill(0.0, positions, fill)

    # (10 * 90 + 5 * 120) / 15, and entry_date stays at the first entry so
    # holding period still measures from when the position was established.
    assert positions["AAPL"] == Position(
        ticker="AAPL", quantity=15, entry_price=100.0, entry_date=TS
    )


def test_apply_fill_averages_cost_basis_when_adding_to_a_short() -> None:
    positions = {"AAPL": Position(ticker="AAPL", quantity=-10, entry_price=90.0, entry_date=TS)}
    fill = FillEvent(
        timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=110.0, commission=0.0
    )

    apply_fill(0.0, positions, fill)

    assert positions["AAPL"] == Position(
        ticker="AAPL", quantity=-20, entry_price=100.0, entry_date=TS
    )


def test_apply_fill_partial_reduce_keeps_the_cost_basis() -> None:
    positions = {"AAPL": Position(ticker="AAPL", quantity=10, entry_price=90.0, entry_date=TS)}
    fill = FillEvent(
        timestamp=TS, ticker="AAPL", quantity=4, direction="SELL", fill_price=120.0, commission=0.0
    )

    apply_fill(0.0, positions, fill)

    assert positions["AAPL"] == Position(ticker="AAPL", quantity=6, entry_price=90.0, entry_date=TS)
