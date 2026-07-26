import re
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

from backtester.config import BacktestConfig
from backtester.tracker.metrics import PerformanceMetrics, TradeMetrics

_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_MUTED = "#898781"
_GRID = "#e1e0d9"
_GOOD_TINT = "#e3f5e3"
_CRITICAL_TINT = "#fbe3e3"

_DIVERGING = LinearSegmentedColormap.from_list("diverging", ["#e34948", "#f0efec", "#2a78d6"])

# (display label, dataclass field, format string, True = higher is better,
#  False = lower is better, None = no winner highlight)
_PERFORMANCE_ROWS: list[tuple[str, str, str, bool | None]] = [
    ("Total return", "total_return", "{:.2%}", True),
    ("Annualized return", "annualized_return", "{:.2%}", True),
    ("Annualized vol", "annualized_vol", "{:.2%}", False),
    ("Sharpe", "sharpe", "{:.2f}", True),
    ("Max drawdown", "max_drawdown", "{:.2%}", True),
]
_TRADE_ROWS: list[tuple[str, str, str, bool | None]] = [
    ("Num trades", "num_trades", "{:.0f}", None),
    ("Win rate", "win_rate", "{:.2%}", True),
    ("Avg win", "avg_win", "{:.2f}", True),
    ("Avg loss", "avg_loss", "{:.2f}", True),
    ("Risk/reward ratio", "risk_reward_ratio", "{:.2f}", True),
    ("Payoff factor", "payoff_factor", "{:.2f}", True),
    ("CPC index", "cpc_index", "{:.2f}", True),
    ("Time in market", "time_in_market", "{:.2%}", None),
    ("Turnover", "turnover", "{:.2f}", None),
]


def _next_report_path(output_dir: Path, stem: str = "report") -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"{re.escape(stem)}_(\d+)\.pdf")
    existing = [
        int(match.group(1))
        for path in output_dir.glob(f"{stem}_*.pdf")
        if (match := pattern.fullmatch(path.name))
    ]
    return output_dir / f"{stem}_{max(existing, default=0) + 1}.pdf"


def _style_axes(ax: Axes) -> None:
    ax.set_facecolor(_SURFACE)
    for spine in ax.spines.values():
        spine.set_visible(False)


def _add_metrics_page(
    pdf: PdfPages,
    metrics: Mapping[str, PerformanceMetrics],
    trade_metrics: Mapping[str, TradeMetrics],
) -> None:
    labels = list(metrics)
    fig, ax = plt.subplots(figsize=(8.5, 11), facecolor=_SURFACE)
    _style_axes(ax)
    ax.set_axis_off()
    ax.set_title("Performance Metrics", color=_INK, fontsize=14, loc="left")

    cell_text: list[list[str]] = []
    cell_colors: list[list[str]] = []
    for display, field, fmt, higher_is_better in _PERFORMANCE_ROWS:
        values = {label: getattr(metrics[label], field) for label in labels}
        cell_text.append([display, *[fmt.format(values[label]) for label in labels]])
        cell_colors.append([_SURFACE, *_row_colors(values, labels, higher_is_better)])
    for display, field, fmt, higher_is_better in _TRADE_ROWS:
        values = {label: getattr(trade_metrics[label], field) for label in labels}
        cell_text.append([display, *[fmt.format(values[label]) for label in labels]])
        cell_colors.append([_SURFACE, *_row_colors(values, labels, higher_is_better)])

    table = ax.table(
        cellText=cell_text,
        colLabels=["Metric", *labels],
        cellColours=cell_colors,
        colColours=[_SURFACE] * (len(labels) + 1),
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.6)
    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor(_GRID)
        if row == 0:
            cell.set_text_props(color=_INK, weight="bold")

    pdf.savefig(fig)  # type: ignore[no-untyped-call]
    plt.close(fig)


def _row_colors(
    values: Mapping[str, float], labels: list[str], higher_is_better: bool | None
) -> list[str]:
    if higher_is_better is None or len(labels) < 2 or len(set(values.values())) < 2:
        return [_SURFACE] * len(labels)
    best = (
        max(values, key=lambda label: values[label])
        if higher_is_better
        else min(values, key=lambda label: values[label])
    )
    return [_GOOD_TINT if label == best else _CRITICAL_TINT for label in labels]


def _add_heatmap_page(
    pdf: PdfPages,
    title: str,
    table: pd.DataFrame,
    value_columns: list[str] | None = None,
    cell_format: str = "{:.1%}",
) -> None:
    fig, ax = plt.subplots(figsize=(11, max(3, 0.6 * len(table) + 2)), facecolor=_SURFACE)
    fig.subplots_adjust(top=0.85)
    _style_axes(ax)
    ax.set_title(title, color=_INK, fontsize=14, loc="left", pad=20)

    columns = value_columns if value_columns is not None else list(table.columns)
    data = table[columns].to_numpy(dtype=float)
    max_abs = np.nanmax(np.abs(data)) if data.size and np.isfinite(data).any() else 1.0
    max_abs = max_abs or 1.0
    norm = TwoSlopeNorm(vmin=-max_abs, vcenter=0.0, vmax=max_abs)

    ax.imshow(data, cmap=_DIVERGING, norm=norm, aspect="auto")
    ax.set_xticks(range(len(columns)), labels=columns, color=_MUTED, fontsize=9)
    ax.set_yticks(range(len(table)), labels=[str(i) for i in table.index], color=_MUTED, fontsize=9)
    ax.tick_params(length=0)

    for row in range(data.shape[0]):
        for col in range(data.shape[1]):
            value = data[row, col]
            if np.isnan(value):
                continue
            ax.text(
                col,
                row,
                cell_format.format(value),
                ha="center",
                va="center",
                color=_INK,
                fontsize=8,
            )

    pdf.savefig(fig)  # type: ignore[no-untyped-call]
    plt.close(fig)


def _add_config_page(pdf: PdfPages, config: BacktestConfig) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 11), facecolor=_SURFACE)
    _style_axes(ax)
    ax.set_axis_off()
    ax.set_title("Backtest Configuration", color=_INK, fontsize=14, loc="left")

    rows = [[key, str(value)] for key, value in asdict(config).items()]
    table = ax.table(cellText=rows, colLabels=["Field", "Value"], loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.6)
    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor(_GRID)
        cell.set_facecolor(_SURFACE)
        if row == 0:
            cell.set_text_props(color=_INK, weight="bold")

    pdf.savefig(fig)  # type: ignore[no-untyped-call]
    plt.close(fig)


def save_report(
    output_dir: Path,
    metrics: Mapping[str, PerformanceMetrics],
    trade_metrics: Mapping[str, TradeMetrics],
    monthly_tables: Mapping[str, pd.DataFrame],
    correlation: pd.DataFrame,
    config: BacktestConfig,
) -> Path:
    path = _next_report_path(output_dir)
    with PdfPages(path) as pdf:
        _add_metrics_page(pdf, metrics, trade_metrics)
        for label, table in monthly_tables.items():
            if table.empty:
                continue
            month_columns = [
                col for col in table.columns if col not in ("Annual Return", "Max DD", "Sharpe")
            ]
            _add_heatmap_page(pdf, f"Monthly Returns — {label}", table, month_columns)
        if not correlation.empty:
            _add_heatmap_page(pdf, "Strategy Correlation", correlation, cell_format="{:.2f}")
        _add_config_page(pdf, config)
    return path
