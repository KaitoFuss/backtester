import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_FIELDS = (
    ("close", "Close"),
    ("open", "Open"),
    ("high", "High"),
    ("low", "Low"),
    ("volume", "Volume"),
)


def fetch_to_parquet(
    tickers: list[str],
    start: str,
    end: str,
    out_dir: Path,
    downloader: Callable[..., pd.DataFrame] = yf.download,
) -> None:
    """Download OHLCV history and write it out as one .parquet file per day.

    Matches the exact per-day, per-ticker-row shape ParquetMarketData reads:
    `close` required, `open`/`high`/`low`/`volume` present only when the
    downloader returned a non-NaN value for that ticker/day (e.g. a ticker
    not yet listed, or delisted, on a given day).

    Existing .parquet files in ``out_dir`` are deleted first: ``ParquetMarketData``
    reads every file in the directory regardless of which fetch wrote it, so a
    stale file from a previous fetch with a different ticker universe or date
    range would silently mix into the new one.
    """
    data = downloader(tickers, start=start, end=end, group_by="ticker", auto_adjust=False)

    out_dir.mkdir(parents=True, exist_ok=True)
    stale_files = list(out_dir.glob("*.parquet"))
    if stale_files:
        logger.info("Deleting %d existing .parquet file(s) in %s", len(stale_files), out_dir)
        for path in stale_files:
            path.unlink()

    for timestamp, row in data.iterrows():
        frame = _row_to_frame(row, tickers)
        if frame.empty:
            continue
        frame.to_parquet(out_dir / f"{timestamp:%Y-%m-%d}.parquet")


def _row_to_frame(row: "pd.Series[float]", tickers: list[str]) -> pd.DataFrame:
    records: dict[str, dict[str, float]] = {}
    for ticker in tickers:
        close = row.get((ticker, "Close"))
        if close is None or pd.isna(close):
            continue
        record = {"close": float(close)}
        for field, column in _FIELDS[1:]:
            value = row.get((ticker, column))
            if value is not None and pd.notna(value):
                record[field] = float(value)
        records[ticker] = record
    return pd.DataFrame.from_dict(records, orient="index")
