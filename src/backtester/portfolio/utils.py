import logging
import math
import statistics
from collections import deque
from collections.abc import Collection, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Literal

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, Position, Ticker
from backtester.core.trade_log import log_trade
from backtester.tracker.metrics import TRADING_DAYS_PER_YEAR

logger = logging.getLogger(__name__)


def annualized_vol(returns: deque[float] | None, window: int) -> float | None:
    """Annualized stdev of a trailing return window, or ``None`` until the
    window is full or when the sample has no dispersion."""
    if returns is None or len(returns) < window:
        return None
    stdev = statistics.stdev(returns)
    if stdev == 0:
        return None
    return stdev * math.sqrt(TRADING_DAYS_PER_YEAR)


def compute_equity(
    cash: float, positions: Mapping[Ticker, Position], price_source: PriceSource
) -> float:
    total = cash
    for ticker, position in positions.items():
        price = price_source.get_price(ticker)
        if price is None:
            logger.warning(
                "No price for held position %s (qty=%d); excluding from equity",
                ticker,
                position.quantity,
            )
            continue
        total += position.quantity * price
    return total


def existing_gross(
    positions: Mapping[Ticker, Position],
    price_source: PriceSource,
    equity: float,
    closing: Collection[Ticker] = (),
) -> float:
    """Gross exposure of held positions, as a fraction of equity. ``closing``
    excludes tickers with a close order already queued this bar — their
    ``Position`` is still in ``positions`` until the close's ``FillEvent``
    settles, but the capital they'll free is available to size this bar's new
    opens against."""
    gross = 0.0
    for ticker, position in positions.items():
        if ticker in closing:
            continue
        price = price_source.get_price(ticker)
        if price is not None:
            gross += abs(position.quantity * price / equity)
    return gross


def partition_signal(
    scores: Mapping[Ticker, float],
    positions: Mapping[Ticker, Position],
    price_source: PriceSource,
    entry_threshold: float,
    exit_threshold: float,
    timestamp: datetime,
) -> tuple[list[OrderEvent], list[tuple[Ticker, float, float]]]:
    """Split a signal's scores into close orders for positions that no longer
    qualify, and open candidates (ticker, score, price) for flat tickers whose
    score just crossed ``entry_threshold``."""
    close_orders: list[OrderEvent] = []
    open_candidates: list[tuple[Ticker, float, float]] = []
    for ticker, score in scores.items():
        price = price_source.get_price(ticker)
        if price is None:
            continue

        position = positions.get(ticker)
        current_qty = position.quantity if position else 0
        if current_qty == 0:
            if score == 0 or abs(score) < entry_threshold:
                logger.debug(
                    "%s  %s: score=%.3f below entry_threshold=%.3f, no open",
                    timestamp,
                    ticker,
                    score,
                    entry_threshold,
                )
                continue
            open_candidates.append((ticker, score, price))
        else:
            held_sign = 1 if current_qty > 0 else -1
            score_sign = (score > 0) - (score < 0)
            if score == 0:
                reason = "score is zero"
            elif score_sign != held_sign:
                reason = "score sign flipped against held position"
            elif abs(score) < exit_threshold:
                reason = f"score={score:.3f} below exit_threshold={exit_threshold:.3f}"
            else:
                reason = None
            if reason is not None:
                direction: Literal["BUY", "SELL"] = "SELL" if current_qty > 0 else "BUY"
                log_trade(
                    logger, timestamp, "CLOSE", direction, ticker, abs(current_qty), price, reason
                )
                close_orders.append(
                    OrderEvent(
                        timestamp=timestamp,
                        ticker=ticker,
                        quantity=abs(current_qty),
                        direction=direction,
                    )
                )
    return close_orders, open_candidates


def size_to_orders(
    weights: Mapping[Ticker, float],
    candidates: list[tuple[Ticker, float, float]],
    equity: float,
    timestamp: datetime,
) -> list[OrderEvent]:
    """Turn per-ticker weight-of-equity fractions into BUY/SELL orders, given
    each candidate's price. A ticker missing from ``weights`` (e.g. no vol
    estimate yet) is skipped."""
    orders: list[OrderEvent] = []
    for ticker, score, price in candidates:
        if ticker not in weights:
            logger.debug("%s  %s: no weight assigned, skipping open", timestamp, ticker)
            continue
        qty = round(weights[ticker] * equity / price)
        if qty == 0:
            logger.debug(
                "%s  %s: weight=%.5f rounds to 0 shares, skipping open",
                timestamp,
                ticker,
                weights[ticker],
            )
            continue
        direction: Literal["BUY", "SELL"] = "BUY" if qty > 0 else "SELL"
        reason = f"score={score:.3f} weight={weights[ticker]:.5f}"
        log_trade(logger, timestamp, "OPEN", direction, ticker, abs(qty), price, reason)
        orders.append(
            OrderEvent(
                timestamp=timestamp,
                ticker=ticker,
                quantity=abs(qty),
                direction=direction,
            )
        )
    return orders


def apply_fill(cash: float, positions: dict[Ticker, Position], event: FillEvent) -> float:
    signed_delta = event.quantity if event.direction == "BUY" else -event.quantity
    new_cash = cash - (signed_delta * event.fill_price + event.commission)

    prior = positions.get(event.ticker)
    prior_qty = prior.quantity if prior is not None else 0
    new_qty = prior_qty + signed_delta

    if new_qty == 0:
        positions.pop(event.ticker, None)
    elif prior is None or (prior_qty > 0) != (new_qty > 0):
        positions[event.ticker] = Position(
            ticker=event.ticker,
            quantity=new_qty,
            entry_price=event.fill_price,
            entry_date=event.timestamp,
        )
    else:
        positions[event.ticker] = replace(prior, quantity=new_qty)
    return new_cash
