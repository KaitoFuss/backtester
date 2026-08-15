from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from backtester.data.frame_market_data import FrameMarketData


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    """Two full dates, then a sparse one: on 2024-01-03 only QQQ has a row, and
    that row has no volume. Both are shapes the writer really produces — a
    ticker not listed that day, and a present close with an absent field."""
    frame = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2024-01-01"),
                pd.Timestamp("2024-01-01"),
                pd.Timestamp("2024-01-02"),
                pd.Timestamp("2024-01-02"),
                pd.Timestamp("2024-01-03"),
            ],
            "ticker": ["QQQ", "SPY", "QQQ", "SPY", "QQQ"],
            "open": [99.0, 199.0, 101.0, 201.0, 103.0],
            "high": [102.0, 202.0, 103.0, 203.0, 105.0],
            "low": [98.0, 198.0, 99.0, 199.0, 102.0],
            "close": [100.0, 200.0, 102.0, 202.0, 104.0],
            "volume": [1000.0, 2000.0, 1100.0, 2100.0, None],
        }
    )
    path = tmp_path / "raw.parquet"
    frame.to_parquet(path, index=False)
    return path


def test_walks_bars_in_date_order(data_file: Path) -> None:
    data = FrameMarketData(data_file)

    first = data.get_next_bar()
    second = data.get_next_bar()
    third = data.get_next_bar()

    assert first is not None
    assert second is not None
    assert third is not None
    assert first.timestamp == datetime(2024, 1, 1)
    assert second.timestamp == datetime(2024, 1, 2)
    assert third.timestamp == datetime(2024, 1, 3)
    assert data.get_next_bar() is None


def test_bar_carries_full_ohlcv(data_file: Path) -> None:
    event = FrameMarketData(data_file).get_next_bar()

    assert event is not None
    bar = event.bars["SPY"]
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        199.0,
        202.0,
        198.0,
        200.0,
        2000.0,
    )


def test_absent_optional_field_is_none_on_the_bar(data_file: Path) -> None:
    """A null in the file must come back as ``None``, not as NaN — a NaN would
    propagate silently through any arithmetic a consumer does with it."""
    data = FrameMarketData(data_file)
    data.get_next_bar()
    data.get_next_bar()
    event = data.get_next_bar()

    assert event is not None
    bar = event.bars["QQQ"]
    assert bar.volume is None
    assert (bar.open, bar.high, bar.low, bar.close) == (103.0, 105.0, 102.0, 104.0)


def test_date_missing_a_ticker_yields_a_bar_for_the_present_one_only(data_file: Path) -> None:
    """The sparse-universe case: on a date where a ticker has no row, the
    event still fires, carrying only the tickers that do have prices."""
    data = FrameMarketData(data_file)
    data.get_next_bar()
    data.get_next_bar()
    event = data.get_next_bar()

    assert event is not None
    assert set(event.bars) == {"QQQ"}


def test_ticker_filter_excludes_everything_else(data_file: Path) -> None:
    event = FrameMarketData(data_file, tickers=["SPY"]).get_next_bar()

    assert event is not None
    assert set(event.bars) == {"SPY"}


def test_get_price_is_none_before_the_bar_is_consumed(data_file: Path) -> None:
    """The price cache must only ever reflect bars the engine has already
    seen — that is what keeps execution from reading the future."""
    data = FrameMarketData(data_file)

    assert data.get_price("SPY") is None

    data.get_next_bar()

    assert data.get_price("SPY") == 200.0


def test_get_price_tracks_the_latest_consumed_bar(data_file: Path) -> None:
    data = FrameMarketData(data_file)
    data.get_next_bar()
    data.get_next_bar()

    assert data.get_price("SPY") == 202.0


def test_golden_sequence(data_file: Path) -> None:
    """Locks the exact bar stream, since there is no old implementation left
    to diff against."""
    data = FrameMarketData(data_file)

    emitted = []
    while (event := data.get_next_bar()) is not None:
        for ticker, bar in event.bars.items():
            emitted.append((event.timestamp, ticker, bar.close))

    assert emitted == [
        (datetime(2024, 1, 1), "QQQ", 100.0),
        (datetime(2024, 1, 1), "SPY", 200.0),
        (datetime(2024, 1, 2), "QQQ", 102.0),
        (datetime(2024, 1, 2), "SPY", 202.0),
        (datetime(2024, 1, 3), "QQQ", 104.0),
    ]


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        FrameMarketData(tmp_path / "absent.parquet")
