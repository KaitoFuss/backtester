import json
from pathlib import Path

import pytest

from backtester.config import BacktestConfig, FetchDataConfig


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return path


def test_fetch_data_config_applies_defaults(tmp_path: Path) -> None:
    path = _write(
        tmp_path, {"tickers": ["AAPL", "MSFT"], "start": "2024-01-02", "end": "2024-03-31"}
    )

    config = FetchDataConfig.from_json(path)

    assert config == FetchDataConfig(
        tickers=["AAPL", "MSFT"], start="2024-01-02", end="2024-03-31", out="data/raw"
    )


def test_fetch_data_config_missing_required_field_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, {"tickers": ["AAPL"], "start": "2024-01-02"})

    with pytest.raises(TypeError):
        FetchDataConfig.from_json(path)


def test_fetch_data_config_unknown_field_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "tickers": ["AAPL"],
            "start": "2024-01-02",
            "end": "2024-03-31",
            "unexpected": "value",
        },
    )

    with pytest.raises(TypeError):
        FetchDataConfig.from_json(path)


def test_backtest_config_applies_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path, {"name": "test", "data": "data/raw"})

    config = BacktestConfig.from_json(path)

    assert config == BacktestConfig(name="test", data="data/raw")


def test_backtest_config_overrides_defaults(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "name": "test",
            "data": "data/raw",
            "tickers": ["AAPL"],
            "window": 10,
            "stop_loss_pct": 0.05,
        },
    )

    config = BacktestConfig.from_json(path)

    assert config.window == 10
    assert config.tickers == ["AAPL"]
    assert config.stop_loss_pct == 0.05


def test_backtest_config_overrides_sizing_defaults(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "name": "test",
            "data": "data/raw",
            "portfolio": "score_proportional",
            "vol_window": 10,
            "max_gross": 2.0,
            "dollar_neutral": True,
            "winsor_limit": 2.5,
        },
    )

    config = BacktestConfig.from_json(path)

    assert config.portfolio == "score_proportional"
    assert config.vol_window == 10
    assert config.max_gross == 2.0
    assert config.dollar_neutral is True
    assert config.winsor_limit == 2.5
