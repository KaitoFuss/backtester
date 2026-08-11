from pathlib import Path
from typing import cast

import pandas as pd

from backtester.data.fetch_yfinance import fetch_to_parquet

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


def test_writes_one_tidy_file(tmp_path: Path) -> None:
    out = tmp_path / "raw.parquet"

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=_fake_downloader)

    assert out.is_file()
    frame = pd.read_parquet(out)
    assert list(frame.columns) == ["date", "ticker", "open", "high", "low", "close", "volume"]
    assert set(frame["ticker"]) == {"AAPL", "MSFT"}


def test_rows_are_sorted_by_date_then_ticker(tmp_path: Path) -> None:
    out = tmp_path / "raw.parquet"

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=_fake_downloader)

    frame = pd.read_parquet(out)
    assert frame.equals(frame.sort_values(["date", "ticker"]).reset_index(drop=True))


def test_missing_close_rows_are_dropped(tmp_path: Path) -> None:
    """AAPL has no data on 2024-01-04 in the fixture. A ticker not listed on a
    given day gets no row at all, rather than a row with a missing price."""
    out = tmp_path / "raw.parquet"

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=_fake_downloader)

    frame = pd.read_parquet(out)
    assert frame["close"].notna().all()
    assert (frame["ticker"] == "AAPL").sum() == 2
    assert (frame["ticker"] == "MSFT").sum() == 3


def test_carries_full_ohlcv(tmp_path: Path) -> None:
    out = tmp_path / "raw.parquet"

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=_fake_downloader)

    frame = pd.read_parquet(out).set_index(["date", "ticker"])
    row = cast("pd.Series[float]", frame.loc[(pd.Timestamp("2024-01-02"), "AAPL")])
    assert (row["open"], row["high"], row["low"], row["close"], row["volume"]) == (
        148.0,
        151.0,
        147.0,
        150.0,
        1_000_000.0,
    )


def test_overwrites_a_stale_file(tmp_path: Path) -> None:
    out = tmp_path / "raw.parquet"
    out.write_bytes(b"stale")

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=_fake_downloader)

    assert set(pd.read_parquet(out)["ticker"]) == {"AAPL", "MSFT"}


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
