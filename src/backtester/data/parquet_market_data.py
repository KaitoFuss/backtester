from datetime import datetime
from pathlib import Path

import pandas as pd

from backtester.core.events import Bar, MarketEvent


class ParquetMarketData:
    """Reads daily Parquet bars and doubles as a shared price lookup.

    A single instance is meant to be wired into both the `Engine` (as
    `DataHandler`) and any consumers that need current prices (as
    `PriceSource`, e.g. `Portfolio`/`ExecutionHandler`) — `get_price`
    reads a cache populated by `get_next_bar`, so it only reflects bars
    already consumed by the engine loop.
    """

    def __init__(self, data_dir: Path, tickers: list[str] | None = None) -> None:
        self._files = [
            (self._parse_timestamp(path), path) for path in sorted(data_dir.glob("*.parquet"))
        ]
        self._tickers = tickers
        self._index = 0
        self._last_price: dict[str, float] = {}

    @staticmethod
    def _parse_timestamp(path: Path) -> datetime:
        try:
            return datetime.strptime(path.stem, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"Parquet file {path} is not named like a trading day; expected YYYY-MM-DD.parquet"
            ) from exc

    def get_next_bar(self) -> MarketEvent | None:
        if self._index >= len(self._files):
            return None
        timestamp, path = self._files[self._index]
        self._index += 1
        return self._read(timestamp, path)

    def get_price(self, ticker: str) -> float | None:
        return self._last_price.get(ticker)

    def _read(self, timestamp: datetime, path: Path) -> MarketEvent:
        df: pd.DataFrame = pd.read_parquet(path)

        if self._tickers is not None:
            df = df[df.index.isin(self._tickers)]

        cols = set(df.columns.tolist())
        bars: dict[str, Bar] = {}
        for ticker, row in df.iterrows():
            bar = Bar(
                close=float(row["close"]),
                open=float(row["open"]) if "open" in cols else None,
                high=float(row["high"]) if "high" in cols else None,
                low=float(row["low"]) if "low" in cols else None,
                volume=float(row["volume"]) if "volume" in cols else None,
            )
            bars[str(ticker)] = bar
            self._last_price[str(ticker)] = bar.close
        return MarketEvent(timestamp=timestamp, bars=bars)
