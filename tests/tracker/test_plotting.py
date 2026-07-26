from datetime import datetime, timedelta
from pathlib import Path

from backtester.tracker.plotting import plot_equity_curve

TS = datetime(2024, 1, 1)


def _ts(n: int) -> datetime:
    return TS + timedelta(days=n)


def test_plot_equity_curve_writes_file(tmp_path: Path) -> None:
    curve = [(_ts(0), 1_000.0), (_ts(1), 1_200.0), (_ts(2), 800.0), (_ts(3), 900.0)]
    out_path = tmp_path / "nested" / "equity_curve.png"

    plot_equity_curve({"Strategy": curve}, out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_plot_equity_curve_supports_multiple_series(tmp_path: Path) -> None:
    strategy = [(_ts(0), 1_000.0), (_ts(1), 1_100.0), (_ts(2), 1_050.0)]
    benchmark = [(_ts(0), 1_000.0), (_ts(1), 1_020.0), (_ts(2), 1_030.0)]
    out_path = tmp_path / "nested" / "equity_curve.png"

    plot_equity_curve({"Strategy": strategy, "Buy & Hold": benchmark}, out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0
