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


def plot_equity_curve(
    series: Mapping[str, Sequence[tuple[datetime, float]]], out_path: Path
) -> None:
    fig, (ax_equity, ax_drawdown) = plt.subplots(
        2,
        1,
        figsize=(10, 7),
        facecolor=_SURFACE,
        sharex=True,
        gridspec_kw={"height_ratios": [2, 1]},
    )
    _style_axes(ax_equity)
    _style_axes(ax_drawdown)

    for (label, history), color in zip(
        series.items(), itertools.cycle(_SERIES_COLORS), strict=False
    ):
        timestamps, values = zip(*history, strict=True)
        ax_equity.plot(timestamps, values, color=color, linewidth=2, label=label)

        peak = values[0]
        drawdowns: list[float] = []
        for value in values:
            peak = max(peak, value)
            drawdowns.append(value / peak - 1)
        ax_drawdown.plot(timestamps, drawdowns, color=color, linewidth=2)
        ax_drawdown.fill_between(timestamps, drawdowns, 0, color=color, alpha=0.15, linewidth=0)

    ax_equity.set_title("Equity Curve", color=_INK, fontsize=12, loc="left")
    ax_equity.set_ylabel("Portfolio value ($)", color=_MUTED, fontsize=9)
    if len(series) > 1:
        ax_equity.legend(frameon=False, labelcolor=_INK, fontsize=9)

    ax_drawdown.set_title("Drawdown", color=_INK, fontsize=12, loc="left")
    ax_drawdown.set_ylabel("Drawdown", color=_MUTED, fontsize=9)
    ax_drawdown.yaxis.set_major_formatter(lambda x, _: f"{x:.0%}")

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
