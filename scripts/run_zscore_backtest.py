"""Run the z-score mean-reversion strategy against locally fetched Parquet data,
alongside a buy-and-hold benchmark, and write a performance report PDF.

Usage:
    uv run scripts/run_zscore_backtest.py configs/zscore_backtest.json -v

The strategy leg's portfolio comes from `config.portfolio`; the benchmark leg is
always equal-weight buy-and-hold. Three configs run the same signal and universe
through each sizing model, so their reports are directly comparable:

    configs/zscore_backtest.json           inverse_vol, band trading + risk exits
    configs/zscore_rebalanced.json         score_proportional, rebalanced every bar
    configs/zscore_rebalanced_neutral.json score_proportional + dollar_neutral
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from backtester.config import BacktestConfig
from backtester.runner import (
    run_strategy_and_benchmark,
    verbosity_to_level,
    warn_if_risk_exits_fight_rebalancing,
)
from backtester.sweep import run_cost_sweep
from backtester.tracker.metrics import monthly_returns_table, strategy_correlation_matrix
from backtester.tracker.report import save_report

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="path to a backtest config JSON")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="-v for the trade blotter (INFO), -vv for the full numeric trail (DEBUG)",
    )
    parser.add_argument(
        "--cost-sweep",
        action="store_true",
        help="also run the cost ladder and add a sensitivity page to the report",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=verbosity_to_level(args.verbose),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    config = BacktestConfig.from_json(args.config)
    warn_if_risk_exits_fight_rebalancing(config)

    logger.info("Running backtest on %s …", config.data)
    trackers = run_strategy_and_benchmark(config)
    histories = {label: tracker.mark_to_market_history for label, tracker in trackers.items()}

    sweep = run_cost_sweep(config=config) if args.cost_sweep else None

    report_path = save_report(
        output_dir=Path(config.output_dir) / "zscore_ma",
        histories=histories,
        metrics={label: tracker.metrics() for label, tracker in trackers.items()},
        trade_metrics={label: tracker.trade_metrics() for label, tracker in trackers.items()},
        monthly_tables={
            label: monthly_returns_table(history) for label, history in histories.items()
        },
        correlation=strategy_correlation_matrix(histories),
        cost_sweep=sweep,
        config=config,
    )
    # warning, not info: the default level is WARNING, so a log call here
    # would make the report path invisible — and the user always needs it.
    logger.warning("Report written to %s", report_path)


if __name__ == "__main__":
    main()
