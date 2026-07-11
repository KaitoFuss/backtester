"""Smoke-test the backtesting engine against locally fetched Parquet data.

Usage:
    uv run scripts/run_backtest.py --data data/raw --tickers AAPL MSFT

Stubs wired up here:
  - PassthroughStrategy  : scores every ticker 1.0 on each bar
  - LoggingPortfolio     : places a BUY 1 order per ticker; prints each fill
  - IdealExecutionHandler: fills at close price, zero commission
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from backtester.core.engine import Engine
from backtester.core.events import FillEvent, MarketEvent, OrderEvent, SignalEvent
from backtester.data.parquet_handler import ParquetHandler


class PassthroughStrategy:
    def process_market(self, event: MarketEvent) -> list[SignalEvent]:
        return [SignalEvent(timestamp=event.timestamp, scores=dict.fromkeys(event.bars, 1.0))]


class LoggingPortfolio:
    def process_signal(self, event: SignalEvent) -> list[OrderEvent]:
        return [
            OrderEvent(timestamp=event.timestamp, ticker=ticker, quantity=1, direction="BUY")
            for ticker in event.scores
        ]

    def process_fill(self, event: FillEvent) -> Sequence[OrderEvent]:
        print(
            f"FILL  {event.timestamp:%Y-%m-%d}  {event.ticker:<6}"
            f"  {event.direction}  qty={event.quantity}  @{event.fill_price:.2f}"
        )
        return []


class IdealExecutionHandler:
    def __init__(self) -> None:
        self._last_bars: dict[str, float] = {}

    def set_bars(self, event: MarketEvent) -> None:
        self._last_bars = {ticker: bar.close for ticker, bar in event.bars.items()}

    def process_order(self, event: OrderEvent) -> list[FillEvent]:
        price = self._last_bars.get(event.ticker)
        if price is None:
            print(f"WARN: no price for {event.ticker} on {event.timestamp:%Y-%m-%d}, order dropped")
            return []
        return [
            FillEvent(
                timestamp=event.timestamp,
                ticker=event.ticker,
                quantity=event.quantity,
                direction=event.direction,
                fill_price=price,
            )
        ]


class BridgedDataHandler:
    """Wraps ParquetHandler and keeps IdealExecutionHandler's price cache in sync."""

    def __init__(self, inner: ParquetHandler, execution: IdealExecutionHandler) -> None:
        self._inner = inner
        self._execution = execution

    def get_next_bar(self) -> MarketEvent | None:
        bar = self._inner.get_next_bar()
        if bar is not None:
            self._execution.set_bars(bar)
        return bar


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtester smoke test")
    parser.add_argument("--data", required=True, help="Directory of daily Parquet files")
    parser.add_argument("--tickers", nargs="+", default=None)
    args = parser.parse_args()

    raw_handler = ParquetHandler(Path(args.data), tickers=args.tickers)
    execution = IdealExecutionHandler()
    data_handler = BridgedDataHandler(raw_handler, execution)

    engine = Engine(
        data_handler=data_handler,
        strategy=PassthroughStrategy(),
        portfolio=LoggingPortfolio(),
        execution_handler=execution,
    )

    print(f"Running backtest on {args.data} …")
    engine.run()
    print("Done.")


if __name__ == "__main__":
    main()
