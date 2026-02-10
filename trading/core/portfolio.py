"""Portfolio and position management."""

from datetime import datetime

from trading.core.models import Order, Position, Side, OrderStatus, Trade


class Portfolio:
    """Tracks cash, positions, and completed trades."""

    def __init__(self, initial_capital: float, commission_pct: float = 0.001):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_pct = commission_pct
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.orders: list[Order] = []
        self._equity_curve: list[tuple[datetime, float]] = []

    @property
    def total_equity(self) -> float:
        positions_value = sum(p.market_value for p in self.positions.values())
        return self.cash + positions_value

    @property
    def total_pnl(self) -> float:
        return self.total_equity - self.initial_capital

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return self.total_pnl / self.initial_capital

    def update_prices(self, prices: dict[str, float], timestamp: datetime):
        """Update current prices for all held positions."""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].current_price = price
        self._equity_curve.append((timestamp, self.total_equity))

    def execute_order(self, order: Order) -> bool:
        """Execute an order against the portfolio.

        Returns True if the order was filled, False otherwise.
        """
        commission = order.price * order.quantity * self.commission_pct
        order.commission = commission

        if order.side == Side.BUY:
            total_cost = order.price * order.quantity + commission
            if total_cost > self.cash:
                order.status = OrderStatus.CANCELLED
                self.orders.append(order)
                return False

            self.cash -= total_cost
            order.fill_price = order.price
            order.status = OrderStatus.FILLED

            if order.symbol in self.positions:
                pos = self.positions[order.symbol]
                total_qty = pos.quantity + order.quantity
                pos.avg_entry_price = (
                    (pos.avg_entry_price * pos.quantity + order.price * order.quantity)
                    / total_qty
                )
                pos.quantity = total_qty
            else:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=order.quantity,
                    avg_entry_price=order.price,
                    current_price=order.price,
                )

        elif order.side == Side.SELL:
            if order.symbol not in self.positions:
                order.status = OrderStatus.CANCELLED
                self.orders.append(order)
                return False

            pos = self.positions[order.symbol]
            sell_qty = min(order.quantity, pos.quantity)
            proceeds = order.price * sell_qty - commission
            self.cash += proceeds

            order.fill_price = order.price
            order.quantity = sell_qty
            order.status = OrderStatus.FILLED

            self.trades.append(Trade(
                symbol=order.symbol,
                side=Side.BUY,
                quantity=sell_qty,
                entry_price=pos.avg_entry_price,
                exit_price=order.price,
                entry_time=order.timestamp,  # approximate
                exit_time=order.timestamp,
                commission=commission,
            ))

            pos.quantity -= sell_qty
            if pos.quantity <= 0:
                del self.positions[order.symbol]

        self.orders.append(order)
        return True

    def get_equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._equity_curve)
