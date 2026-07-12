from collections.abc import Sequence

from backtester.core.engine import PriceSource
from backtester.core.events import FillEvent, OrderEvent, SignalEvent, Ticker


class WeightedPortfolio:
    def __init__(self, prices: PriceSource, initial_cash: float = 100_000.0) -> None:
        self._prices = prices
        self._cash = initial_cash
        self._positions: dict[Ticker, int] = {}

    def equity(self) -> float:
        return self._cash + sum(
            qty * (self._prices.get_price(ticker) or 0.0) for ticker, qty in self._positions.items()
        )

    def process_signal(self, event: SignalEvent) -> Sequence[OrderEvent]:
        gross = sum(abs(score) for score in event.scores.values())
        equity = self.equity()

        orders: list[OrderEvent] = []
        for ticker, score in event.scores.items():
            price = self._prices.get_price(ticker)
            if price is None or score == 0 or gross == 0:
                continue

            weight = score / gross
            target_shares = round(weight * equity / price)
            delta = target_shares - self._positions.get(ticker, 0)
            if delta == 0:
                continue

            orders.append(
                OrderEvent(
                    timestamp=event.timestamp,
                    ticker=ticker,
                    quantity=abs(delta),
                    direction="BUY" if delta > 0 else "SELL",
                )
            )
        return orders

    def process_fill(self, event: FillEvent) -> Sequence[OrderEvent]:
        signed_qty = event.quantity if event.direction == "BUY" else -event.quantity
        notional = signed_qty * event.fill_price
        self._cash -= notional + event.commission
        self._positions[event.ticker] = self._positions.get(event.ticker, 0) + signed_qty
        return []
