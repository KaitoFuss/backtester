"""Run a backtest config across a ladder of trading costs and report the breakeven.

Usage:
    uv run scripts/cost_sweep.py configs/zscore_rebalanced_neutral.json
"""

import argparse
import logging
from pathlib import Path

from backtester.config import BacktestConfig
from backtester.runner import verbosity_to_level
from backtester.sweep import DEFAULT_LADDER, format_sweep, run_cost_sweep


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="path to a backtest config JSON")
    parser.add_argument(
        "--ladder",
        type=float,
        nargs="+",
        default=list(DEFAULT_LADDER),
        help="cost levels in basis points",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args()

    logging.basicConfig(
        level=verbosity_to_level(args.verbose),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    config = BacktestConfig.from_json(args.config)
    print(format_sweep(run_cost_sweep(config, args.ladder)))


if __name__ == "__main__":
    main()
