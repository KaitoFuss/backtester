import logging
import math
from collections import deque
from datetime import datetime
from itertools import pairwise

import pytest

from backtester.core.events import FillEvent, SignalEvent
from backtester.portfolio.vol_weighted import VolWeightedPortfolio, annualized_vol

TS = datetime(2024, 1, 1)


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)


def test_signal_skips_tickers_with_unknown_price() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"MSFT": 1.0}))

    assert orders == []


def test_zero_score_without_position_yields_no_orders() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0}))

    assert orders == []


def test_zero_score_closes_existing_position() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0}))

    assert len(orders) == 1
    assert orders[0].ticker == "AAPL"
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_short_position_closes_with_a_buy() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0}))

    assert len(orders) == 1
    assert orders[0].direction == "BUY"
    assert orders[0].quantity == 10


def test_fill_updates_cash_and_positions() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)

    portfolio.process_fill(
        FillEvent(
            timestamp=TS,
            ticker="AAPL",
            quantity=10,
            direction="BUY",
            fill_price=100.0,
            commission=1.0,
        )
    )

    assert portfolio.mark_to_market() == 10_000.0 - 1_000.0 - 1.0 + 10 * 100.0


def test_equity_excludes_position_with_missing_price_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="MSFT", quantity=5, direction="BUY", fill_price=50.0)
    )

    with caplog.at_level(logging.WARNING):
        equity = portfolio.mark_to_market()

    expected_cash = 10_000.0 - 10 * 100.0 - 5 * 50.0
    assert equity == expected_cash + 10 * 100.0
    assert "MSFT" in caplog.text


def test_get_position_tracks_entry_price_and_date() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    entry = datetime(2024, 3, 1)

    assert portfolio.get_position("AAPL") is None

    portfolio.process_fill(
        FillEvent(timestamp=entry, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    position = portfolio.get_position("AAPL")
    assert position is not None
    assert position.quantity == 10
    assert position.entry_price == 100.0
    assert position.entry_date == entry


def test_adding_to_position_keeps_original_entry() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    first, second = datetime(2024, 3, 1), datetime(2024, 3, 8)
    portfolio.process_fill(
        FillEvent(timestamp=first, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.process_fill(
        FillEvent(timestamp=second, ticker="AAPL", quantity=5, direction="BUY", fill_price=200.0)
    )

    position = portfolio.get_position("AAPL")
    assert position is not None
    assert position.quantity == 15
    assert position.entry_price == 100.0
    assert position.entry_date == first


def test_closing_position_clears_it() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="SELL", fill_price=100.0)
    )

    assert portfolio.get_position("AAPL") is None


def test_no_resize_while_held_even_with_stronger_same_sign_score() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=100.0)

    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=1, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0}))

    assert orders == []


def test_entry_threshold_blocks_weak_signal_when_flat() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(
        price_source=prices, initial_cash=10_000.0, entry_threshold=0.5
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.4}))

    assert orders == []


def test_no_resize_while_held_with_banding_enabled() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(
        price_source=prices, initial_cash=10_000.0, entry_threshold=0.5, exit_threshold=0.2
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.9}))

    assert orders == []


def test_exit_threshold_closes_on_weak_signal() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(
        price_source=prices, initial_cash=10_000.0, entry_threshold=0.5, exit_threshold=0.2
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.1}))

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


def test_sign_flip_closes_position_even_above_exit_threshold() -> None:
    prices = FakePriceSource({"AAPL": 100.0})
    portfolio = VolWeightedPortfolio(
        price_source=prices, initial_cash=10_000.0, entry_threshold=0.5, exit_threshold=0.2
    )
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=10, direction="BUY", fill_price=100.0)
    )

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": -0.9}))

    assert len(orders) == 1
    assert orders[0].direction == "SELL"
    assert orders[0].quantity == 10


class MutablePriceSource:
    """Price source whose per-ticker price the test advances bar by bar, so the
    portfolio can accumulate a return history for its vol estimate."""

    def __init__(self, **prices: float) -> None:
        self._prices = dict(prices)

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def set(self, **prices: float) -> None:
        self._prices.update(prices)


def _warm_and_open(
    portfolio: VolWeightedPortfolio,
    prices: MutablePriceSource,
    paths: dict[str, list[float]],
    open_price: dict[str, float],
    scores: dict[str, float],
) -> dict[str, int]:
    """Feed `paths` as zero-score bars (build vol, open nothing), then one bar
    at `open_price` with real `scores`, returning ticker -> filled-in quantity.
    A path of length N needs vol_window == N for the open bar to have a ready
    vol estimate (N-1 returns from warm-up, +1 from the open bar itself)."""
    for step in zip(*paths.values(), strict=True):
        prices.set(**dict(zip(paths, step, strict=True)))
        portfolio.process_signal(SignalEvent(timestamp=TS, scores=dict.fromkeys(paths, 0.0)))
    prices.set(**open_price)
    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores=scores))
    return {o.ticker: o.quantity for o in orders}


def _sigma(price_path: list[float]) -> float:
    """Annualized vol implied by a price path, computed the same way the
    portfolio would from the log returns it observes along that path."""
    returns = [math.log(b / a) for a, b in pairwise(price_path)]
    vol = annualized_vol(deque(returns, maxlen=len(returns)), len(returns))
    assert vol is not None
    return vol


