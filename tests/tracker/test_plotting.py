from datetime import datetime, timedelta

import matplotlib.pyplot as plt

from backtester.tracker.plotting import draw_equity_curve

TS = datetime(2024, 1, 1)


def _ts(n: int) -> datetime:
    return TS + timedelta(days=n)


def test_draw_equity_curve_plots_one_line_per_series() -> None:
    strategy = [(_ts(0), 1_000.0), (_ts(1), 1_100.0), (_ts(2), 1_050.0)]
    benchmark = [(_ts(0), 1_000.0), (_ts(1), 1_020.0), (_ts(2), 1_030.0)]
    fig, (ax_equity, ax_drawdown) = plt.subplots(2, 1)

    draw_equity_curve(ax_equity, ax_drawdown, {"Strategy": strategy, "Buy & Hold": benchmark})

    assert len(ax_equity.lines) == 2
    assert len(ax_drawdown.lines) == 2
    assert [line.get_label() for line in ax_equity.lines] == ["Strategy", "Buy & Hold"]
    plt.close(fig)


def test_draw_equity_curve_drawdown_is_zero_at_new_peaks() -> None:
    curve = [(_ts(0), 1_000.0), (_ts(1), 1_200.0), (_ts(2), 600.0)]
    fig, (ax_equity, ax_drawdown) = plt.subplots(2, 1)

    draw_equity_curve(ax_equity, ax_drawdown, {"Strategy": curve})

    drawdowns = list(ax_drawdown.lines[0].get_ydata())
    assert drawdowns[0] == 0.0
    assert drawdowns[1] == 0.0
    assert drawdowns[2] == 600.0 / 1_200.0 - 1
    plt.close(fig)


def test_draw_equity_curve_omits_legend_for_a_single_series() -> None:
    curve = [(_ts(0), 1_000.0), (_ts(1), 1_100.0)]
    fig, (ax_equity, ax_drawdown) = plt.subplots(2, 1)

    draw_equity_curve(ax_equity, ax_drawdown, {"Strategy": curve})

    assert ax_equity.get_legend() is None
    plt.close(fig)
