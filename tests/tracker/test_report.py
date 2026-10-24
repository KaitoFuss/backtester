from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import matplotlib.pyplot as plt
import pytest
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from backtester.config import BacktestConfig
from backtester.tracker import report
from backtester.tracker.cost_curve import CostPoint
from backtester.tracker.metrics import (
    PerformanceMetrics,
    TradeMetrics,
    monthly_returns_table,
    strategy_correlation_matrix,
)
from backtester.tracker.report import new_page, save_page, save_report

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
            commission_bps=0.5,
            total_return=0.75,
            sharpe=0.38,
            max_drawdown=-0.23,
            annual_turnover=689.0,
        ),
        CostPoint(
            cost_bps=1.0,
            commission_bps=0.5,
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
            commission_bps=0.5,
            total_return=0.75,
            sharpe=1.20,
            max_drawdown=-0.23,
            annual_turnover=689.0,
        ),
        CostPoint(
            cost_bps=1.0,
            commission_bps=0.5,
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


def test_cost_sweep_page_renders_with_several_rungs(tmp_path: Path) -> None:
    """A wider ladder still renders, with a per-rung table beneath the chart."""
    metrics, trade_metrics, histories, config = _sample_inputs()
    points = [
        CostPoint(0.0, 0.5, 0.241, 0.38, -0.272, 689.2),
        CostPoint(0.25, 0.5, 0.045, 0.20, -0.290, 689.1),
        CostPoint(0.5, 0.5, -0.120, -0.05, -0.318, 689.0),
        CostPoint(1.0, 0.5, -0.376, -0.30, -0.409, 688.7),
        CostPoint(2.0, 0.5, -0.686, -0.60, -0.700, 687.7),
        CostPoint(5.0, 0.5, -0.960, -0.95, -0.961, 681.0),
    ]

    without = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        config=config,
    )
    with_sweep = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        config=config,
        cost_sweep=points,
    )

    assert with_sweep.stat().st_size > without.stat().st_size


def test_cost_sweep_page_renders_with_a_single_rung(tmp_path: Path) -> None:
    """A single-rung ladder is the degenerate range case: min == max, so the
    turnover caption must render one number, not a "689-689x" range."""
    metrics, trade_metrics, histories, config = _sample_inputs()
    points = [
        CostPoint(0.0, 0.5, 0.24, 0.38, -0.27, 689.2),
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


@dataclass(frozen=True)
class _MinimalConfig:
    """Only ``name`` plus a field ``BacktestConfig`` has no home for, proving
    ``save_report`` no longer requires the concrete ``BacktestConfig`` class
    and does not silently drop a caller's own strategy-specific fields."""

    name: str
    target_vol: float


def test_save_report_accepts_a_minimal_custom_config_with_a_foreign_field(
    tmp_path: Path,
) -> None:
    metrics, trade_metrics, histories, _ = _sample_inputs()
    config = _MinimalConfig(name="Macd Benchmark", target_vol=0.1)

    path = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        config=config,
    )

    assert path == tmp_path / "macd_benchmark_report_1.pdf"
    assert path.exists()
    assert path.stat().st_size > 0


def test_cost_sweep_page_renders_when_turnover_is_constant(tmp_path: Path) -> None:
    """All rungs sharing a turnover value is another degenerate-range case."""
    metrics, trade_metrics, histories, config = _sample_inputs()
    points = [
        CostPoint(0.0, 0.5, 0.24, 0.38, -0.27, 689.0),
        CostPoint(1.0, 0.5, -0.12, -0.09, -0.32, 689.0),
        CostPoint(2.0, 0.5, -0.40, -0.30, -0.45, 689.0),
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


class _RecordingPage:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def render(self, pdf: PdfPages) -> None:
        self._calls.append("extra")
        save_page(pdf, new_page("Extra"))


def test_extra_pages_render_before_the_config_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics, trade_metrics, histories, config = _sample_inputs()
    calls: list[str] = []
    original = report._add_config_page

    def _spy(pdf: PdfPages, config: report.ReportConfig) -> None:
        calls.append("config")
        original(pdf, config)

    monkeypatch.setattr(report, "_add_config_page", _spy)

    path = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        extra_pages=[_RecordingPage(calls), _RecordingPage(calls)],
        config=config,
    )

    assert calls == ["extra", "extra", "config"]
    assert path.stat().st_size > 0