def test_open_direction_and_magnitude_follow_signed_score() -> None:
    prices = MutablePriceSource(AAPL=100.0, MSFT=100.0)
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=1_000_000.0, vol_window=2)

    for step in zip([105.0, 95.0], [105.0, 95.0], strict=True):
        prices.set(AAPL=step[0], MSFT=step[1])
        portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 0.0, "MSFT": 0.0}))
    prices.set(AAPL=100.0, MSFT=100.0)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0, "MSFT": -1.0}))

    aapl = next(o for o in orders if o.ticker == "AAPL")
    msft = next(o for o in orders if o.ticker == "MSFT")
    assert aapl.direction == "BUY"
    assert msft.direction == "SELL"
    # Same price path -> same vol, and equal |score| -> equal magnitude.
    assert aapl.quantity == msft.quantity
    assert aapl.quantity > 0


def test_open_skipped_when_vol_not_yet_ready() -> None:
    prices = MutablePriceSource(AAPL=100.0)
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0, vol_window=5)

    orders = portfolio.process_signal(SignalEvent(timestamp=TS, scores={"AAPL": 1.0}))

    assert orders == []


def test_absent_ticker_holds_existing_position() -> None:
    prices = MutablePriceSource(AAPL=100.0, MSFT=200.0)
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=10_000.0, vol_window=2)
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="MSFT", quantity=5, direction="BUY", fill_price=200.0)
    )

    qty = _warm_and_open(
        portfolio,
        prices,
        {"AAPL": [105.0, 95.0]},
        open_price={"AAPL": 100.0},
        scores={"AAPL": 1.0},
    )

    assert "MSFT" not in qty
    assert qty.get("AAPL", 0) > 0


def test_entry_threshold_opens_position_once_crossed() -> None:
    prices = MutablePriceSource(AAPL=100.0)
    portfolio = VolWeightedPortfolio(
        price_source=prices,
        initial_cash=10_000.0,
        entry_threshold=0.5,
        vol_window=2,
        target_vol=0.2,
    )

    qty = _warm_and_open(
        portfolio, prices, {"AAPL": [105.0, 95.0]}, open_price={"AAPL": 100.0}, scores={"AAPL": 0.6}
    )

    sigma = _sigma([105.0, 95.0, 100.0])
    expected_qty = round(0.6 * 0.2 / sigma * 10_000.0 / 100.0)
    assert expected_qty > 0
    assert qty["AAPL"] == expected_qty


def test_inverse_vol_gives_lower_vol_name_a_bigger_position() -> None:
    prices = MutablePriceSource(LOWV=100.0, HIGHV=100.0)
    portfolio = VolWeightedPortfolio(price_source=prices, initial_cash=1_000_000.0, vol_window=3)

    qty = _warm_and_open(
        portfolio,
        prices,
        {"LOWV": [101.0, 100.0, 101.0], "HIGHV": [120.0, 90.0, 130.0]},
        open_price={"LOWV": 100.0, "HIGHV": 100.0},
        scores={"LOWV": 1.0, "HIGHV": 1.0},
    )

    assert qty["LOWV"] > qty["HIGHV"]


def test_open_is_capped_to_available_gross_when_implied_size_is_larger() -> None:
    # A large target_vol implies far more size than a single name can have
    # under max_gross; the batch is capped down to exactly the available
    # gross (never scaled up), so qty == max_gross * equity / price.
    prices = MutablePriceSource(AAPL=100.0)
    portfolio = VolWeightedPortfolio(
        price_source=prices,
        initial_cash=1_000_000.0,
        vol_window=3,
        max_gross=1.0,
        target_vol=50.0,
    )
    qty = _warm_and_open(
        portfolio,
        prices,
        {"AAPL": [102.0, 98.0, 103.0]},
        open_price={"AAPL": 100.0},
        scores={"AAPL": 1.0},
    )
    assert qty["AAPL"] == 10_000


def test_max_gross_scales_the_capped_open_to_the_leverage_limit() -> None:
    prices = MutablePriceSource(AAPL=100.0)
    portfolio = VolWeightedPortfolio(
        price_source=prices,
        initial_cash=1_000_000.0,
        vol_window=3,
        max_gross=2.0,
        target_vol=50.0,
    )
    qty = _warm_and_open(
        portfolio,
        prices,
        {"AAPL": [102.0, 98.0, 103.0]},
        open_price={"AAPL": 100.0},
        scores={"AAPL": 1.0},
    )
    # 2x leverage on $1M equity at $100 -> 20_000 shares of gross exposure.
    assert qty["AAPL"] == 20_000


def test_held_position_shrinks_budget_for_a_new_open() -> None:
    prices = MutablePriceSource(AAPL=100.0, MSFT=100.0)
    portfolio = VolWeightedPortfolio(
        price_source=prices,
        initial_cash=10_000.0,
        max_gross=1.0,
        vol_window=2,
        target_vol=50.0,
    )
    # Hold 60 shares of AAPL = $6000 = 60% of equity; 40% gross budget remains.
    portfolio.process_fill(
        FillEvent(timestamp=TS, ticker="AAPL", quantity=60, direction="BUY", fill_price=100.0)
    )

    qty = _warm_and_open(
        portfolio, prices, {"MSFT": [105.0, 95.0]}, open_price={"MSFT": 100.0}, scores={"MSFT": 1.0}
    )

    assert qty["MSFT"] == round(0.4 * 10_000.0 / 100.0)
