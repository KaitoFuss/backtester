import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_FIELDS = (
    ("open", "Open"),
    ("high", "High"),
    ("low", "Low"),
    ("close", "Close"),
    ("volume", "Volume"),
)
COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume"]


def fetch_to_parquet(
    tickers: list[str],
    start: str,
    end: str,
    out_path: Path,
    downloader: Callable[..., pd.DataFrame] = yf.download,
) -> None:
    """Download OHLCV history and write it as one tidy Parquet file.

    One row per (date, ticker), sorted by date then ticker — the order
    ``FrameMarketData`` relies on to walk bars chronologically. Rows without a
    close are dropped: a ticker not yet listed (or already delisted) on a day
    has no bar at all, rather than a bar with a missing price.

    The file is overwritten wholesale, so a previous fetch with a different
    universe or date range cannot leak into this one.
    """
    data = downloader(tickers, start=start, end=end, group_by="ticker", auto_adjust=False)

    records: list[dict[str, object]] = []
    for timestamp, row in data.iterrows():
        for ticker in tickers:
            close = row.get((ticker, "Close"))
            if close is None or pd.isna(close):
                continue
            record: dict[str, object] = {
                "date": cast(pd.Timestamp, timestamp),
                "ticker": ticker,
            }
            for field, column in _FIELDS:
                value = row.get((ticker, column))
                record[field] = float(value) if value is not None and pd.notna(value) else None
            records.append(record)

    frame = pd.DataFrame.from_records(records, columns=COLUMNS)
    frame = frame.sort_values(["date", "ticker"]).reset_index(drop=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows for %d ticker(s) to %s", len(frame), len(tickers), out_path)
