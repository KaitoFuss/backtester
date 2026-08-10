from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from backtester.config import BacktestConfig
from backtester.cost_curve import CostPoint
from backtester.tracker.metrics import (
    PerformanceMetrics,
    TradeMetrics,
    monthly_returns_table,
    strategy_correlation_matrix,
)
from backtester.tracker.report import save_report

TS = datetime(2024, 1, 1)


def _history(values: list[float]) -> list[tuple[datetime, float]]:
    return [(TS + timedelta(days=i), value) for i, value in enumerate(values)]


def _sample_inputs() -> tuple[
    dict[str, PerformanceMetrics],
    dict[str, TradeMetrics],
    dict[str, list[tuple[datetime, float]]],
    BacktestConfig,
]:
    metrics = {
        "Strategy": PerformanceMetrics(0.1, 0.1, 0.1, 1.0, -0.05, 0.5),
        "Buy & Hold": PerformanceMetrics(0.05, 0.05, 0.15, 0.5, -0.1, 0.67),
    }
    trade_metrics = {
        "Strategy": TradeMetrics(10, 0.6, 100.0, -50.0, 2.0, 2.0, 1.2, 0.5, 1.5),
        "Buy & Hold": TradeMetrics(1, 1.0, 500.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0),
    }
    histories = {
        "Strategy": _history([100_000.0 + i * 100 for i in range(60)]),
        "Buy & Hold": _history([100_000.0 + i * 50 for i in range(60)]),
    }
    config = BacktestConfig(name="Zscore Momentum", data="data/raw")
    return metrics, trade_metrics, histories, config


def test_save_report_writes_report_1_pdf_on_first_run(tmp_path: Path) -> None:
    metrics, trade_metrics, histories, config = _sample_inputs()

    path = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        config=config,
    )

    assert path == tmp_path / "zscore_momentum_report_1.pdf"
    assert path.exists()
    assert path.stat().st_size > 0


def test_overview_png_is_written_next_to_the_pdf(tmp_path: Path) -> None:
    metrics, trade_metrics, histories, config = _sample_inputs()

    path = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        config=config,
    )

    png = path.with_name(f"{path.stem}_overview.png")
    assert png.is_file()
    assert png.stat().st_size > 0


def test_save_report_increments_and_never_overwrites(tmp_path: Path) -> None:
    metrics, trade_metrics, histories, config = _sample_inputs()
    monthly_tables = {label: monthly_returns_table(h) for label, h in histories.items()}
    correlation = strategy_correlation_matrix(histories)

    first = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables=monthly_tables,
        correlation=correlation,
        config=config,
    )
    second = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables=monthly_tables,
        correlation=correlation,
        config=config,
    )

    assert first == tmp_path / "zscore_momentum_report_1.pdf"
    assert second == tmp_path / "zscore_momentum_report_2.pdf"
    assert first.exists()
    assert second.exists()


def test_save_report_increments_past_gaps_in_existing_files(tmp_path: Path) -> None:
    (tmp_path / "zscore_momentum_report_1.pdf").write_bytes(b"existing")
    (tmp_path / "zscore_momentum_report_5.pdf").write_bytes(b"existing")
    metrics, trade_metrics, histories, config = _sample_inputs()

    path = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        config=config,
    )

    assert path == tmp_path / "zscore_momentum_report_6.pdf"
    assert (tmp_path / "zscore_momentum_report_1.pdf").read_bytes() == b"existing"


def test_save_report_numbers_each_name_independently(tmp_path: Path) -> None:
    metrics, trade_metrics, histories, config = _sample_inputs()
    monthly_tables = {label: monthly_returns_table(h) for label, h in histories.items()}
    correlation = strategy_correlation_matrix(histories)
    other_config = replace(config, name="Other Strategy")

    first = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables=monthly_tables,
        correlation=correlation,
        config=config,
    )
    second = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables=monthly_tables,
        correlation=correlation,
        config=other_config,
    )

    assert first == tmp_path / "zscore_momentum_report_1.pdf"
    assert second == tmp_path / "other_strategy_report_1.pdf"


def test_cost_sweep_page_adds_a_page_to_the_pdf(tmp_path: Path) -> None:
    """Same inputs, with and without a sweep: the sweep run must render more,
    which is the observable evidence the extra page was drawn."""
    metrics, trade_metrics, histories, config = _sample_inputs()
    points = [
        CostPoint(
            cost_bps=0.0,
            total_return=0.75,
            sharpe=0.38,
            max_drawdown=-0.23,
            annual_turnover=689.0,
        ),
        CostPoint(
            cost_bps=1.0,
            total_return=-0.12,
            sharpe=-0.09,
            max_drawdown=-0.32,
            annual_turnover=688.0,
        ),
    ]
    monthly_tables = {label: monthly_returns_table(h) for label, h in histories.items()}
    correlation = strategy_correlation_matrix(histories)

    without = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables=monthly_tables,
        correlation=correlation,
        config=config,
    )
    with_sweep = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables=monthly_tables,
        correlation=correlation,
        config=config,
        cost_sweep=points,
    )

    assert with_sweep.stat().st_size > without.stat().st_size


def test_cost_sweep_page_handles_a_ladder_that_never_crosses_zero(tmp_path: Path) -> None:
    """breakeven_cost returns None here; the page must still render without
    an annotation rather than crashing on the missing crossing."""
    metrics, trade_metrics, histories, config = _sample_inputs()
    points = [
        CostPoint(
            cost_bps=0.0,
            total_return=0.75,
            sharpe=1.20,
            max_drawdown=-0.23,
            annual_turnover=689.0,
        ),
        CostPoint(
            cost_bps=1.0,
            total_return=0.60,
            sharpe=0.95,
            max_drawdown=-0.25,
            annual_turnover=688.0,
        ),
    ]

    path = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        config=config,
        cost_sweep=points,
    )

    assert path.exists()
    assert path.stat().st_size > 0
