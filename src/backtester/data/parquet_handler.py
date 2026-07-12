from datetime import datetime
from pathlib import Path

import pandas as pd

from backtester.core.events import Bar, MarketEvent


class ParquetHandler:
    def __init__(self, data_dir: Path, tickers: list[str] | None = None) -> None:
        self._files = sorted(data_dir.glob("*.parquet"))
        self._tickers = tickers
        self._index = 0
        self._last_price: dict[str, float] = {}

    def get_next_bar(self) -> MarketEvent | None:
        if self._index >= len(self._files):
            return None
        path = self._files[self._index]
        self._index += 1
        return self._read(path)

    def get_price(self, ticker: str) -> float | None:
        return self._last_price.get(ticker)

    def _read(self, path: Path) -> MarketEvent:
        timestamp = datetime.strptime(path.stem, "%Y-%m-%d")
        df: pd.DataFrame = pd.read_parquet(path)

        if self._tickers is not None:
            df = df[df.index.isin(self._tickers)]

        cols = set(df.columns.tolist())
        bars: dict[str, Bar] = {}
        for ticker, row in df.iterrows():
            bars[str(ticker)] = Bar(
                close=float(row["close"]),
                open=float(row["open"]) if "open" in cols else None,
                high=float(row["high"]) if "high" in cols else None,
                low=float(row["low"]) if "low" in cols else None,
                volume=float(row["volume"]) if "volume" in cols else None,
            )
        self._last_price.update({ticker: bar.close for ticker, bar in bars.items()})
        return MarketEvent(timestamp=timestamp, bars=bars)
