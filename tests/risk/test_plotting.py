from datetime import datetime, timedelta
from pathlib import Path

from backtester.risk.plotting import plot_drawdown, plot_mark_to_market_history

TS = datetime(2024, 1, 1)


def _ts(n: int) -> datetime:
    return TS + timedelta(days=n)


def test_plot_mark_to_market_history_writes_file(tmp_path: Path) -> None:
    curve = [(_ts(0), 1_000.0), (_ts(1), 1_100.0), (_ts(2), 1_050.0)]
    out_path = tmp_path / "nested" / "equity_curve.png"

    plot_mark_to_market_history(curve, out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_plot_drawdown_writes_file(tmp_path: Path) -> None:
    curve = [(_ts(0), 1_000.0), (_ts(1), 1_200.0), (_ts(2), 800.0), (_ts(3), 900.0)]
    out_path = tmp_path / "nested" / "drawdown.png"

    plot_drawdown(curve, out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0
