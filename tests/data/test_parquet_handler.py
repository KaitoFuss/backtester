from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from backtester.data.parquet_handler import ParquetHandler


def _write(path: Path, data: dict[str, list[float]], index: list[str]) -> None:
    pd.DataFrame(data, index=index).to_parquet(path)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    _write(
        tmp_path / "2024-01-02.parquet",
        {"close": [150.0, 300.0], "open": [148.0, 298.0]},
        ["AAPL", "MSFT"],
    )
    _write(
        tmp_path / "2024-01-03.parquet",
        {"close": [152.0, 302.0], "open": [150.0, 300.0]},
        ["AAPL", "MSFT"],
    )
    _write(
        tmp_path / "2024-01-04.parquet",
        {"close": [155.0, 305.0]},
        ["AAPL", "MSFT"],
    )
    return tmp_path


def test_correct_number_of_events(data_dir: Path) -> None:
    events = list(ParquetHandler(data_dir))
    assert len(events) == 3


def test_events_sorted_by_date(data_dir: Path) -> None:
    events = list(ParquetHandler(data_dir))
    assert events[0].timestamp == datetime(2024, 1, 2)
    assert events[1].timestamp == datetime(2024, 1, 3)
    assert events[2].timestamp == datetime(2024, 1, 4)


def test_bars_contain_expected_tickers(data_dir: Path) -> None:
    event = next(iter(ParquetHandler(data_dir)))
    assert set(event.bars.keys()) == {"AAPL", "MSFT"}
    assert event.bars["AAPL"].close == 150.0
    assert event.bars["MSFT"].close == 300.0


def test_optional_columns_populated_when_present(data_dir: Path) -> None:
    event = next(iter(ParquetHandler(data_dir)))
    assert event.bars["AAPL"].open == 148.0
    assert event.bars["MSFT"].open == 298.0


def test_optional_columns_none_when_absent(data_dir: Path) -> None:
    events = list(ParquetHandler(data_dir))
    last = events[-1]
    assert last.bars["AAPL"].open is None
    assert last.bars["AAPL"].high is None
    assert last.bars["AAPL"].low is None
    assert last.bars["AAPL"].volume is None


def test_ticker_filtering(data_dir: Path) -> None:
    events = list(ParquetHandler(data_dir, tickers=["AAPL"]))
    for event in events:
        assert set(event.bars.keys()) == {"AAPL"}


def test_missing_ticker_in_file_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "2024-01-02.parquet", {"close": [150.0]}, ["AAPL"])
    _write(tmp_path / "2024-01-03.parquet", {"close": [300.0, 152.0]}, ["MSFT", "AAPL"])

    events = list(ParquetHandler(tmp_path, tickers=["AAPL", "MSFT"]))
    assert set(events[0].bars.keys()) == {"AAPL"}
    assert set(events[1].bars.keys()) == {"AAPL", "MSFT"}


def test_stop_iteration_when_exhausted(data_dir: Path) -> None:
    handler = ParquetHandler(data_dir)
    for _ in handler:
        pass
    with pytest.raises(StopIteration):
        next(handler)


def test_market_event_type(data_dir: Path) -> None:
    event = next(iter(ParquetHandler(data_dir)))
    assert event.type == "MARKET"
