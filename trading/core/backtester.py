"""Backtesting engine."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from trading.core.models import Order, Side, Signal
from trading.core.portfolio import Portfolio
from trading.strategies.base import Strategy


@dataclass
class BacktestResult:
    """Summary statistics from a backtest run."""
    strategy_name: str
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_equity: float
    total_return_pct: float
    num_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_trade_pnl: float
    max_drawdown_pct: float
    sharpe_ratio: float
    equity_curve: list[tuple[datetime, float]]
    trades: list

    def summary(self) -> str:
        lines = [
            f"{'='*50}",
            f"  Backtest Results: {self.strategy_name}",
            f"  Symbol: {self.symbol}",
            f"{'='*50}",
            f"  Period:          {self.start_date:%Y-%m-%d} to {self.end_date:%Y-%m-%d}",
            f"  Initial Capital: ${self.initial_capital:,.2f}",
            f"  Final Equity:    ${self.final_equity:,.2f}",
            f"  Total Return:    {self.total_return_pct:+.2%}",
            f"  Num Trades:      {self.num_trades}",
            f"  Win Rate:        {self.win_rate:.1%}",
            f"  Avg Trade P&L:   ${self.avg_trade_pnl:,.2f}",
            f"  Max Drawdown:    {self.max_drawdown_pct:.2%}",
            f"  Sharpe Ratio:    {self.sharpe_ratio:.2f}",
            f"{'='*50}",
        ]
        return "\n".join(lines)


class Backtester:
    """Runs a strategy against historical data and computes performance metrics."""

    def __init__(
        self,
        strategy: Strategy,
        initial_capital: float = 100_000.0,
        commission_pct: float = 0.001,
        max_position_pct: float = 0.10,
        stop_loss_pct: float = 0.05,
        take_profit_pct: float = 0.15,
    ):
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.max_position_pct = max_position_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def run(self, symbol: str, data: pd.DataFrame) -> BacktestResult:
        """Run the backtest for a single symbol.

        Args:
            symbol: Ticker symbol.
            data: OHLCV DataFrame with DatetimeIndex.

        Returns:
            BacktestResult with performance metrics.
        """
        portfolio = Portfolio(self.initial_capital, self.commission_pct)

        # Generate signals from the strategy
        signals = self.strategy.generate_signals(data)
        # Tag signals with symbol
        for sig in signals:
            sig.symbol = symbol

        # Build a lookup: date -> signal
        signal_map: dict[datetime, Signal] = {}
        for sig in signals:
            signal_map[sig.timestamp] = sig

        # Walk through each bar
        for timestamp, row in data.iterrows():
            price = row["Close"]

            # Update portfolio prices
            portfolio.update_prices({symbol: price}, timestamp)

            # Check stop-loss / take-profit on existing position
            if symbol in portfolio.positions:
                pos = portfolio.positions[symbol]
                pnl_pct = pos.unrealized_pnl_pct

                if pnl_pct <= -self.stop_loss_pct:
                    order = Order(
                        symbol=symbol,
                        side=Side.SELL,
                        quantity=pos.quantity,
                        price=price,
                        timestamp=timestamp,
                    )
                    portfolio.execute_order(order)
                    continue

                if pnl_pct >= self.take_profit_pct:
                    order = Order(
                        symbol=symbol,
                        side=Side.SELL,
                        quantity=pos.quantity,
                        price=price,
                        timestamp=timestamp,
                    )
                    portfolio.execute_order(order)
                    continue

            # Process signal if one exists for this bar
            if timestamp in signal_map:
                sig = signal_map[timestamp]
                self._process_signal(portfolio, sig, price, timestamp)

        # Close any remaining position at the last price
        if symbol in portfolio.positions:
            last_price = data["Close"].iloc[-1]
            last_time = data.index[-1]
            pos = portfolio.positions[symbol]
            order = Order(
                symbol=symbol,
                side=Side.SELL,
                quantity=pos.quantity,
                price=last_price,
                timestamp=last_time,
            )
            portfolio.execute_order(order)

        return self._build_result(symbol, data, portfolio)

    def _process_signal(self, portfolio: Portfolio, sig: Signal, price: float, timestamp):
        """Convert a signal into an order and execute it."""
        if sig.side == Side.BUY and sig.symbol not in portfolio.positions:
            max_spend = portfolio.cash * self.max_position_pct
            quantity = int(max_spend / price)
            if quantity > 0:
                order = Order(
                    symbol=sig.symbol,
                    side=Side.BUY,
                    quantity=quantity,
                    price=price,
                    timestamp=timestamp,
                )
                portfolio.execute_order(order)

        elif sig.side == Side.SELL and sig.symbol in portfolio.positions:
            pos = portfolio.positions[sig.symbol]
            order = Order(
                symbol=sig.symbol,
                side=Side.SELL,
                quantity=pos.quantity,
                price=price,
                timestamp=timestamp,
            )
            portfolio.execute_order(order)

    def _build_result(self, symbol: str, data: pd.DataFrame, portfolio: Portfolio) -> BacktestResult:
        """Compute final metrics from the portfolio state."""
        trades = portfolio.trades
        num_trades = len(trades)
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl <= 0]
        avg_pnl = np.mean([t.pnl for t in trades]) if trades else 0.0
        win_rate = len(winning) / num_trades if num_trades > 0 else 0.0

        # Max drawdown
        equity_curve = portfolio.get_equity_curve()
        max_dd = 0.0
        peak = self.initial_capital
        for _, equity in equity_curve:
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

        # Sharpe ratio (annualized, assuming daily returns)
        if len(equity_curve) > 1:
            equities = [e for _, e in equity_curve]
            returns = pd.Series(equities).pct_change().dropna()
            if returns.std() > 0:
                sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        return BacktestResult(
            strategy_name=self.strategy.name,
            symbol=symbol,
            start_date=data.index[0],
            end_date=data.index[-1],
            initial_capital=self.initial_capital,
            final_equity=portfolio.total_equity,
            total_return_pct=portfolio.total_return_pct,
            num_trades=num_trades,
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=win_rate,
            avg_trade_pnl=float(avg_pnl),
            max_drawdown_pct=max_dd,
            sharpe_ratio=float(sharpe),
            equity_curve=equity_curve,
            trades=trades,
        )
