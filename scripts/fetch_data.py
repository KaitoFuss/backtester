"""Fetch daily OHLCV data from yfinance and write one Parquet file per day.

Usage:
    uv run scripts/fetch_data.py --tickers AAPL MSFT --start 2024-01-02 --end 2024-03-31 \
        --out data/raw
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backtester.data.fetch_yfinance import fetch_to_parquet


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch OHLCV data from yfinance")
    parser.add_argument("--tickers", nargs="+", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD exclusive")
    parser.add_argument("--out", default="data/raw", help="Output directory")
    args = parser.parse_args()

    out = Path(args.out)
    fetch_to_parquet(args.tickers, args.start, args.end, out)
    print(f"Done — Parquet files written to {out}")


if __name__ == "__main__":
    main()
