from pathlib import Path

import pandas as pd

from backtester.data.fetch_yfinance import fetch_to_parquet
from backtester.data.parquet_market_data import ParquetMarketData

TICKERS = ["AAPL", "MSFT"]


def _fake_downloader(*_args: object, **_kwargs: object) -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    columns = pd.MultiIndex.from_tuples(
        [
            ("AAPL", "Close"),
            ("AAPL", "Open"),
            ("AAPL", "High"),
            ("AAPL", "Low"),
            ("AAPL", "Volume"),
            ("MSFT", "Close"),
            ("MSFT", "Open"),
            ("MSFT", "High"),
            ("MSFT", "Low"),
            ("MSFT", "Volume"),
        ]
    )
    return pd.DataFrame(
        [
            [150.0, 148.0, 151.0, 147.0, 1_000_000, 300.0, 298.0, 302.0, 297.0, 2_000_000],
            [152.0, 150.0, 153.0, 149.0, 1_100_000, 302.0, 300.0, 304.0, 299.0, 2_100_000],
            [float("nan")] * 5 + [305.0, 303.0, 306.0, 302.0, 2_200_000],
        ],
        index=dates,
        columns=columns,
    )


def test_writes_one_parquet_file_per_day(tmp_path: Path) -> None:
    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", tmp_path, downloader=_fake_downloader)

    written = sorted(p.name for p in tmp_path.glob("*.parquet"))
    assert written == ["2024-01-02.parquet", "2024-01-03.parquet", "2024-01-04.parquet"]


def test_round_trip_through_parquet_handler(tmp_path: Path) -> None:
    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", tmp_path, downloader=_fake_downloader)

    handler = ParquetMarketData(tmp_path)

    first = handler.get_next_bar()
    assert first is not None
    assert set(first.bars.keys()) == {"AAPL", "MSFT"}
    assert first.bars["AAPL"].close == 150.0
    assert first.bars["AAPL"].open == 148.0
    assert first.bars["MSFT"].volume == 2_000_000

    second = handler.get_next_bar()
    assert second is not None

    third = handler.get_next_bar()
    assert third is not None
    assert set(third.bars.keys()) == {"MSFT"}
    assert third.bars["MSFT"].close == 305.0

    assert handler.get_next_bar() is None


def test_stale_parquet_files_are_deleted_before_writing(tmp_path: Path) -> None:
    stale = tmp_path / "2019-06-01.parquet"
    stale.write_bytes(b"stale")
    other = tmp_path / "notes.txt"
    other.write_text("keep me")

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", tmp_path, downloader=_fake_downloader)

    assert not stale.exists()
    assert other.exists()
    written = sorted(p.name for p in tmp_path.glob("*.parquet"))
    assert written == ["2024-01-02.parquet", "2024-01-03.parquet", "2024-01-04.parquet"]


def test_downloader_receives_requested_range(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def recording_downloader(*args: object, **kwargs: object) -> pd.DataFrame:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return _fake_downloader()

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", tmp_path, downloader=recording_downloader)

    assert seen["args"] == (TICKERS,)
    assert seen["kwargs"] == {
        "start": "2024-01-02",
        "end": "2024-01-05",
        "group_by": "ticker",
        "auto_adjust": False,
    }
