import logging
from datetime import datetime


def log_trade(
    logger: logging.Logger,
    timestamp: datetime,
    action: str,
    direction: str,
    ticker: str,
    quantity: int,
    price: float,
    reason: str,
) -> None:
    """Single-line, column-aligned record of a trade decision. Used at every
    point a position opens, gets resized, closes, gets risk-exited, or gets
    liquidated, so every trade in a run reads the same way regardless of which
    component made the decision."""
    logger.info(
        "%s  %-9s %-4s %-6s qty=%6d  price=%12.4f  %s",
        timestamp,
        action,
        direction,
        ticker,
        quantity,
        price,
        reason,
    )