def test_public_page_helpers_and_colors_are_exported() -> None:
    for name in (
        "ReportPage",
        "new_page",
        "save_page",
        "style_table",
        "draw_heatmap",
        "save_table_pages",
        "SURFACE",
        "INK",
        "MUTED",
        "GRID",
        "NEGATIVE",
    ):
        assert hasattr(report, name), name


def test_overview_png_can_be_turned_off(tmp_path: Path) -> None:
    metrics, trade_metrics, histories, config = _sample_inputs()

    path = save_report(
        output_dir=tmp_path,
        histories=histories,
        metrics=metrics,
        trade_metrics=trade_metrics,
        monthly_tables={label: monthly_returns_table(h) for label, h in histories.items()},
        correlation=strategy_correlation_matrix(histories),
        config=config,
        overview_png=False,
    )

    assert path.exists()
    assert list(tmp_path.glob("*.png")) == []


@dataclass(frozen=True)
class _Inner:
    lookback: int = 252
    bounds: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class _Outer:
    name: str = "Nested"
    tickers: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    initial_cash: float = 1_000_000.0
    stop_loss_pct: float | None = None
    inner: _Inner = field(default_factory=_Inner)
    optional: _Inner | None = None


def test_config_rows_flatten_nested_configs_into_sections() -> None:
    rows: list[list[str]] = []
    section_of: list[int | None] = []

    report._config_rows(asdict(_Outer()), rows, section_of)

    assert rows == [
        ["name", "Nested"],
        ["tickers", "SPY, QQQ"],
        ["initial_cash", "1,000,000.0"],
        ["stop_loss_pct", "none"],
        ["inner", ""],
        ["    lookback", "252"],
        ["    bounds", "none"],
        ["optional", "none"],
    ]
    assert section_of == [None, None, None, None, None, 4, 4, None]


def test_config_rows_show_mapping_entries_as_rows() -> None:
    rows: list[list[str]] = []
    section_of: list[int | None] = []

    report._config_rows(asdict(_Inner(bounds={"Equity": (-0.5, 0.5)})), rows, section_of)

    assert rows == [["lookback", "252"], ["bounds", ""], ["    Equity", "(-0.5, 0.5)"]]
    assert section_of == [None, None, 1]


def test_paginate_repeats_the_section_header_on_a_continuation_page() -> None:
    rows = [["top", "1"], ["section", ""], ["    a", "2"], ["    b", "3"], ["    c", "4"]]
    section_of = [None, None, 1, 1, 1]
    row = report._row_height(["x"])

    pages = report._paginate(rows, section_of, available=4 * row, header_height=row)

    assert pages == [
        [(["top", "1"], False), (["section", ""], True), (["    a", "2"], False)],
        [(["section (cont.)", ""], True), (["    b", "3"], False), (["    c", "4"], False)],
    ]


def test_paginate_never_ends_a_page_on_a_section_header() -> None:
    rows = [["top", "1"], ["other", "2"], ["section", ""], ["    a", "3"]]
    section_of = [None, None, None, 2]
    row = report._row_height(["x"])

    pages = report._paginate(rows, section_of, available=4 * row, header_height=row)

    assert pages == [
        [(["top", "1"], False), (["other", "2"], False)],
        [(["section", ""], True), (["    a", "3"], False)],
    ]


class _CountingPdf:
    def __init__(self) -> None:
        self.pages = 0

    def savefig(self, figure: Figure, **_: object) -> None:
        self.pages += 1
        plt.close(figure)


def test_save_table_pages_adds_pages_only_when_the_rows_do_not_fit() -> None:
    short, long = _CountingPdf(), _CountingPdf()
    rows = [[f"row {i}", "value"] for i in range(200)]

    for pdf, count in ((short, 5), (long, 200)):
        report.save_table_pages(
            cast(PdfPages, pdf),
            "Table",
            rows[:count],
            ["Field", "Value"],
            col_widths=[0.3, 0.7],
            wrap_widths=[None, 100],
        )

    assert short.pages == 1
    assert long.pages > 1


def test_wrap_breaks_long_cells_into_lines_instead_of_cutting_them() -> None:
    wrapped = report._wrap("SPY, " * 60, 100)

    assert wrapped.count("\n") == 2
    assert wrapped.replace("\n", " ").split() == ("SPY, " * 60).split()
