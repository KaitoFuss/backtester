import logging
from pathlib import Path
from typing import cast

import pandas as pd

from backtester.core.events import Bar, MarketEvent

logger = logging.getLogger(__name__)

_OPTIONAL = ("open", "high", "low", "volume")


class FrameMarketData:
    """Reads one tidy Parquet file of daily bars and doubles as a price lookup.

    The whole history is loaded and grouped by date once at construction, so a
    run costs one file open rather than one per trading day.

    A single instance is meant to be wired into both the `Engine` (as
    `DataHandler`) and any consumer needing current prices (as `PriceSource`,
    e.g. `Portfolio`/`ExecutionHandler`) — `get_price` reads a cache populated
    by `get_next_bar`, so it only ever reflects bars the engine loop has
    already consumed. That is what keeps execution from reading ahead.
    """

    def __init__(self, path: Path, tickers: list[str] | None = None) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"no market data file at {path}")

        frame = pd.read_parquet(path)
        if tickers is not None:
            frame = frame[frame["ticker"].isin(tickers)]
        frame = frame.sort_values(["date", "ticker"])

        self._events: list[MarketEvent] = [
            MarketEvent(
                timestamp=cast(pd.Timestamp, timestamp).to_pydatetime(),
                bars=self._bars(group),
            )
            for timestamp, group in frame.groupby("date", sort=True)
        ]
        self._index = 0
        self._last_price: dict[str, float] = {}
        logger.info("Loaded %d bar(s) from %s", len(self._events), path)

    @staticmethod
    def _bars(group: pd.DataFrame) -> dict[str, Bar]:
        bars: dict[str, Bar] = {}
        for record in group.to_dict("records"):
            optional = {
                field: float(record[field])
                for field in _OPTIONAL
                if record.get(field) is not None and pd.notna(record[field])
            }
            bars[str(record["ticker"])] = Bar(close=float(record["close"]), **optional)
        return bars

    def get_next_bar(self) -> MarketEvent | None:
        if self._index >= len(self._events):
            return None
        event = self._events[self._index]
        self._index += 1
        for ticker, bar in event.bars.items():
            self._last_price[ticker] = bar.close
        return event

    def get_price(self, ticker: str) -> float | None:
        return self._last_price.get(ticker)
