from datetime import datetime, timedelta
from pathlib import Path

from backtester.config import BacktestConfig
from backtester.tracker.metrics import PerformanceMetrics, TradeMetrics
from backtester.tracker.report import save_report
from backtester.tracker.reporting import monthly_returns_table, strategy_correlation_matrix

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
        "Strategy": PerformanceMetrics(0.1, 0.1, 0.1, 1.0, -0.05),
        "Buy & Hold": PerformanceMetrics(0.05, 0.05, 0.15, 0.5, -0.1),
    }
    trade_metrics = {
        "Strategy": TradeMetrics(10, 0.6, 100.0, -50.0, 2.0, 2.0, 1.2, 0.5, 1.5),
        "Buy & Hold": TradeMetrics(1, 1.0, 500.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0),
    }
    histories = {
        "Strategy": _history([100_000.0 + i * 100 for i in range(60)]),
        "Buy & Hold": _history([100_000.0 + i * 50 for i in range(60)]),
    }
    config = BacktestConfig(data="data/raw")
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

    assert path == tmp_path / "report_1.pdf"
    assert path.exists()
    assert path.stat().st_size > 0


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

    assert first == tmp_path / "report_1.pdf"
    assert second == tmp_path / "report_2.pdf"
    assert first.exists()
    assert second.exists()


def test_save_report_increments_past_gaps_in_existing_files(tmp_path: Path) -> None:
    (tmp_path / "report_1.pdf").write_bytes(b"existing")
    (tmp_path / "report_5.pdf").write_bytes(b"existing")
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

    assert path == tmp_path / "report_6.pdf"
    assert (tmp_path / "report_1.pdf").read_bytes() == b"existing"
