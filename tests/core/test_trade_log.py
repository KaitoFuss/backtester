import logging
from datetime import datetime

import pytest

from backtester.core.trade_log import log_trade

TS = datetime(2024, 1, 2)


def test_log_trade_includes_all_fields(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.trade_log")

    with caplog.at_level(logging.INFO, logger="test.trade_log"):
        log_trade(logger, TS, "OPEN", "BUY", "AAPL", 100, 185.5, "score=1.850 weight=0.04200")

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert str(TS) in message
    assert "OPEN" in message
    assert "BUY" in message
    assert "AAPL" in message
    assert "100" in message
    assert "185.5000" in message
    assert "score=1.850 weight=0.04200" in message
