import logging
from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from backtester.data.fetch_yfinance import fetch_to_parquet

TICKERS = ["AAPL", "MSFT"]


def _empty_downloader(*_args: object, **_kwargs: object) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples([("AAPL", "Close"), ("AAPL", "Open")])
    return pd.DataFrame([], columns=columns)


def _fake_downloader(*_args: object, **_kwargs: object) -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
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
            # AAPL has a close but no volume: the row survives, the field is null.
            [154.0, 153.0, 155.0, 152.0, float("nan"), 307.0, 305.0, 308.0, 304.0, 2_300_000],
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
    assert (frame["ticker"] == "AAPL").sum() == 3
    assert (frame["ticker"] == "MSFT").sum() == 4


def test_row_with_a_close_survives_a_missing_optional_field(tmp_path: Path) -> None:
    """AAPL has a close but no volume on 2024-01-05 in the fixture. Only a
    missing *close* drops the row; any other absent OHLCV field is written as
    null, which is what ``FrameMarketData`` later reads back as ``None``."""
    out = tmp_path / "raw.parquet"

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-06", out, downloader=_fake_downloader)

    frame = pd.read_parquet(out).set_index(["date", "ticker"])
    row = cast("pd.Series[float]", frame.loc[(pd.Timestamp("2024-01-05"), "AAPL")])
    assert row["close"] == 154.0
    assert row["open"] == 153.0
    assert pd.isna(row["volume"])


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


def test_directory_target_is_refused_not_destroyed(tmp_path: Path) -> None:
    """out_path must be a file path (e.g. data/raw.parquet). If it points at a
    directory, fetch_to_parquet must refuse rather than delete the directory —
    a data-fetching utility must never recursively remove a directory a caller
    pointed it at, even one that looks stale."""
    target = tmp_path / "raw.parquet"
    target.mkdir()
    sentinel = target / "keep-me.parquet"
    sentinel.write_bytes(b"precious data")

    with pytest.raises(IsADirectoryError, match="Is a directory"):
        fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", target, downloader=_fake_downloader)

    assert sentinel.exists()
    assert sentinel.read_bytes() == b"precious data"


def test_downloader_receives_requested_range(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def recording_downloader(*args: object, **kwargs: object) -> pd.DataFrame:
        seen["args"] = args
        seen["kwargs"] = kwargs
        return _fake_downloader()

    out = tmp_path / "raw.parquet"

    fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=recording_downloader)

    assert seen["args"] == (TICKERS,)
    assert seen["kwargs"] == {
        "start": "2024-01-02",
        "end": "2024-01-05",
        "group_by": "ticker",
        "auto_adjust": False,
    }


def test_summary_log_includes_date_range(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    out = tmp_path / "raw.parquet"

    with caplog.at_level(logging.INFO):
        fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=_fake_downloader)

    summary = next(r for r in caplog.records if "Wrote" in r.getMessage())
    assert "2024-01-02" in summary.getMessage()
    assert "2024-01-05" in summary.getMessage()


def test_head_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    out = tmp_path / "raw.parquet"

    with caplog.at_level(logging.INFO):
        fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=_fake_downloader)

    head_records = [r for r in caplog.records if "Head of fetched frame" in r.getMessage()]
    assert head_records
    assert "AAPL" in head_records[0].getMessage()
    assert "close" in head_records[0].getMessage()


def test_empty_frame_logs_warning_and_does_not_crash(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = tmp_path / "raw.parquet"

    with caplog.at_level(logging.INFO):
        fetch_to_parquet(TICKERS, "2024-01-02", "2024-01-05", out, downloader=_empty_downloader)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings
    assert "no rows" in warnings[0].getMessage().lower()
    assert "NaT" not in caplog.text
