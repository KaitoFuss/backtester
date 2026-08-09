import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.transforms import Bbox

from backtester.config import BacktestConfig
from backtester.tracker.metrics import PerformanceMetrics, TradeMetrics
from backtester.tracker.plotting import draw_equity_curve

_A4_LANDSCAPE = (11.69, 8.27)

_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_MUTED = "#898781"
_GRID = "#e1e0d9"
_GOOD_TINT = "#e3f5e3"
_CRITICAL_TINT = "#fbe3e3"

_DIVERGING = LinearSegmentedColormap.from_list("diverging", ["#e34948", "#f0efec", "#2a78d6"])

_SUMMARY_COLUMNS = ("Annual Return", "Max DD", "Sharpe")
_SUMMARY_FORMATS = {"Annual Return": "{:.1%}", "Max DD": "{:.1%}", "Sharpe": "{:.2f}"}
_SUMMARY_LABELS = {"Annual Return": "Annual", "Max DD": "Max DD", "Sharpe": "Sharpe"}

# (display label, dataclass field, format string, True = higher is better,
#  False = lower is better, None = no winner highlight)
_PERFORMANCE_ROWS: list[tuple[str, str, str, bool | None]] = [
    ("Total return", "total_return", "{:.2%}", True),
    ("Annualized return", "annualized_return", "{:.2%}", True),
    ("Annualized vol", "annualized_vol", "{:.2%}", False),
    ("Sharpe", "sharpe", "{:.2f}", True),
    ("Max drawdown", "max_drawdown", "{:.2%}", True),
    ("Drawdown/vol", "drawdown_to_vol", "{:.2f}", False),
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


def _new_page(title: str) -> Figure:
    fig = plt.figure(figsize=_A4_LANDSCAPE, facecolor=_SURFACE)
    fig.suptitle(title, color=_INK, fontsize=15, x=0.04, y=0.955, ha="left")
    return fig


def _save_page(pdf: PdfPages, fig: Figure) -> None:
    pdf.savefig(fig, facecolor=_SURFACE)  # type: ignore[no-untyped-call]
    plt.close(fig)


def _style_table(
    ax: Axes, cell_text: list[list[str]], col_labels: list[str], **kwargs: object
) -> None:
    ax.set_axis_off()
    table = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        bbox=Bbox.from_bounds(0, 0, 1, 1),
        **kwargs,  # type: ignore[arg-type]
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    for (row, _col), cell in table.get_celld().items():
        cell.set_edgecolor(_GRID)
        cell.set_linewidth(0.6)
        if row == 0:
            cell.set_facecolor(_SURFACE)
            cell.set_text_props(color=_INK, weight="bold")
        elif cell.get_facecolor() == (1.0, 1.0, 1.0, 1.0):
            cell.set_facecolor(_SURFACE)


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


def _add_overview_page(
    pdf: PdfPages,
    histories: Mapping[str, Sequence[tuple[datetime, float]]],
    metrics: Mapping[str, PerformanceMetrics],
    trade_metrics: Mapping[str, TradeMetrics],
    correlation: pd.DataFrame,
) -> None:
    labels = list(metrics)
    fig = _new_page("Performance Overview")
    grid = fig.add_gridspec(
        1, 2, width_ratios=[1.4, 1], left=0.06, right=0.975, top=0.87, bottom=0.06, wspace=0.22
    )
    left = grid[0, 0].subgridspec(2, 1, height_ratios=[2, 1], hspace=0.16)
    ax_equity = fig.add_subplot(left[0])
    ax_drawdown = fig.add_subplot(left[1], sharex=ax_equity)
    draw_equity_curve(ax_equity, ax_drawdown, histories)
    ax_equity.tick_params(labelbottom=False)

    cell_text: list[list[str]] = []
    cell_colors: list[list[str]] = []
    for source, rows in ((metrics, _PERFORMANCE_ROWS), (trade_metrics, _TRADE_ROWS)):
        for display, field, fmt, higher_is_better in rows:
            values = {label: getattr(source[label], field) for label in labels}
            cell_text.append([display, *[fmt.format(values[label]) for label in labels]])
            cell_colors.append([_SURFACE, *_row_colors(values, labels, higher_is_better)])

    # The correlation matrix shares this page rather than owning one: at two or three
    # strategies it is a handful of cells, and a page of its own is mostly blank.
    right = grid[0, 1].subgridspec(2, 1, height_ratios=[3.4, 1], hspace=0.22)
    ax_table = fig.add_subplot(right[0])
    _style_table(
        ax_table, cell_text, ["Metric", *labels], cellColours=cell_colors, cellLoc="center"
    )

    ax_correlation = fig.add_subplot(right[1])
    if correlation.empty:
        ax_correlation.set_axis_off()
    else:
        values_2d = correlation.to_numpy(dtype=float)
        correlation_labels = [str(index) for index in correlation.index]
        _draw_heatmap(
            ax_correlation,
            values_2d,
            values_2d,
            correlation_labels,
            correlation_labels,
            ["{:.2f}"] * len(correlation),
            annotation_fontsize=9,
        )
        ax_correlation.set_title("Return Correlation", color=_INK, fontsize=11, loc="left", pad=8)
    _save_page(pdf, fig)


def _normalize_overall(data: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    scale = float(np.nanmax(np.abs(data))) if data.size and np.isfinite(data).any() else 0.0
    return data / scale if scale else np.zeros_like(data)


def _normalize_per_column(data: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    normalized = np.zeros_like(data)
    for index in range(data.shape[1]):
        column = data[:, index]
        scale = float(np.nanmax(np.abs(column))) if np.isfinite(column).any() else 0.0
        normalized[:, index] = column / scale if scale else 0.0
    return normalized


def _draw_heatmap(
    ax: Axes,
    values: npt.NDArray[np.float64],
    normalized: npt.NDArray[np.float64],
    row_labels: list[str],
    col_labels: list[str],
    formats: list[str],
    show_row_labels: bool = True,
    tick_fontsize: float = 8,
    annotation_fontsize: float = 7.5,
) -> None:
    # Months with no data must read as "no bar", not as a zero-return cell.
    ax.set_facecolor(_SURFACE)
    ax.imshow(normalized, cmap=_DIVERGING, vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(col_labels)), labels=col_labels, color=_MUTED, fontsize=tick_fontsize)
    if show_row_labels:
        ax.set_yticks(
            range(len(row_labels)), labels=row_labels, color=_MUTED, fontsize=tick_fontsize
        )
    else:
        ax.set_yticks([])
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for row in range(values.shape[0]):
        for col in range(values.shape[1]):
            value = values[row, col]
            if np.isnan(value):
                continue
            ax.text(
                col,
                row,
                formats[col].format(value),
                ha="center",
                va="center",
                color=_INK,
                fontsize=annotation_fontsize,
            )


def _add_monthly_page(pdf: PdfPages, monthly_tables: Mapping[str, pd.DataFrame]) -> None:
    tables = {label: table for label, table in monthly_tables.items() if not table.empty}
    if not tables:
        return

    fig = _new_page("Monthly Returns")
    outer = fig.add_gridspec(
        len(tables),
        1,
        height_ratios=[len(table) for table in tables.values()],
        left=0.06,
        right=0.975,
        top=0.86,
        bottom=0.07,
        hspace=0.5,
    )

    for row, (label, table) in enumerate(tables.items()):
        month_columns = [col for col in table.columns if col not in _SUMMARY_COLUMNS]
        summary_columns = [col for col in _SUMMARY_COLUMNS if col in table.columns]
        row_labels = [str(index) for index in table.index]

        inner = outer[row].subgridspec(
            1, 2, width_ratios=[len(month_columns), len(summary_columns)], wspace=0.035
        )
        ax_months = fig.add_subplot(inner[0, 0])
        month_values = table[month_columns].to_numpy(dtype=float)
        _draw_heatmap(
            ax_months,
            month_values,
            _normalize_overall(month_values),
            row_labels,
            month_columns,
            ["{:.1%}"] * len(month_columns),
        )
        ax_months.set_title(label, color=_INK, fontsize=11, loc="left", pad=8)

        # Own axes with per-column scaling: annual return / drawdown / Sharpe live on
        # different scales than a single month, and would swamp the monthly ramp.
        ax_summary = fig.add_subplot(inner[0, 1])
        summary_values = table[summary_columns].to_numpy(dtype=float)
        _draw_heatmap(
            ax_summary,
            summary_values,
            _normalize_per_column(summary_values),
            row_labels,
            [_SUMMARY_LABELS[col] for col in summary_columns],
            [_SUMMARY_FORMATS[col] for col in summary_columns],
            show_row_labels=False,
        )

    _save_page(pdf, fig)


def _add_config_page(pdf: PdfPages, config: BacktestConfig) -> None:
    fig = _new_page("Backtest Configuration")
    ax = fig.add_axes((0.06, 0.07, 0.88, 0.79))
    rows = [[key, str(value)] for key, value in asdict(config).items()]
    _style_table(ax, rows, ["Field", "Value"], cellLoc="left", colWidths=[0.35, 0.65])
    _save_page(pdf, fig)


def save_report(
    output_dir: Path,
    histories: Mapping[str, Sequence[tuple[datetime, float]]],
    metrics: Mapping[str, PerformanceMetrics],
    trade_metrics: Mapping[str, TradeMetrics],
    monthly_tables: Mapping[str, pd.DataFrame],
    correlation: pd.DataFrame,
    config: BacktestConfig,
) -> Path:
    path = _next_report_path(output_dir)
    with PdfPages(path) as pdf:
        _add_overview_page(pdf, histories, metrics, trade_metrics, correlation)
        _add_monthly_page(pdf, monthly_tables)
        _add_config_page(pdf, config)
    return path
