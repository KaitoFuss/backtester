import itertools
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.axes import Axes

_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_MUTED = "#898781"
_GRID = "#e1e0d9"
_BLUE = "#2a78d6"
_RED = "#e34948"
_SERIES_COLORS = (_BLUE, "#898781", "#2aa876", "#c77d2e")


def _style_axes(ax: Axes) -> None:
    ax.set_facecolor(_SURFACE)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(_MUTED)
    ax.spines["bottom"].set_color(_MUTED)
    ax.tick_params(colors=_MUTED, labelsize=9)
    ax.grid(True, color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_mark_to_market_history(
    series: Mapping[str, Sequence[tuple[datetime, float]]], out_path: Path
) -> None:
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=_SURFACE)
    _style_axes(ax)
    for (label, history), color in zip(
        series.items(), itertools.cycle(_SERIES_COLORS), strict=False
    ):
        timestamps, values = zip(*history, strict=True)
        ax.plot(timestamps, values, color=color, linewidth=2, label=label)
    ax.set_title("Equity Curve", color=_INK, fontsize=12, loc="left")
    ax.set_ylabel("Portfolio value ($)", color=_MUTED, fontsize=9)
    if len(series) > 1:
        ax.legend(frameon=False, labelcolor=_INK, fontsize=9)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_drawdown(mark_to_market_history: Sequence[tuple[datetime, float]], out_path: Path) -> None:
    timestamps, values = zip(*mark_to_market_history, strict=True)

    peak = values[0]
    drawdowns: list[float] = []
    for value in values:
        peak = max(peak, value)
        drawdowns.append(value / peak - 1)

    fig, ax = plt.subplots(figsize=(10, 3.5), facecolor=_SURFACE)
    _style_axes(ax)
    ax.fill_between(
        timestamps,
        drawdowns,
        0,
        color=_RED,
        alpha=0.25,
        linewidth=0,
    )
    ax.plot(timestamps, drawdowns, color=_RED, linewidth=2)
    ax.set_title("Drawdown", color=_INK, fontsize=12, loc="left")
    ax.set_ylabel("Drawdown", color=_MUTED, fontsize=9)
    ax.yaxis.set_major_formatter(lambda x, _: f"{x:.0%}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
